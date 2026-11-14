"""Offline installer contract checks: no downloads, root writes or real services."""
import hashlib
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/install.sh"
ROOT = "flownote-v0.3.5-linux-amd64"
ARCHIVE = ROOT + ".tar.gz"

class Installer(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="flownote-installer-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.mock = self.base / "bin"
        self.mock.mkdir()
        self.assets = self.base / "assets"
        self.assets.mkdir()
        self.env = dict(os.environ, PATH=str(self.mock) + os.pathsep + os.environ["PATH"],
                        FIXTURE_ASSETS=str(self.assets), TEST_ARCH="x86_64", TEST_OS="Linux")
        self.write_tool("uname", '#!/bin/sh\nif [ "$1" = -s ]; then echo "$TEST_OS"; else echo "$TEST_ARCH"; fi\n')
        self.write_tool("curl", '''#!/usr/bin/env python3
import os, pathlib, shutil, sys
args = sys.argv[1:]
assert '--proto' in args and '--proto-redir' in args and '--tlsv1.2' in args
assert args[args.index('--proto')+1] == '=https'
assert args[args.index('--proto-redir')+1] == '=https'
assert args[-1].startswith('https://github.com/youbilin/FlowNote/releases/download/v0.3.5/')
shutil.copyfile(pathlib.Path(os.environ['FIXTURE_ASSETS']) / args[-1].rsplit('/',1)[1], args[args.index('--output')+1])
''')
        self.package()

    def write_tool(self, name, text):
        path = self.mock / name
        path.write_text(text)
        path.chmod(0o755)

    def package(self, variant="valid"):
        with tarfile.open(self.assets / ARCHIVE, "w:gz") as tar:
            directory = tarfile.TarInfo(ROOT + "/")
            directory.type, directory.mode = tarfile.DIRTYPE, 0o755
            tar.addfile(directory)
            for name in ["flownote", "config.example.toml", "config.https.example.toml", "xray-https-snippet.json", "flownote.service", "xray-snippet.json", "LICENSE", "INSTALL.md", "setup.sh", "setup.py"]:
                version = "0.0.0" if variant == "version" else "0.3.5"
                data = f'#!/bin/sh\nprintf "flownote {version}\\n"\n'.encode() if name == "flownote" else b"fixture\n"
                info = tarfile.TarInfo(f"{ROOT}/{name}")
                info.mode, info.size = (0o755 if name == "flownote" else 0o644), len(data)
                if variant == "symlink" and name == "config.example.toml":
                    info.type, info.linkname, info.size = tarfile.SYMTYPE, "/etc/passwd", 0
                    tar.addfile(info)
                else:
                    tar.addfile(info, io.BytesIO(data))
            if variant == "traversal":
                info = tarfile.TarInfo("../escaped")
                tar.addfile(info, io.BytesIO(b""))
        checksum = hashlib.sha256((self.assets / ARCHIVE).read_bytes()).hexdigest()
        self.manifest = f"{checksum}  {ARCHIVE}\n"
        (self.assets / "SHA256SUMS").write_text(self.manifest)

    def run_installer(self, *args, success=False):
        result = subprocess.run(["bash", str(SCRIPT), *args], env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def download(self, success=False):
        return self.run_installer("--download-only", str(self.base / "out"), success=success)

    def test_valid_package_is_verified_and_saved(self):
        self.download(success=True)
        self.assertEqual((self.base / "out" / ARCHIVE).read_bytes(), (self.assets / ARCHIVE).read_bytes())
        self.assertEqual(list((self.base / "out").glob("*.tar.gz")), [self.base / "out" / ARCHIVE])

    def test_bad_checksum_writes_nothing(self):
        (self.assets / "SHA256SUMS").write_text("0" * 64 + f"  {ARCHIVE}\n")
        self.assertIn("SHA-256 mismatch", self.download().stderr)
        self.assertFalse((self.base / "out").exists())

    def test_duplicate_checksum_is_rejected(self):
        (self.assets / "SHA256SUMS").write_text(self.manifest * 2)
        self.assertIn("unique valid entry", self.download().stderr)

    def test_traversal_is_rejected_before_extraction(self):
        self.package("traversal")
        self.assertIn("archive layout", self.download().stderr)
        self.assertFalse((self.base / "out").exists())

    def test_symlink_is_rejected(self):
        self.package("symlink")
        self.assertIn("Links or special", self.download().stderr)

    def test_wrong_binary_version_is_rejected(self):
        self.package("version")
        self.assertIn("Binary version mismatch", self.download().stderr)

    def test_existing_download_is_preserved(self):
        out = self.base / "out"
        out.mkdir()
        (out / ARCHIVE).write_bytes(b"keep")
        self.download()
        self.assertEqual((out / ARCHIVE).read_bytes(), b"keep")

    def test_setup_rejects_download_only_and_noninteractive_input(self):
        self.assertIn("cannot be combined", self.run_installer("--setup", "--download-only", str(self.base / "out")).stderr)
        self.assertIn("interactive terminal", self.run_installer("--setup").stderr)

    def test_unsupported_platforms_and_bad_options(self):
        self.env["TEST_ARCH"] = "riscv64"
        self.assertIn("Supported architectures", self.download().stderr)
        self.env["TEST_ARCH"], self.env["TEST_OS"] = "x86_64", "Darwin"
        self.assertIn("Only Linux", self.download().stderr)
        self.assertIn("Version must", self.run_installer("--version", "../../main").stderr)
        self.run_installer("--help", success=True)
        self.run_installer("--unknown")

if __name__ == "__main__":
    unittest.main(verbosity=2)
