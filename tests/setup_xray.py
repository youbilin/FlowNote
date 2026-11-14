"""Real Xray preflight regression; temporary files only, no panel or systemd changes.
Usage: python3 tests/setup_xray.py /absolute/path/to/xray
"""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("wizard", Path(__file__).resolve().parents[1] / "scripts/setup.py")
wizard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wizard)
CORE = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 else None


@unittest.skipUnless(CORE and CORE.is_file(), "supply an Xray executable path")
class RealXray(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="flownote-xray-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.real_log = self.root / "not-created-yet/access.log"
        self.value = wizard.merged_config({
            "inbounds": [], "outbounds": [{"protocol": "freedom", "tag": "direct"}],
            "log": {"access": "none", "error": "none", "loglevel": "warning"},
        }, str(self.real_log))
        # The test runs unprivileged; production private writer remains root-owned.
        ownership = patch.object(wizard.os, "fchown")
        ownership.start()
        self.addCleanup(ownership.stop)

    def test_old_order_reproduces_missing_log_directory(self):
        with self.assertRaises(wizard.XrayCheckError) as raised:
            wizard.test_xray(CORE, self.value, self.root)
        self.assertIn(str(self.root / "xray-check.stdout.log"), str(raised.exception))
        self.assertFalse(raised.exception.final_rules_unsupported)
        self.assertIn("no such file or directory", (self.root / "xray-check.stdout.log").read_text())

    def test_preflight_succeeds_without_creating_real_log_directory(self):
        original = copy.deepcopy(self.value)
        wizard.test_xray(CORE, self.value, self.root, stage_access_log=True)
        self.assertFalse(self.real_log.parent.exists())
        self.assertEqual(self.value, original)

    def test_exact_check_succeeds_after_real_log_prepared(self):
        wizard.test_xray(CORE, self.value, self.root, stage_access_log=True)
        self.real_log.parent.mkdir()
        wizard.write_private(self.real_log, "")
        wizard.test_xray(CORE, self.value, self.root)
        self.assertEqual(json.loads((self.root / "xray-check.json").read_text()), self.value)

    def test_other_config_error_still_fails_during_preflight(self):
        self.value["outbounds"][0]["protocol"] = "fixture-invalid-protocol"
        with self.assertRaises(wizard.XrayCheckError) as raised:
            wizard.test_xray(CORE, self.value, self.root, stage_access_log=True)
        self.assertFalse(raised.exception.final_rules_unsupported)
        self.assertFalse(self.real_log.parent.exists())

    def test_log_error_has_private_diagnostics(self):
        self.real_log.parent.mkdir()
        self.real_log.mkdir()  # A directory cannot be opened as the access log.
        with self.assertRaises(wizard.XrayCheckError):
            wizard.test_xray(CORE, self.value, self.root)
        for name in ("xray-check.json", "xray-check.stdout.log", "xray-check.stderr.log"):
            self.assertEqual((self.root / name).stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main(verbosity=2)
