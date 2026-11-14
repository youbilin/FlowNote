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


    def test_unmerge_preserves_nodes_and_restores_only_log_keys(self):
        installed = wizard.merged_config(self.template, "/var/log/flownote-xray/access.log")
        current = copy.deepcopy(installed)
        current["log"]["loglevel"] = "debug"
        current["policy"]["system"] = {"statsInboundUplink": True}
        cleaned = wizard.unmerged_config(current, self.template, installed)
        self.assertEqual(cleaned["outbounds"], self.template["outbounds"])
        self.assertEqual(cleaned["inbounds"], self.template["inbounds"])
        self.assertEqual(cleaned["routing"], self.template["routing"])
        self.assertEqual(cleaned["log"]["access"], "none")
        self.assertEqual(cleaned["log"]["loglevel"], "debug")
        self.assertNotIn("maskAddress", cleaned["log"])
        self.assertIn("system", cleaned["policy"])
        self.assertEqual(current["log"]["access"], "/var/log/flownote-xray/access.log")

    def test_unmerge_keeps_custom_log_and_is_idempotent(self):
        installed = wizard.merged_config(self.template, "/var/log/access.log")
        current = copy.deepcopy(installed)
        current["log"]["access"] = "/var/log/changed.log"
        current["log"]["maskAddress"] = "quarter"
        cleaned = wizard.unmerged_config(current, self.template, installed)
        self.assertEqual(cleaned["log"], current["log"])
        self.assertEqual(wizard.unmerged_config(cleaned), cleaned)

    def test_unmerge_refuses_custom_or_default_query_outbound(self):
        for kind in ("redirect", "finalRules", "default", "duplicate"):
            value = wizard.merged_config(self.template, "/var/log/access.log")
            query = next(o for o in value["outbounds"] if o["tag"] == wizard.QUERY)
            if kind == "default":
                value["outbounds"].remove(query)
                value["outbounds"].insert(0, query)
            elif kind == "duplicate":
                value["outbounds"].append(query)
            else:
                query["settings"][kind] = "custom"
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                wizard.unmerged_config(value)

    def test_unmerge_refuses_custom_routes_and_balancer_references(self):
        for rule in ({"type": "field", "domain": ["example.com"], "outboundTag": wizard.QUERY}, None, "prefix"):
            value = wizard.merged_config(self.template, "/var/log/access.log")
            if isinstance(rule, dict):
                value["routing"]["rules"].append(rule)
            else:
                value["routing"]["balancers"] = [{"tag": "shared", "selector": ["traffic-" if rule == "prefix" else wizard.QUERY]}]
            with self.assertRaises(ValueError):
                wizard.unmerged_config(value)

    def test_unmerge_accepts_old_core_without_final_rules(self):
        value = wizard.merged_config(self.template, "/var/log/access.log", False)
        self.assertEqual(wizard.unmerged_config(value)["outbounds"], self.template["outbounds"])

    def test_original_log_settings_searches_past_repeat_setups(self):
        installed = wizard.merged_config(self.template, "/var/log/flownote-xray/access.log")
        for name, original in (("001", self.original), ("002", json.dumps(installed))):
            directory = self.root / "backups" / name
            directory.mkdir(parents=True)
            with wizard.connection(directory / "x-ui.before.db") as conn:
                conn.execute("CREATE TABLE settings (key TEXT,value TEXT)")
                conn.execute("INSERT INTO settings VALUES ('xrayTemplateConfig',?)", (original,))
            (directory / "xray-template.after.json").write_text(json.dumps(installed))
        before, after = wizard.original_log_settings(self.root / "backups")
        self.assertEqual(before, self.template)
        self.assertEqual(after, installed)

    def test_fixed_cleanup_rejects_symlink_and_unlisted_path(self):
        target = self.root / "outside"
        target.mkdir()
        (target / "keep").write_text("keep")
        link = self.root / "owned"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            wizard.remove_owned(link, {link})
        with self.assertRaises(ValueError):
            wizard.remove_owned(target, {link})
        self.assertEqual((target / "keep").read_text(), "keep")

    def test_fixed_cleanup_refuses_nested_mount_and_keeps_external_link(self):
        owned = self.root / "owned"
        nested = owned / "nested"
        nested.mkdir(parents=True)
        with patch.object(wizard.os.path, "ismount", side_effect=lambda p: Path(p) == nested):
            with self.assertRaises(ValueError):
                wizard.remove_owned(owned, {owned})
        external = self.root / "outside"
        external.write_text("keep")
        (owned / "link").symlink_to(external)
        wizard.remove_owned(owned, {owned})
        self.assertEqual(external.read_text(), "keep")
        self.assertFalse(owned.exists())

    def uninstall_fixture(self, mode="1", confirmation=None, fail=False, modified=False, restore=True, interrupt=False, fresh=None, overlap=False):
        installed = wizard.merged_config(self.template, "/var/log/flownote-xray/access.log")
        if modified:
            installed["outbounds"][2]["settings"]["redirect"] = "127.0.0.1:9999"
        with wizard.connection(self.db) as conn:
            conn.execute("UPDATE settings SET value=? WHERE key='xrayTemplateConfig'", (json.dumps(installed),))
        if fresh:
            with wizard.connection(self.db) as conn:
                conn.execute("DELETE FROM settings WHERE key='xrayTemplateConfig'")
        app = (self.root / "bin/flownote", self.root / "bin/flownote-setup", self.root / "share")
        data = (self.root / "config", self.root / "history", self.root / "backups")
        logs = (self.root / "logs", self.root / "rotate")
        for path in (app[0], app[1]):
            path.parent.mkdir(exist_ok=True)
            path.write_text("installed")
        for path in (app[2],) + data + logs:
            path.mkdir()
            (path / "keep").write_text("private fixture")
        core = self.root / "panel/bin/xray"
        core.parent.mkdir(parents=True)
        (core.parent / "config.json").write_text(json.dumps(self.template if fresh == "clean" else installed))
        args = wizard.argparse.Namespace(db=str(self.db), xui_dir=str(core.parent.parent), core=str(core))
        calls = []
        failed = False
        def run(arguments, **kwargs):
            nonlocal failed
            calls.append(arguments)
            if fail and not failed and arguments == ["systemctl", "start", "x-ui"]:
                failed = True
                if interrupt:
                    raise KeyboardInterrupt()
                raise wizard.subprocess.CalledProcessError(1, arguments)
        with patch.object(wizard, "APP_FILES", app), patch.object(wizard, "DATA_PATHS", (self.root, data[1], data[2]) if overlap else data), \
             patch.object(wizard, "LOG_PATHS", logs), patch.object(wizard, "BACKUP_ROOT", data[2]), \
             patch.object(wizard, "original_log_settings", return_value=(self.template, installed) if restore else (None, None)), \
             patch.object(wizard, "discover", return_value=(core.parent.parent, self.db, core, {}, None)), \
             patch.object(wizard, "check_environment"), patch.object(wizard, "test_xray"), \
             patch.object(wizard, "wait_service"), patch.object(wizard, "remove_service_account") as account, \
             patch.object(wizard, "command", side_effect=run), patch.object(wizard.os, "fchown"), \
             patch.object(wizard.os, "chown"), patch.object(wizard.subprocess, "run", return_value=wizard.subprocess.CompletedProcess([],0)), \
             patch("builtins.input", side_effect=[mode, confirmation or ("DELETE" if mode == "2" else "UNINSTALL")]):
            if fail or modified or fresh == "query" or overlap:
                with self.assertRaises(ValueError):
                    wizard.uninstall(args)
                result = None
            else:
                result = wizard.uninstall(args)
            account_deleted = account.called
        return app, data, logs, calls, result, account_deleted, installed

    def test_uninstall_keep_mode_preserves_token_history_and_backups(self):
        app, data, logs, calls, result, account, installed = self.uninstall_fixture()
        self.assertTrue(result)
        self.assertTrue(all(not p.exists() for p in app))
        self.assertTrue(all((p / "keep").is_file() for p in data + logs))
        self.assertFalse(account)
        self.assertEqual(json.loads(self.setting("xrayTemplateConfig")), self.template)
        self.assertEqual(self.setting("subEnable"), "false")
        self.assertIn(["systemctl", "disable", "flownote"], calls)

    def test_uninstall_purge_removes_only_allowed_data_after_panel_recovery(self):
        app, data, logs, calls, result, account, _ = self.uninstall_fixture("2")
        self.assertTrue(result and account)
        self.assertTrue(all(not p.exists() for p in app + data + logs))
        self.assertTrue(self.db.is_file())
        with wizard.connection(self.db) as conn:
            self.assertEqual(conn.execute("SELECT up FROM client_traffics").fetchone()[0], 1234)
        self.assertLess(calls.index(["systemctl", "start", "x-ui"]), calls.index(["systemctl", "disable", "flownote"]))

    def test_uninstall_cancel_has_no_host_mutations(self):
        app, data, _, calls, result, account, _ = self.uninstall_fixture("2", "no")
        self.assertFalse(result or account or calls)
        self.assertTrue(all(p.exists() for p in app + data))

    def test_uninstall_panel_failure_keeps_files_and_restores_template(self):
        app, data, _, calls, _, account, installed = self.uninstall_fixture("2", fail=True)
        self.assertTrue(all(p.exists() for p in app + data))
        self.assertFalse(account)
        self.assertEqual(json.loads(self.setting("xrayTemplateConfig")), installed)
        self.assertNotIn(["systemctl", "disable", "flownote"], calls)
        self.assertIn(["systemctl", "start", "flownote"], calls)

    def test_uninstall_modified_query_stops_before_confirmation_or_removal(self):
        app, data, _, calls, _, _, _ = self.uninstall_fixture("2", modified=True)
        self.assertTrue(all(p.exists() for p in app + data))
        self.assertFalse(calls)

    def test_uninstall_preserves_log_and_account_if_original_log_cannot_be_restored(self):
        app, data, logs, _, result, account, _ = self.uninstall_fixture("2", restore=False)
        self.assertTrue(result)
        self.assertFalse(account)
        self.assertTrue(all(not p.exists() for p in app + data))
        self.assertTrue(all(p.exists() for p in logs))
        self.assertEqual(json.loads(self.setting("xrayTemplateConfig"))["log"]["access"], "/var/log/flownote-xray/access.log")

    def test_uninstall_interrupt_restores_template_and_keeps_app(self):
        app, data, _, _, _, _, installed = self.uninstall_fixture("2", fail=True, interrupt=True)
        self.assertTrue(all(p.exists() for p in app + data))
        self.assertEqual(json.loads(self.setting("xrayTemplateConfig")), installed)

    def test_uninstall_menu_back_does_not_read_or_write_host(self):
        with patch("builtins.input", return_value="0"), patch.object(wizard, "command") as command, patch.object(wizard, "read_settings") as read:
            self.assertFalse(wizard.uninstall(wizard.argparse.Namespace()))
            command.assert_not_called()
            read.assert_not_called()

    def test_service_account_cleanup_refuses_root_or_nonstandard_user(self):
        for uid, home, shell in ((0, "/var/lib/flownote", "/usr/sbin/nologin"), (1000, "/home/user", "/bin/bash")):
            user = wizard.argparse.Namespace(pw_uid=uid, pw_dir=home, pw_shell=shell)
            with patch.object(wizard.pwd, "getpwnam", return_value=user), patch.object(wizard, "command") as command:
                wizard.remove_service_account()
                command.assert_not_called()

    def test_uninstall_fresh_panel_without_persisted_template_needs_no_restart(self):
        app, data, _, calls, result, _, _ = self.uninstall_fixture(fresh="clean")
        self.assertTrue(result)
        self.assertTrue(all(not p.exists() for p in app))
        self.assertTrue(all(p.exists() for p in data))
        self.assertNotIn(["systemctl", "stop", "x-ui"], calls)

    def test_uninstall_runtime_only_query_config_requires_persisted_template(self):
        app, _, _, calls, _, _, _ = self.uninstall_fixture(fresh="query")
        self.assertTrue(all(p.exists() for p in app))
        self.assertFalse(calls)

    def test_uninstall_refuses_purge_directory_containing_panel_database(self):
        app, _, _, calls, _, _, _ = self.uninstall_fixture(mode="2", overlap=True)
        self.assertTrue(self.db.is_file())
        self.assertTrue(all(p.exists() for p in app))
        self.assertFalse(calls)

    def test_uninstall_running_panel_with_missing_db_stops_without_file_removal(self):
        args = wizard.argparse.Namespace(db=str(self.root / "missing.db"))
        with patch("builtins.input", return_value="2"), patch.object(wizard.subprocess, "run", return_value=wizard.subprocess.CompletedProcess([],0)), patch.object(wizard, "command") as command:
            with self.assertRaisesRegex(ValueError, "--db"):
                wizard.uninstall(args)
            command.assert_not_called()
        self.assertFalse(Path(args.db).exists())

    def test_uninstall_concurrent_template_edit_is_preserved_and_panel_restarted(self):
        other = json.dumps(dict(self.template, concurrent="keep"))
        def changed(*args):
            with wizard.connection(self.db) as conn:
                conn.execute("UPDATE settings SET value=? WHERE key='xrayTemplateConfig'", (other,))
            raise ValueError("concurrent edit")
        with patch.object(wizard, "snapshot_and_update", side_effect=changed), patch.object(wizard, "command") as command, patch.object(wizard, "wait_service"):
            with self.assertRaises(ValueError):
                wizard.uninstall_xray(self.db, self.original, "replacement", self.root, self.root / "xray")
            self.assertIn(unittest.mock.call(["systemctl", "start", "x-ui"]), command.call_args_list)
        self.assertEqual(self.setting("xrayTemplateConfig"), other)

if __name__ == "__main__":
    unittest.main(verbosity=2)
