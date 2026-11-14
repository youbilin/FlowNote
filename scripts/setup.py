#!/usr/bin/env python3
"""Local interactive setup for the standard Linux 3x-ui installation (stdlib only)."""
import argparse
import copy
from contextlib import closing, contextmanager
import datetime
import getpass
import grp
import json
import os
from pathlib import Path
import pwd
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

KEYS = ("webPort", "webListen", "webBasePath", "webCertFile", "webKeyFile", "webDomain", "xrayTemplateConfig")
QUERY = "traffic-query"
BLOCK = "flownote-block"


def command(args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, timeout=30, **kwargs)


@contextmanager
def connection(*args, **kwargs):
    with closing(sqlite3.connect(*args, **kwargs)) as conn:
        with conn:
            yield conn


def load_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("JSON contains duplicate keys")
            result[key] = value
        return result
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("Xray config exceeds 4 MiB")
    result = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(result, dict):
        raise ValueError("Xray config must be an object")
    return result


def read_settings(db):
    if not db.is_file():
        raise ValueError("未找到面板数据库，请使用 --db 指定 SQLite 文件")
    with connection(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as conn:
        rows = conn.execute("SELECT key,value FROM settings WHERE key IN (" + ",".join("?" for _ in KEYS) + ")", KEYS)
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError("面板存在重复设置，停止自动配置")
            result[key] = value
        return result


def validate_url(value):
    url = urlsplit(value)
    if (url.scheme not in ("http", "https") or not url.hostname or url.username is not None
            or url.password is not None or url.query or url.fragment
            or any(ord(c) < 33 for c in value)):
        raise ValueError("面板 URL 需要 http(s) 地址，不含凭据、查询和空白")
    if url.scheme == "http" and url.hostname not in ("127.0.0.1", "::1", "localhost"):
        raise ValueError("HTTP 面板必须使用回环地址；远程面板使用有效证书 HTTPS")
    if url.port is not None and not 1 <= url.port <= 65535:
        raise ValueError("面板端口不正确")
    return value.rstrip("/")


def panel_default(settings):
    port = int(settings.get("webPort") or "2053")
    base = settings.get("webBasePath") or "/"
    base = "/" + base.strip("/") if base.strip("/") else ""
    listen = settings.get("webListen") or ""
    if settings.get("webCertFile") or settings.get("webKeyFile") or listen not in ("", "0.0.0.0", "127.0.0.1", "::", "::1"):
        return None  # Never guess a certificate hostname or downgrade a TLS panel.
    host = "[::1]" if listen == "::1" else "127.0.0.1"
    return validate_url("http://{}:{}{}".format(host, port, base))


def merged_config(original, access_log, final_rules=True):
    result = copy.deepcopy(original)
    outbounds = result.get("outbounds")
    if not isinstance(outbounds, list) or not outbounds or not all(isinstance(o, dict) for o in outbounds):
        raise ValueError("原配置没有有效默认出站，停止自动合并")
    if outbounds[0].get("tag") in (QUERY, BLOCK):
        raise ValueError("查询 / 阻断出站不能成为默认出站")
    if not Path(access_log).is_absolute() or any(c in access_log for c in "\n\r\0"):
        raise ValueError("访问日志必须是绝对路径")
    query = {"tag": QUERY, "protocol": "freedom", "settings": {"redirect": "127.0.0.1:8686", "proxyProtocol": 2}}
    if final_rules:
        query["settings"]["finalRules"] = [{"action": "allow", "network": "tcp", "ip": ["127.0.0.1"], "port": "8686"}]
    block = {"tag": BLOCK, "protocol": "blackhole", "settings": {}}
    for desired in (query, block):
        matches = [o for o in outbounds if o.get("tag") == desired["tag"]]
        if len(matches) > 1:
            raise ValueError("出站标签重复，停止自动合并")
        if matches:
            existing = copy.deepcopy(matches[0])
            wanted = copy.deepcopy(desired)
            if desired["tag"] == QUERY:
                final = existing.get("settings", {}).pop("finalRules", None)
                allowed = [{"action": "allow", "network": "tcp", "ip": ["127.0.0.1"], "port": "8686"}]
                if final not in (None, allowed):
                    raise ValueError("已有查询出站含其他 finalRules，停止自动修改")
                wanted["settings"].pop("finalRules", None)
            if existing != wanted:
                raise ValueError("已有同名出站的配置不同，请先人工检查: " + desired["tag"])
            outbounds[outbounds.index(matches[0])] = desired
        else:
            outbounds.append(desired)
    if not isinstance(result.get("routing", {}), dict) or not isinstance(result.get("log", {}), dict):
        raise ValueError("routing / log 必须是对象")
    routing = result.setdefault("routing", {})
    rules = routing.setdefault("rules", [])
    if not isinstance(rules, list) or not all(isinstance(r, dict) for r in rules):
        raise ValueError("routing.rules 必须是数组")
    added = [
        {"type": "field", "network": "tcp", "ip": ["6.6.6.6/32"], "port": "80", "outboundTag": QUERY},
        {"type": "field", "network": "tcp,udp", "ip": ["6.6.6.6/32"], "outboundTag": BLOCK},
    ]
    for rule in rules:
        if rule.get("outboundTag") in (QUERY, BLOCK) and rule not in added:
            raise ValueError("已有查询路由与 HTTP 入口不同，请先人工检查")
    routing["rules"] = added + [r for r in rules if r not in added]
    log = result.setdefault("log", {})
    log["access"] = access_log
    log["maskAddress"] = ""
    return result


def configuration(base_url, access_log):
    quote = lambda s: json.dumps(s, ensure_ascii=False)
    return '''# Generated by flownote-setup; HTTP entry intercepted by Xray.
[server]
listen = "127.0.0.1:8686"
protocol = "http"
domain = "6.6.6.6"
[xray]
access_log = %s
outbound_tag = "traffic-query"
[panel]
base_url = %s
token_file = "/etc/flownote/token"
[display]
title = "流量笺"
tz_offset_hours = 8
[history]
enabled = true
directory = "/var/lib/flownote/history"
retention_days = 30
sample_interval_secs = 3600
''' % (quote(access_log), quote(validate_url(base_url)))


def write_private(path, data, group=0):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("拒绝覆盖符号链接: " + str(path))
    fd, temporary = tempfile.mkstemp(prefix=".flownote-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
            os.fchmod(file.fileno(), 0o640 if group else 0o600)
            os.fchown(file.fileno(), 0, group)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def snapshot_and_update(db, backup, expected, replacement):
    with connection(str(db), timeout=5) as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute("SELECT value FROM settings WHERE key=?", ("xrayTemplateConfig",)).fetchall()
        if rows != [(expected,)]:
            raise ValueError("Xray 设置在向导运行期间发生变化，未写入；请重新运行")
        # A second read-only connection snapshots the last committed state while the write lock is held.
        with connection(db.resolve().as_uri() + "?mode=ro", uri=True) as source:
            with connection(str(backup)) as dest:
                source.backup(dest)
        os.chmod(backup, 0o600)
        conn.execute("UPDATE settings SET value=? WHERE key=?", (replacement, "xrayTemplateConfig"))


def restore_setting(db, expected, original):
    with connection(str(db), timeout=5) as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute("SELECT value FROM settings WHERE key=?", ("xrayTemplateConfig",)).fetchall()
        if rows == [(original,)]:
            return
        if rows != [(expected,)]:
            raise ValueError("设置已被其他进程修改，未自动覆盖；请检查备份")
        conn.execute("UPDATE settings SET value=? WHERE key=?", (original, "xrayTemplateConfig"))


def ask(label, default=""):
    suffix = " [{}]".format(default) if default else ""
    answer = input(label + suffix + ": ").strip()
    return answer or default


def yes(label):
    return input(label + " [y/N]: ").strip().lower() in ("y", "yes")


def check_environment(base, db, core, proc_root=Path("/proc")):
    pid = command(["systemctl", "show", "x-ui", "--property=MainPID", "--value"]).stdout.strip()
    if not pid.isdigit() or int(pid) <= 0:
        raise ValueError("请先启动 x-ui 服务，再运行配置向导")
    proc = proc_root / pid
    if (proc / "exe").resolve() != (base / "x-ui").resolve():
        raise ValueError("运行中的面板目录不同，请用 --xui-dir 指定实际目录")
    if os.readlink(proc / "ns/net") != os.readlink(proc_root / "self/ns/net"):
        raise ValueError("面板与向导不在同一网络命名空间，暂不支持容器自动配置")
    env = {}
    for item in (proc / "environ").read_bytes().split(b"\0"):
        key, _, value = item.partition(b"=")
        if key in (b"XUI_DB_FOLDER", b"XUI_BIN_FOLDER", b"XUI_PORT", b"XUI_DB_TYPE"):
            env[key.decode()] = value.decode()
    if env.get("XUI_DB_TYPE", "sqlite").lower() not in ("", "sqlite", "sqlite3"):
        raise ValueError("自动向导仅支持本机 SQLite 面板，未修改数据库")
    db_dir = Path(env.get("XUI_DB_FOLDER") or "/etc/x-ui")
    if not db_dir.is_absolute():
        db_dir = (proc / "cwd").resolve() / db_dir
    if db != (db_dir / "x-ui.db").resolve():
        raise ValueError("服务数据库路径不同，请用 --db 指定实际数据库")
    bin_dir = Path(env.get("XUI_BIN_FOLDER") or "bin")
    if not bin_dir.is_absolute():
        bin_dir = (proc / "cwd").resolve() / bin_dir
    if core.parent != bin_dir.resolve():
        raise ValueError("运行中的 Xray 目录不同，请用 --core 指定实际内核路径")
    return env.get("XUI_PORT")


def discover(args):
    base = Path(args.xui_dir).resolve()
    db = Path(args.db).resolve()
    settings = read_settings(db)
    candidates = [p for p in (base / "bin").glob("xray*") if p.is_file() and os.access(p, os.X_OK) and p.name in ("xray", "xray-linux-amd64", "xray-linux-arm64", "xray-linux-64", "xray-linux-arm64-v8a")]
    core = Path(args.core).resolve() if args.core else (candidates[0].resolve() if len(candidates) == 1 else None)
    if core is None or not core.is_file() or not os.access(core, os.X_OK):
        raise ValueError("无法唯一识别 Xray 内核，请使用 --core 指定可执行文件")
    print("\n检测结果")
    print("  面板目录:", base)
    print("  数据库:  ", db)
    print("  Xray:    ", core)
    default = panel_default(settings)
    print("  面板地址:", default or "HTTPS / 自定义监听，需要输入实际地址")
    return base, db, core, settings, default


def test_xray(core, value, directory):
    candidate = directory / "xray-check.json"
    write_private(candidate, json.dumps(value, ensure_ascii=False))
    env = dict(os.environ, XRAY_LOCATION_ASSET=str(core.parent))
    try:
        command([str(core), "run", "-test", "-config", str(candidate)], cwd=str(core.parent), env=env)
    except subprocess.CalledProcessError:
        raise ValueError("Xray 配置检查失败；未改面板。请检查向导导出的配置，勿公开其中账号密钥") from None


def core_running(core):
    for entry in Path("/proc").glob("[0-9]*/exe"):
        try:
            if entry.resolve() == core:
                return True
        except OSError:
            pass
    return False


def wait_service(name, core=None):
    for _ in range(20):
        active = subprocess.run(["systemctl", "is-active", "--quiet", name], timeout=5).returncode == 0
        if active and (core is None or core_running(core)):
            time.sleep(1)
            if subprocess.run(["systemctl", "is-active", "--quiet", name], timeout=5).returncode == 0 and (core is None or core_running(core)):
                return
        time.sleep(.5)
    raise ValueError(name + " 未正常启动")


def grant_log(log, group, directory):
    path = Path(log)
    if path.is_symlink():
        raise ValueError("日志路径不能为符号链接")
    if path.parent == Path("/var/log/flownote-xray"):
        user = command(["systemctl", "show", "x-ui", "--property=User", "--value"]).stdout.strip() or "root"
        uid = pwd.getpwnam(user).pw_uid
        if path.parent.is_symlink():
            raise ValueError("日志目录不能为符号链接")
        path.parent.mkdir(mode=0o750, exist_ok=True)
        os.chown(path.parent, uid, group)
        os.chmod(path.parent, 0o750)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o640)
        os.close(fd)
        os.chown(path, uid, group)
        os.chmod(path, 0o640)
        rotate = Path("/etc/logrotate.d/flownote-xray")
        rotate.parent.mkdir(mode=0o755, exist_ok=True)
        if rotate.is_symlink():
            raise ValueError("日志轮转配置不能为符号链接")
        if rotate.exists():
            shutil.copy2(rotate, directory / "logrotate.before")
        write_private(rotate, str(path) + " {\n  su " + user + " flownote\n  daily\n  rotate 7\n  compress\n  delaycompress\n  missingok\n  notifempty\n  copytruncate\n}\n")
        os.chmod(rotate, 0o644)
        if not shutil.which("logrotate"):
            print("已写入日志轮转配置；系统未安装 logrotate，Debian / Ubuntu 请执行 sudo apt-get install -y logrotate。")
    else:
        if path.is_file() and subprocess.run(["runuser", "-u", "flownote", "--", "test", "-r", str(path)], timeout=5).returncode == 0:
            print("现有日志已可读；轮转后仍需保留读取权限。")
            return
        if not path.is_file() or not shutil.which("setfacl"):
            raise ValueError("现有日志需要存在且安装 acl 工具；或选择默认 /var/log/flownote-xray/access.log")
        for parent in reversed(path.parents):
            if parent != Path("/") and subprocess.run(["runuser", "-u", "flownote", "--", "test", "-x", str(parent)], timeout=5).returncode != 0:
                command(["setfacl", "-m", "u:flownote:--x", str(parent)])
        command(["setfacl", "-m", "u:flownote:r--", str(path)])
        print("现有日志已授予读取权限；请在其轮转配置中保留该文件 ACL。")
    command(["runuser", "-u", "flownote", "--", "test", "-r", str(path)])


def setup(args):
    base, db, core, settings, default = discover(args)
    port_override = check_environment(base, db, core)
    if port_override:
        settings["webPort"] = port_override
        default = panel_default(settings)
    original = settings.get("xrayTemplateConfig")
    if not original:
        raise ValueError("未找到持久化 Xray 模板。请在 3x-ui 的 Xray 设置页保存一次现有配置，再运行向导；不会把运行时 config.json 当作面板模板覆盖")
    template = load_json(original)
    runtime = load_json((core.parent / "config.json").read_text(encoding="utf-8"))
    base_url = validate_url(ask("面板 API 地址（包含面板访问路径）", default or ""))
    access = template.get("log", {}).get("access", "")
    access = access if access not in ("", "none", "stdout") and Path(access).is_absolute() else "/var/log/flownote-xray/access.log"
    access = ask("Xray access log", access)
    if Path(access) in (Path("/root"), Path("/home")) or any(p in Path(access).parents for p in (Path("/root"), Path("/home"))):
        raise ValueError("systemd ProtectHome 会阻止读取此日志，请使用 /var/log/flownote-xray/access.log")
    group = grp.getgrnam("flownote").gr_gid
    token_path = Path("/etc/flownote/token")
    token = getpass.getpass("面板 API Token（不回显；留空保留已有 Token）: ").strip()
    if not token and (not token_path.is_file() or token_path.is_symlink()):
        raise ValueError("首次配置需要 API Token；请在面板创建后粘贴，不是登录密码或订阅链接")
    if any(c in token for c in "\r\n\0"):
        raise ValueError("Token 不能含换行或 NUL")
    email = ask("填写一个真实 client email，用于验证面板权限")
    if not email:
        raise ValueError("需要真实 client email 才能验证接口兼容和权限")
    final_rules = True
    merged = merged_config(template, access, final_rules)
    run_merged = merged_config(runtime, access, final_rules)
    root = Path("/var/backups/flownote")
    if root.is_symlink():
        raise ValueError("备份目录不能为符号链接")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chown(root, 0, 0)
    os.chmod(root, 0o700)
    directory = Path(tempfile.mkdtemp(prefix=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ-"), dir=str(root)))
    write_private(directory / "xray-template.after.json", json.dumps(merged, ensure_ascii=False, indent=2))
    try:
        test_xray(core, run_merged, directory)
    except ValueError:
        if not yes("内核不接受新配置。去除新版 finalRules 后重新检查？"):
            raise
        merged = merged_config(template, access, False)
        test_xray(core, merged_config(runtime, access, False), directory)
        write_private(directory / "xray-template.after.json", json.dumps(merged, ensure_ascii=False, indent=2))
    config = configuration(base_url, access)
    write_private(directory / "config.after.toml", config)
    print("\n将保存 HTTP 配置、Token 和日志权限；追加两个出站及两条精确 IP 路由。")
    print("原默认出站、节点、订阅开关与面板登录设置保留。")
    print("访问日志保留完整来源 IP:端口，用于账号关联；不做地址掩码。")
    print("将使用向导生成的 HTTP / 历史采样配置；已有 FlowNote 自定义配置先备份。")
    print("会短暂停止 / 启动 x-ui（节点连接可能断开），并启动 FlowNote。")
    print("变更预览 / 备份目录:", directory)
    print("如使用现有日志，只对该日志授予 ACL；日志轮转仍需保持权限。")
    if not yes("确认应用以上变更？"):
        print("已取消，面板和服务未修改。预览文件已保留。")
        return
    apply_changes(db, directory, original, json.dumps(merged, ensure_ascii=False),
                  Path("/etc/flownote/config.toml"), config, token_path, token,
                  group, access, email, core)
    print("\n服务已启动。还需在客户端加规则，并完成双账号查询验收：")
    client_rules()


def apply_changes(db, directory, original, replacement, config_path, config,
                  token_path, token, group, access, email, core):
    for path in (config_path, token_path):
        if path.is_symlink():
            raise ValueError("拒绝替换符号链接配置 / Token")
        if path.exists():
            shutil.copy2(path, directory / (path.name + ".before"))
            os.chmod(directory / (path.name + ".before"), 0o600)
    stopped = updated = False
    was_active = subprocess.run(["systemctl", "is-active", "--quiet", "flownote"], timeout=5).returncode == 0
    try:
        # Validate panel before touching the running x-ui service.
        if token:
            write_private(token_path, token + "\n", group)
        write_private(config_path, config, group)
        command(["runuser", "-u", "flownote", "--", "/usr/local/bin/flownote", str(config_path), "--check-panel", email])
        grant_log(access, group, directory)
        stopped = True
        command(["systemctl", "stop", "x-ui"])
        updated = True
        snapshot_and_update(db, directory / "x-ui.before.db", original, replacement)
        command(["systemctl", "start", "x-ui"])
        wait_service("x-ui", core)
        command(["systemctl", "restart", "flownote"])
        wait_service("flownote")
        command(["systemctl", "enable", "flownote"])
    except BaseException:
        try:
            if updated:
                command(["systemctl", "stop", "x-ui"])
                restore_setting(db, replacement, original)
            if stopped:
                command(["systemctl", "start", "x-ui"])
            for path in (config_path, token_path):
                previous = directory / (path.name + ".before")
                if previous.exists():
                    write_private(path, previous.read_text(encoding="utf-8"), group)
                elif path.exists():
                    path.unlink()
            command(["systemctl", "restart" if was_active else "stop", "flownote"])
        except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError):
            print("自动回退未全部成功，请检查 x-ui / flownote 日志与备份。", file=sys.stderr)
        raise ValueError("应用失败，已尝试恢复原 Xray 设置和 FlowNote 配置；日志文件 / ACL / 轮转配置可能保留。备份: " + str(directory)) from None


def client_rules():
    print("\nClash / Mihomo rules 最前面添加（替换策略名）：")
    print("  - IP-CIDR,6.6.6.6/32,你的节点或策略组,no-resolve")
    print("选择自己的账号节点，打开系统代理 / TUN，关闭该场景的 Mux。")
    print("浏览器打开 http://6.6.6.6/（使用 HTTP，不自动升级 HTTPS）。")
    print("不同账号、同 NAT 并发和重连仍须实际验收；服务启动不代表身份链路已验证。")


def main():
    parser = argparse.ArgumentParser(description="FlowNote 本机 3x-ui 交互式配置")
    parser.add_argument("--db", default="/etc/x-ui/x-ui.db")
    parser.add_argument("--xui-dir", default="/usr/local/x-ui")
    parser.add_argument("--core", help="自定义 Xray 内核路径")
    parser.add_argument("--detect", action="store_true", help="只读探测，不修改配置")
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() != 0:
        parser.error("请在安装 3x-ui 的 Linux 服务器上运行 sudo flownote-setup")
    if args.detect:
        discover(args)
        return
    if not sys.stdin.isatty():
        parser.error("需要交互终端；请下载脚本后运行，不要把输入管道当成终端")
    while True:
        print("\n流量笺 · FlowNote\n  1. 检测 3x-ui 安装\n  2. 配置 HTTP 查询入口\n  3. 查看服务状态与日志\n  4. 显示客户端分流规则\n  0. 退出")
        choice = ask("选择", "0")
        try:
            if choice == "0":
                return
            if choice == "1":
                discover(args)
            elif choice == "2":
                setup(args)
            elif choice == "3":
                subprocess.run(["systemctl", "status", "flownote", "--no-pager"], timeout=15)
                subprocess.run(["journalctl", "-u", "flownote", "-n", "30", "--no-pager"], timeout=15)
            elif choice == "4":
                client_rules()
        except (ValueError, KeyError) as exc:
            print("操作未完成: " + str(exc), file=sys.stderr)
        except (OSError, sqlite3.Error, subprocess.SubprocessError):
            print("操作未完成。请检查文件权限、Python 依赖和服务日志。面板检查失败时请核对 Token / URL / client email；不跳过证书验证。", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n已退出。")
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
