"""Setup wizard checks using synthetic SQLite databases; no host services are modified."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("flownote_setup", Path(__file__).resolve().parents[1] / "scripts/setup.py")
wizard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wizard)


class Setup(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="flownote-setup-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.template = {
            "outbounds": [{"tag": "direct", "protocol": "freedom", "settings": {"keep": True}},
                          {"tag": "blocked", "protocol": "blackhole", "settings": {}}],
            "inbounds": [{"tag": "original-node", "settings": {"clients": [{"id": "fixture-secret"}]}}],
            "routing": {"domainStrategy": "AsIs", "rules": [{"type": "field", "inboundTag": ["api"], "outboundTag": "api"}]},
            "log": {"access": "none", "error": "error.log", "loglevel": "warning"},
            "policy": {"levels": {"0": {"statsUserUplink": True}}},
        }
        self.original = json.dumps(self.template)
        self.db = self.root / "x-ui.db"
        with wizard.connection(self.db) as conn:
            conn.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY, key TEXT, value TEXT)")
            conn.executemany("INSERT INTO settings(key,value) VALUES (?,?)", [
                ("xrayTemplateConfig", self.original), ("webPort", "39876"),
                ("webBasePath", "/private-path/"), ("subEnable", "false"),
                ("apiToken", "must-not-be-discovered"), ("webCertFile", ""),
            ])
            conn.execute("CREATE TABLE client_traffics (email TEXT, up INTEGER)")
            conn.execute("INSERT INTO client_traffics VALUES ('alice', 1234)")

    def setting(self, name):
        with wizard.connection(self.db) as conn:
            return conn.execute("SELECT value FROM settings WHERE key=?", (name,)).fetchone()[0]

    def test_discovery_reads_only_allowlisted_keys(self):
        settings = wizard.read_settings(self.db)
        self.assertNotIn("apiToken", settings)
        self.assertNotIn("subEnable", settings)
        self.assertEqual(wizard.panel_default(settings), "http://127.0.0.1:39876/private-path")
        self.assertEqual(self.setting("subEnable"), "false")

    def test_missing_database_is_not_created(self):
        missing = self.root / "missing.db"
        with self.assertRaises(ValueError):
            wizard.read_settings(missing)
        self.assertFalse(missing.exists())

    def test_duplicate_database_setting_is_rejected(self):
        with wizard.connection(self.db) as conn:
            conn.execute("INSERT INTO settings(key,value) VALUES ('webPort','2053')")
        with self.assertRaises(ValueError):
            wizard.read_settings(self.db)

    def test_https_or_custom_listen_requires_explicit_url(self):
        for settings in [{"webCertFile": "/cert.pem"}, {"webKeyFile": "/key.pem"}, {"webListen": "192.0.2.1"}]:
            self.assertIsNone(wizard.panel_default(settings))
        self.assertEqual(wizard.panel_default({"webListen": "::1"}), "http://[::1]:2053")

    def test_url_does_not_allow_plain_remote_or_embedded_secrets(self):
        for url in ["http://panel.example.com", "https://u:p@panel.example.com", "https://panel.example.com/?token=x",
                    "https://panel.example.com/#secret", "ftp://localhost", "http://127.0.0.1:99999", "https://panel.example.com/a\nb"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                wizard.validate_url(url)
        self.assertEqual(wizard.validate_url("https://panel.example.com:2053/base/"), "https://panel.example.com:2053/base")

    def test_merge_preserves_nodes_default_outbound_and_other_settings(self):
        old = copy.deepcopy(self.template)
        merged = wizard.merged_config(self.template, "/var/log/flownote-xray/access.log")
        self.assertEqual(self.template, old)
        for key in ("inbounds", "policy"):
            self.assertEqual(merged[key], old[key])
        self.assertEqual(merged["outbounds"][:2], old["outbounds"])
        self.assertEqual(merged["log"]["error"], "error.log")
        self.assertEqual(merged["routing"]["rules"][2:], old["routing"]["rules"])
        self.assertEqual(merged["routing"]["rules"][0]["port"], "80")
        self.assertEqual(merged["routing"]["rules"][0]["ip"], ["6.6.6.6/32"])
        self.assertNotIn("port", merged["routing"]["rules"][1])

    def test_merge_is_idempotent_and_supports_old_core_without_final_rules(self):
        merged = wizard.merged_config(self.template, "/var/log/access.log")
        self.assertEqual(wizard.merged_config(merged, "/var/log/access.log"), merged)
        old = wizard.merged_config(merged, "/var/log/access.log", False)
        self.assertNotIn("finalRules", old["outbounds"][2]["settings"])
        self.assertEqual(wizard.merged_config(old, "/var/log/access.log"), merged)

    def test_conflicting_outbound_is_never_overwritten(self):
        for tag in (wizard.QUERY, wizard.BLOCK):
            value = copy.deepcopy(self.template)
            value["outbounds"].append({"tag": tag, "protocol": "unexpected"})
            with self.assertRaises(ValueError):
                wizard.merged_config(value, "/var/log/access.log")

    def test_duplicate_or_default_query_outbound_is_rejected(self):
        merged = wizard.merged_config(self.template, "/var/log/access.log")
        merged["outbounds"].append(copy.deepcopy(merged["outbounds"][2]))
        with self.assertRaises(ValueError):
            wizard.merged_config(merged, "/var/log/access.log")
        merged = wizard.merged_config(self.template, "/var/log/access.log")
        merged["outbounds"].insert(0, merged["outbounds"].pop(2))
        with self.assertRaises(ValueError):
            wizard.merged_config(merged, "/var/log/access.log")

    def test_unknown_existing_query_route_is_rejected(self):
        value = copy.deepcopy(self.template)
        value["routing"]["rules"].append({"outboundTag": wizard.QUERY, "port": "443"})
        with self.assertRaises(ValueError):
            wizard.merged_config(value, "/var/log/access.log")

    def test_invalid_shapes_or_paths_fail_before_mutation(self):
        for value in [{}, {"outbounds": []}, {"outbounds": ["bad"]}]:
            with self.assertRaises(ValueError):
                wizard.merged_config(value, "/var/log/access.log")
        for path in ["relative", "/tmp/hello\nworld"]:
            with self.assertRaises(ValueError):
                wizard.merged_config(self.template, path)

    def test_duplicate_or_oversized_json_is_rejected(self):
        for raw in ['{"a":1,"a":2}', '[]', ' ' * (4 * 1024 * 1024 + 1)]:
            with self.assertRaises(ValueError):
                wizard.load_json(raw)

    def test_config_is_valid_toml_and_escapes_paths(self):
        import tomllib
        raw = wizard.configuration("http://127.0.0.1:2053/private", '/var/log/a"b.log')
        cfg = tomllib.loads(raw)
        self.assertEqual(cfg["server"]["protocol"], "http")
        self.assertEqual(cfg["server"]["domain"], "6.6.6.6")
        self.assertEqual(cfg["xray"]["access_log"], '/var/log/a"b.log')
        self.assertNotIn("tls", cfg)
        self.assertNotIn("token =", raw)

    def test_snapshot_updates_only_template_and_can_restore(self):
        backup = self.root / "backup.db"
        merged = json.dumps(wizard.merged_config(self.template, "/var/log/access.log"))
        wizard.snapshot_and_update(self.db, backup, self.original, merged)
        self.assertEqual(self.setting("xrayTemplateConfig"), merged)
        self.assertEqual(self.setting("subEnable"), "false")
        with wizard.connection(backup) as conn:
            self.assertEqual(conn.execute("SELECT value FROM settings WHERE key='xrayTemplateConfig'").fetchone()[0], self.original)
            self.assertEqual(conn.execute("SELECT up FROM client_traffics").fetchone()[0], 1234)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        with wizard.connection(self.db) as conn:
            conn.execute("UPDATE client_traffics SET up=5678")
        wizard.restore_setting(self.db, merged, self.original)
        self.assertEqual(self.setting("xrayTemplateConfig"), self.original)
        with wizard.connection(self.db) as conn:
            self.assertEqual(conn.execute("SELECT up FROM client_traffics").fetchone()[0], 5678)

    def test_concurrent_template_change_aborts_without_backup_or_write(self):
        backup = self.root / "backup.db"
        with self.assertRaises(ValueError):
            wizard.snapshot_and_update(self.db, backup, "stale", "bad")
        self.assertFalse(backup.exists())
        self.assertEqual(self.setting("xrayTemplateConfig"), self.original)

    def test_rollback_does_not_overwrite_unrelated_template_edit(self):
        with self.assertRaises(ValueError):
            wizard.restore_setting(self.db, "different", "old")
        self.assertEqual(self.setting("xrayTemplateConfig"), self.original)

    def test_private_writer_rejects_symlinks_and_keeps_old_target(self):
        target = self.root / "secret"
        target.write_text("keep")
        link = self.root / "link"
        link.symlink_to(target)
        with self.assertRaises(ValueError):
            wizard.write_private(link, "replace")
        self.assertEqual(target.read_text(), "keep")

    def test_core_check_has_test_flag_no_shell_and_private_candidate(self):
        core = self.root / "xray"
        with patch.object(wizard, "write_private") as write, patch.object(wizard, "command") as run:
            wizard.test_xray(core, self.template, self.root)
        args = run.call_args.args[0]
        self.assertEqual(args[:3], [str(core), "run", "-test"])
        self.assertEqual(run.call_args.kwargs["env"]["XRAY_LOCATION_ASSET"], str(core.parent))
        self.assertEqual(write.call_args.args[0], self.root / "xray-check.json")

    def apply_fixture(self, fail_at=None, interrupt=False):
        directory = self.root / "backup"
        directory.mkdir()
        config = self.root / "config.toml"
        token = self.root / "token"
        config.write_text("old config")
        token.write_text("old token")
        replacement = json.dumps(wizard.merged_config(self.template, "/var/log/access.log"))
        calls = []
        failed = False
        def run(args, **kwargs):
            nonlocal failed
            calls.append(args)
            if not failed and fail_at and fail_at in " ".join(args):
                failed = True
                if interrupt:
                    raise KeyboardInterrupt()
                raise wizard.subprocess.CalledProcessError(1, args)
        patches = (patch.object(wizard, "command", side_effect=run),
                   patch.object(wizard, "grant_log"), patch.object(wizard, "wait_service"),
                   patch.object(wizard.subprocess, "run", return_value=wizard.subprocess.CompletedProcess([], 0)),
                   patch.object(wizard.os, "fchown"))
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            if fail_at:
                with self.assertRaises(ValueError):
                    wizard.apply_changes(self.db, directory, self.original, replacement,
                                         config, "new config", token, "new token", 1,
                                         "/var/log/access.log", "alice", self.root / "xray")
            else:
                wizard.apply_changes(self.db, directory, self.original, replacement,
                                     config, "new config", token, "new token", 1,
                                     "/var/log/access.log", "alice", self.root / "xray")
        return directory, config, token, calls, replacement

    def test_full_apply_keeps_node_settings_and_enables_service(self):
        directory, config, token, calls, replacement = self.apply_fixture()
        self.assertEqual(self.setting("xrayTemplateConfig"), replacement)
        self.assertEqual(self.setting("subEnable"), "false")
        self.assertEqual(config.read_text(), "new config")
        self.assertEqual(token.read_text(), "new token\n")
        self.assertEqual(token.stat().st_mode & 0o777, 0o640)
        self.assertEqual((directory / "token.before").stat().st_mode & 0o777, 0o600)
        self.assertEqual(calls[-1], ["systemctl", "enable", "flownote"])
        self.assertLess(next(i for i,c in enumerate(calls) if "--check-panel" in c), calls.index(["systemctl", "stop", "x-ui"]))
        self.assertFalse(any("new token" in " ".join(c) for c in calls))

    def test_panel_failure_restores_files_without_stopping_xui(self):
        directory, config, token, calls, _ = self.apply_fixture("--check-panel")
        self.assertEqual(config.read_text(), "old config")
        self.assertEqual(token.read_text(), "old token")
        self.assertNotIn(["systemctl", "stop", "x-ui"], calls)
        self.assertFalse((directory / "x-ui.before.db").exists())
        self.assertEqual(self.setting("xrayTemplateConfig"), self.original)

    def test_service_failure_rolls_back_only_template_and_files(self):
        directory, config, token, calls, _ = self.apply_fixture("restart flownote")
        self.assertEqual(config.read_text(), "old config")
        self.assertEqual(token.read_text(), "old token")
        self.assertEqual(self.setting("xrayTemplateConfig"), self.original)
        self.assertTrue((directory / "x-ui.before.db").exists())
        self.assertEqual(calls.count(["systemctl", "start", "x-ui"]), 2)

    def test_interrupt_after_database_update_also_rolls_back(self):
        _, config, token, _, _ = self.apply_fixture("restart flownote", interrupt=True)
        self.assertEqual(self.setting("xrayTemplateConfig"), self.original)
        self.assertEqual(config.read_text(), "old config")
        self.assertEqual(token.read_text(), "old token")

    def environment_fixture(self, values=None):
        base = self.root / "panel"
        base.mkdir()
        (base / "x-ui").touch()
        core = base / "bin/xray-linux-amd64"
        core.parent.mkdir()
        core.touch()
        proc = self.root / "proc"
        for item in (proc / "123", proc / "self"):
            (item / "ns").mkdir(parents=True)
            (item / "ns/net").symlink_to("net:[1234]")
        (proc / "123/exe").symlink_to(base / "x-ui")
        (proc / "123/cwd").symlink_to(base)
        settings = {"XUI_DB_FOLDER": str(self.root), "XUI_PORT": "54321"}
        settings.update(values or {})
        (proc / "123/environ").write_bytes(b"\0".join((k + "=" + v).encode() for k,v in settings.items()))
        return base, core, proc

    def test_running_environment_uses_port_and_relative_directories(self):
        base, core, proc = self.environment_fixture({"XUI_DB_FOLDER": "..", "XUI_BIN_FOLDER": "bin"})
        with patch.object(wizard, "command", return_value=wizard.subprocess.CompletedProcess([], 0, stdout="123\n")):
            self.assertEqual(wizard.check_environment(base, self.db, core, proc), "54321")

    def test_environment_rejects_wrong_database_and_postgres(self):
        base, core, proc = self.environment_fixture({"XUI_DB_TYPE": "postgres"})
        with patch.object(wizard, "command", return_value=wizard.subprocess.CompletedProcess([], 0, stdout="123")):
            with self.assertRaisesRegex(ValueError, "SQLite"):
                wizard.check_environment(base, self.db, core, proc)
            (proc / "123/environ").write_bytes(b"XUI_DB_FOLDER=/different/database")
            with self.assertRaisesRegex(ValueError, "--db"):
                wizard.check_environment(base, self.db, core, proc)

    def test_environment_rejects_container_namespace_and_other_core(self):
        base, core, proc = self.environment_fixture()
        with patch.object(wizard, "command", return_value=wizard.subprocess.CompletedProcess([], 0, stdout="123")):
            with self.assertRaisesRegex(ValueError, "--core"):
                wizard.check_environment(base, self.db, base / "other/xray", proc)
            (proc / "123/ns/net").unlink()
            (proc / "123/ns/net").symlink_to("net:[5678]")
            with self.assertRaisesRegex(ValueError, "容器"):
                wizard.check_environment(base, self.db, core, proc)

    def test_existing_final_rules_are_not_silently_relaxed(self):
        value = wizard.merged_config(self.template, "/var/log/access.log")
        value["outbounds"][2]["settings"]["finalRules"] = [{"action": "block"}]
        with self.assertRaises(ValueError):
            wizard.merged_config(value, "/var/log/access.log")


if __name__ == "__main__":
    unittest.main(verbosity=2)
