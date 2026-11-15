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
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

KEYS = ("webPort", "webListen", "webBasePath", "webCertFile", "webKeyFile", "webDomain", "xrayTemplateConfig")
BACKUP_ROOT = Path("/var/backups/flownote")
QUERY = "traffic-query"
BLOCK = "flownote-block"
CONFIG_PATH = Path("/etc/flownote/config.toml")
TOKEN_PATH = Path("/etc/flownote/token")


def command(args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, timeout=kwargs.pop("timeout", 30), **kwargs)


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


def certificate_host(path):
    if not path or not Path(path).is_file() or not shutil.which("openssl"):
        return None
    try:
        output = command(["openssl", "x509", "-in", str(path), "-noout", "-ext", "subjectAltName"]).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    hosts = set(re.findall(r"DNS:([a-zA-Z0-9.-]+)(?=,|\s|$)", output))
    return next(iter(hosts)) if len(hosts) == 1 else None


def panel_default(settings):
    port = int(settings.get("webPort") or "2053")
    base = settings.get("webBasePath") or "/"
    base = "/" + base.strip("/") if base.strip("/") else ""
    listen = settings.get("webListen") or ""
    if settings.get("webCertFile") or settings.get("webKeyFile"):
        host = (settings.get("webDomain") or "").strip() or certificate_host(settings.get("webCertFile"))
        if not host or not re.fullmatch(r"[a-zA-Z0-9.-]+", host):
            return None
        return validate_url("https://{}:{}{}".format(host, port, base))
    if listen not in ("", "0.0.0.0", "127.0.0.1", "::", "::1"):
        return None
    host = "[::1]" if listen == "::1" else "127.0.0.1"
    return validate_url("http://{}:{}{}".format(host, port, base))


def config_field(text, section, key):
    # Read only the strings we own; preserve all other TOML verbatim. No new dependency.
    header = re.compile(r"^\s*\[([^]\n]+)\]\s*(?:#.*)?$")
    current = None
    found = []
    for line in text.splitlines():
        match = header.match(line)
        if match:
            current = match[1]
        elif current == section:
            match = re.match(r"^\s*" + re.escape(key) + r"\s*=\s*(.*)$", line)
            if match:
                value = re.match(r"(\"(?:[^\"\\]|\\.)*\"|'[^']*')\s*(?:#.*)?$", match[1])
                if not value:
                    raise ValueError("无法自动读取 [" + section + "] " + key + "，请检查配置字符串")
                quoted = value[1]
                found.append(json.loads(quoted) if quoted.startswith('"') else quoted[1:-1])
    if len(found) > 1:
        raise ValueError("配置项重复: [" + section + "] " + key)
    return found[0] if found else None


def set_config_field(text, section, key, value):
    # Validate uniqueness and supported scalar syntax before changing anything.
    current = config_field(text, section, key)
    if current == value:
        return text
    lines = text.splitlines(keepends=True)
    inside = False
    for index, line in enumerate(lines):
        header = re.match(r"^\s*\[([^]\n]+)\]\s*(?:#.*)?$", line.strip())
        if header:
            if inside:
                lines.insert(index, key + " = " + json.dumps(value, ensure_ascii=False) + "\n")
                return "".join(lines)
            inside = header[1] == section
        elif inside and re.match(r"^\s*" + re.escape(key) + r"\s*=", line):
            lines[index] = key + " = " + json.dumps(value, ensure_ascii=False) + "\n"
            return "".join(lines)
    prefix = "".join(lines).rstrip("\n") + "\n"
    return prefix + ("" if inside else "[" + section + "]\n") + key + " = " + json.dumps(value, ensure_ascii=False) + "\n"


def setup_configuration(existing, base_url, access):
    if not existing:
        return configuration(base_url, access)
    protocol = config_field(existing, "server", "protocol")
    domain = config_field(existing, "server", "domain")
    if protocol != "http" or domain != "6.6.6.6":
        raise ValueError("当前不是 6.6.6.6 HTTP 查询配置；请保留现有入口并按手动指南调整")
    if (config_field(existing, "server", "listen") != "127.0.0.1:8686"
            or config_field(existing, "xray", "outbound_tag") != QUERY):
        raise ValueError("当前监听地址 / 出站标签为自定义值，请按手动指南调整")
    result = set_config_field(existing, "panel", "base_url", base_url)
    return set_config_field(result, "xray", "access_log", access)


def query_ready(value, access, final_rules):
    verified = merged_config(value, access, final_rules)
    api_rule = {"type": "field", "inboundTag": ["api"], "outboundTag": "api"}
    rules = [rule for rule in value.get("routing", {}).get("rules", []) if rule != api_rule]
    # Compare only owned settings. The panel can inject a management API rule.
    return (value["outbounds"] == verified["outbounds"] and value.get("log") == verified["log"]
            and rules[:2] == verified["routing"]["rules"][:2])


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
enabled = false
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


class XrayCheckError(ValueError):
    def __init__(self, message, final_rules_unsupported=False):
        super().__init__(message)
        self.final_rules_unsupported = final_rules_unsupported


def test_xray(core, value, directory, *, stage_access_log=False):
    # Xray -test initializes loggers, including files whose parent may not exist yet.
    # Validate with a private access log until the user confirms applying changes.
    checked = copy.deepcopy(value)
    if stage_access_log:
        access = directory / "xray-preflight-access.log"
        write_private(access, "")
        checked.setdefault("log", {})["access"] = str(access)
    candidate = directory / "xray-check.json"
    write_private(candidate, json.dumps(checked, ensure_ascii=False))
    env = dict(os.environ, XRAY_LOCATION_ASSET=str(core.parent))
    try:
        command([str(core), "run", "-test", "-config", str(candidate)], cwd=str(core.parent), env=env)
    except subprocess.CalledProcessError as exc:
        stdout, stderr = exc.stdout or "", exc.stderr or ""
        write_private(directory / "xray-check.stdout.log", stdout)
        write_private(directory / "xray-check.stderr.log", stderr)
        detail = (stdout + "\n" + stderr).lower()
        unsupported = bool(re.search(
            r"(?:unknown|unrecognized|unsupported|invalid) (?:json )?field\s*[:=]?\s*\W?finalrules\b"
            r"|finalrules[^\n]{0,80}(?:unknown|unrecognized|unsupported|not supported)", detail))
        reason = ""
        if unsupported:
            reason = "当前内核不识别 finalRules 字段。"
        elif "failed to initialize access logger" in detail:
            reason = "访问日志无法打开，请检查日志目录是否存在及权限。"
        elif "failed to initialize error logger" in detail:
            reason = "Xray 错误日志无法打开，请检查原错误日志路径及权限。"
        elif ("geosite" in detail or "geoip" in detail) and any(
                term in detail for term in ("no such file", "failed to open", "not found")):
            reason = "GeoIP / GeoSite 资源文件缺失，请检查内核资源目录。"
        raise XrayCheckError(
            "Xray 配置检查失败（退出码 {}）；未改面板。{}原始错误已保存：{} 和 {}；"
            "请在服务器本机查看，勿公开其中账号密钥。".format(
                exc.returncode, reason, directory / "xray-check.stdout.log", directory / "xray-check.stderr.log"),
            final_rules_unsupported=unsupported) from None


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


def access_path(value):
    if value in (None, "", "none", "stdout"):
        return None
    if not isinstance(value, str) or not Path(value).is_absolute() or any(c in value for c in "\n\r\0"):
        raise ValueError("Xray 访问日志必须使用绝对路径；请先在面板日志设置中调整")
    path = Path(value).resolve()
    if any(p == path or p in path.parents for p in (Path("/root"), Path("/home"))):
        raise ValueError("日志不能放在 /root 或 /home；请在面板设置 /var/log 下的路径")
    return value


def choose_access(runtime, template):
    # The panel may override the stored template when generating config.json.
    return (access_path(runtime.get("log", {}).get("access"))
            or access_path(template.get("log", {}).get("access"))
            or "/var/log/flownote-xray/access.log")


def client_identifier(runtime, db):
    for inbound in runtime.get("inbounds", []):
        for client in inbound.get("settings", {}).get("clients", []):
            email = client.get("email")
            if isinstance(email, str) and email and not any(c.isspace() or ord(c) < 32 for c in email):
                return email
    try:
        with connection(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as conn:
            row = conn.execute("SELECT email FROM client_traffics WHERE email IS NOT NULL AND email != '' ORDER BY email LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        return None  # Older / empty panels fall back to the explicit prompt.
    if row and isinstance(row[0], str) and not any(c.isspace() or ord(c) < 32 for c in row[0]):
        return row[0]
    return None


def missing_tools(access):
    packages = []
    if not shutil.which("logrotate"):
        packages.append("logrotate")
    if Path(access).parent != Path("/var/log/flownote-xray") and not shutil.which("setfacl"):
        packages.append("acl")
    return packages


def ensure_tools(access):
    packages = missing_tools(access)
    if not packages:
        return
    print("安装配置依赖: " + ", ".join(packages))
    if shutil.which("apt-get"):
        command(["apt-get", "update"], timeout=180)
        command(["apt-get", "install", "-y", *packages], timeout=180,
                env=dict(os.environ, DEBIAN_FRONTEND="noninteractive"))
    elif shutil.which("dnf"):
        command(["dnf", "install", "-y", *packages], timeout=180)
    elif shutil.which("apk"):
        command(["apk", "add", "--no-cache", *packages], timeout=180)
    else:
        raise ValueError("请先用系统包管理器安装: " + " ".join(packages))
    if missing_tools(access):
        raise ValueError("依赖安装后仍找不到工具，请检查系统 PATH: " + " ".join(missing_tools(access)))


def reconcile_log(core, config_path, config, group, directory, expected):
    actual = load_json((core.parent / "config.json").read_text(encoding="utf-8"))
    access = access_path(actual.get("log", {}).get("access"))
    if not access:
        raise ValueError("面板重新生成的 Xray 配置未启用文件访问日志")
    query = next(o for o in expected["outbounds"] if o.get("tag") == QUERY)
    final_rules = "finalRules" in query["settings"]
    if not query_ready(actual, access, final_rules):
        raise ValueError("面板未保留查询路由、出站或完整来源地址，停止启动 FlowNote")
    before = access_path(expected.get("log", {}).get("access"))
    if access != before:
        # Reuse the effective panel log, rather than starting another logger or service.
        ensure_tools(access)
        grant_log(access, group, directory)
        config = set_config_field(config, "xray", "access_log", access)
        write_private(config_path, config, group)
        write_private(directory / "config.after.toml", config)
        print("已同步面板实际访问日志: " + access)
    command(["runuser", "-u", "flownote", "--", "test", "-r", access])


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
    advanced = getattr(args, "advanced", False)
    if CONFIG_PATH.is_symlink():
        raise ValueError("配置文件不能为符号链接")
    existing = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.is_file() else ""
    if not default and existing:
        saved_url = config_field(existing, "panel", "base_url")
        if saved_url and (not settings.get("webCertFile") and not settings.get("webKeyFile")
                          or urlsplit(saved_url).scheme == "https"):
            default = validate_url(saved_url)
    base_url = validate_url(ask("面板 API 地址（包含面板访问路径）", default or "")
                            if advanced or not default else default)
    access = choose_access(runtime, template)
    if advanced:
        access = access_path(ask("Xray 访问日志路径", access))
        if not access:
            raise ValueError("必须启用文件访问日志")
    print("面板地址: " + base_url)
    print("自动使用 Xray 访问日志: " + access)
    group = grp.getgrnam("flownote").gr_gid
    token_path = Path(config_field(existing, "panel", "token_file") or TOKEN_PATH)
    if not token_path.is_absolute() or token_path.is_symlink():
        raise ValueError("Token 文件必须为绝对路径且不能是符号链接")
    inline_token = config_field(existing, "panel", "token")
    if not advanced and (token_path.is_file() or inline_token):
        token = ""
        print("复用已保存的 API Token。")
    else:
        token = getpass.getpass("面板 API Token（不回显；留空保留已有 Token）: ").strip()
    if not token and not inline_token and (not token_path.is_file() or token_path.is_symlink()):
        raise ValueError("首次配置需要 API Token；请在面板创建后粘贴，不是登录密码或订阅链接")
    if any(c in token for c in "\r\n\0"):
        raise ValueError("Token 不能含换行或 NUL")
    email = client_identifier(runtime, db)
    if advanced or not email:
        email = ask("3x-ui 已有客户端的 email 标识（无需真实邮箱）", email or "")
    else:
        print("已自动选择已有客户端用于验证流量 API。")
    if not email:
        raise ValueError("请填写面板里一个已有客户端的 email 标识，用于验证流量 API；不是面板登录账号")
    previous_query = next((o for o in runtime.get("outbounds", []) if o.get("tag") == QUERY), None)
    final_rules = previous_query is None or "finalRules" in previous_query.get("settings", {})
    merged = merged_config(template, access, final_rules)
    run_merged = merged_config(runtime, access, final_rules)
    # An unchanged deployment needs neither a kernel check nor a service reload.
    restart_xui = not query_ready(runtime, access, final_rules)
    config = setup_configuration(existing, base_url, access)
    if token:
        config = set_config_field(config, "panel", "token_file", str(token_path))
        if inline_token:
            config = set_config_field(config, "panel", "token", "")
    root = BACKUP_ROOT
    if root.is_symlink():
        raise ValueError("备份目录不能为符号链接")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chown(root, 0, 0)
    os.chmod(root, 0o700)
    directory = Path(tempfile.mkdtemp(prefix=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ-"), dir=str(root)))
    write_private(directory / "xray-template.after.json", json.dumps(merged, ensure_ascii=False, indent=2))
    try:
        if restart_xui:
            test_xray(core, run_merged, directory, stage_access_log=True)
    except XrayCheckError as exc:
        if not exc.final_rules_unsupported:
            raise
        print(str(exc), file=sys.stderr)
        if not yes("内核不识别 finalRules。去除此字段后重新检查？"):
            raise
        merged = merged_config(template, access, False)
        run_merged = merged_config(runtime, access, False)
        test_xray(core, run_merged, directory, stage_access_log=True)
        write_private(directory / "xray-template.after.json", json.dumps(merged, ensure_ascii=False, indent=2))
    write_private(directory / "config.after.toml", config)
    print("\n将保存 HTTP 配置、Token 和日志权限；追加两个出站及两条精确 IP 路由。")
    print("原默认出站、节点、订阅开关与面板登录设置保留。")
    print("访问日志保留完整来源 IP:端口，用于账号关联；不做地址掩码。")
    print("保留已有显示、历史和性能设置；新配置默认关闭历史曲线。")
    print("需要首次加载 / 修复 Xray 路由，将短暂重启 x-ui（节点可能断开）。" if restart_xui
          else "Xray 查询路由已就绪；本次不重启 3x-ui / Xray。")
    print("变更预览 / 备份目录:", directory)
    print("如使用现有日志，只对该日志授予 ACL；日志轮转仍需保持权限。")
    packages = missing_tools(access)
    if packages:
        print("确认后自动补齐配置依赖: " + ", ".join(packages))
    if not yes("确认应用以上变更？"):
        print("已取消，面板和服务未修改。预览文件已保留。")
        return
    apply_changes(db, directory, original, json.dumps(merged, ensure_ascii=False),
                  CONFIG_PATH, config, token_path, token,
                  group, access, email, core, run_merged, restart_xui=restart_xui)
    print("\n服务已启动。还需在客户端加规则，并完成双账号查询验收：")
    client_rules()


def apply_changes(db, directory, original, replacement, config_path, config,
                  token_path, token, group, access, email, core, runtime_config, *, restart_xui=True):
    for path in (config_path, token_path):
        if path.is_symlink():
            raise ValueError("拒绝替换符号链接配置 / Token")
        if path.exists():
            shutil.copy2(path, directory / (path.name + ".before"))
            os.chmod(directory / (path.name + ".before"), 0o600)
    updated = reloaded = files_changed = flow_reloaded = False
    previous_config = config_path.read_text(encoding="utf-8") if config_path.is_file() else None
    config_changed = previous_config != config
    token_changed = bool(token) and (not token_path.is_file() or token_path.read_text(encoding="utf-8").strip() != token)
    template_changed = load_json(original) != load_json(replacement)
    was_active = subprocess.run(["systemctl", "is-active", "--quiet", "flownote"], timeout=5).returncode == 0
    stage = "验证面板 URL / Token / 流量接口"
    try:
        # Verify in root-private staging files; do not replace working configuration.
        probe = directory / "panel-check.toml"
        probe_token = directory / "panel-check.token"
        staged = config
        if token:
            write_private(probe_token, token + "\n")
            staged = set_config_field(staged, "panel", "token_file", str(probe_token))
        write_private(probe, staged)
        try:
            command(["/usr/local/bin/flownote", str(probe), "--check-panel", email])
        finally:
            if probe_token.exists():
                probe_token.unlink()
        stage = "准备日志工具与读取权限"
        ensure_tools(access)
        grant_log(access, group, directory)
        if restart_xui:
            stage = "检查 Xray 正式候选配置"
            test_xray(core, runtime_config, directory)
        else:
            stage = "核对运行中的查询路由"
            actual = load_json((core.parent / "config.json").read_text(encoding="utf-8"))
            query = next(o for o in runtime_config["outbounds"] if o.get("tag") == QUERY)
            if not query_ready(actual, access, "finalRules" in query["settings"]):
                raise ValueError("运行配置已改变，请重新运行向导")
        stage = "保存面板查询模板"
        if template_changed:
            snapshot_and_update(db, directory / "x-ui.before.db", original, replacement)
            updated = True
        elif read_settings(db).get("xrayTemplateConfig") != original:
            raise ValueError("面板模板已被其他操作修改，请重新运行向导")
        if restart_xui:
            stage = "重新加载 x-ui / Xray"
            reloaded = True
            # A single restart replaces the old stop/write/start window.
            command(["systemctl", "restart", "x-ui"])
            wait_service("x-ui", core)
        stage = "保存 FlowNote 配置"
        if config_changed or token_changed:
            files_changed = True
            if token_changed:
                write_private(token_path, token + "\n", group)
            if config_changed:
                write_private(config_path, config, group)
        stage = "核对面板实际日志与查询路由"
        files_changed = True  # Reconciliation may update the effective log path.
        reconcile_log(core, config_path, config, group, directory, runtime_config)
        command(["runuser", "-u", "flownote", "--", "test", "-r", str(config_path)])
        if config_field(config, "panel", "token_file"):
            command(["runuser", "-u", "flownote", "--", "test", "-r", str(token_path)])
        effective_changed = config_path.read_text(encoding="utf-8") != previous_config
        if config_changed or token_changed or effective_changed or not was_active:
            stage = "启动 FlowNote"
            flow_reloaded = True
            command(["systemctl", "restart" if was_active else "start", "flownote"])
            wait_service("flownote")
        else:
            print("FlowNote 配置一致，保持运行。")
        stage = "启用 FlowNote 开机启动"
        command(["systemctl", "enable", "flownote"])
    except BaseException as exc:
        # Keep diagnostics private, while always attempting service recovery even if
        # restoring a concurrently edited template fails.
        try:
            for name in ("stdout", "stderr"):
                text = getattr(exc, name, "") or ""
                if isinstance(text, bytes):
                    text = text.decode("utf-8", errors="replace")
                write_private(directory / ("apply." + name + ".log"), text)
            write_private(directory / "apply.failure.json", json.dumps({
                "stage": stage, "error_type": type(exc).__name__, "detail": str(exc),
                "returncode": getattr(exc, "returncode", None)}, ensure_ascii=False))
        except (OSError, ValueError):
            pass  # A diagnostic write failure must never prevent recovery.
        recovery = []
        if updated:
            try:
                restore_setting(db, replacement, original)
            except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError):
                recovery.append("面板模板恢复失败，未覆盖其他修改")
        if reloaded:
            try:
                command(["systemctl", "restart", "x-ui"])
                wait_service("x-ui", core)
            except (OSError, ValueError, subprocess.SubprocessError):
                recovery.append("x-ui 恢复启动失败，请执行 systemctl status x-ui")
        if files_changed:
            try:
                for path in (config_path, token_path):
                    previous = directory / (path.name + ".before")
                    if previous.exists():
                        write_private(path, previous.read_text(encoding="utf-8"), group)
                    elif path.exists():
                        path.unlink()
            except (OSError, ValueError):
                recovery.append("FlowNote 配置恢复失败")
        if flow_reloaded:
            try:
                command(["systemctl", "restart" if was_active else "stop", "flownote"])
            except (OSError, subprocess.SubprocessError):
                recovery.append("FlowNote 服务恢复失败")
        detail = "；".join(recovery) if recovery else "未修改的服务保持运行；已修改的配置已执行回退"
        raise ValueError("应用失败（阶段：" + stage + "）。" + detail + "。诊断目录: " + str(directory)
                         + "；查看 apply.failure.json / apply.stderr.log，勿公开 Token 或节点密钥。日志权限和已安装系统包可能保留。") from None


# Uninstall operations stay in the same stdlib script so the menu can remove itself.
APP_FILES = tuple(Path(p) for p in (
    "/usr/local/bin/flownote", "/usr/local/bin/flownote.previous", "/usr/local/bin/flownote.new",
    "/usr/local/bin/flownote-setup", "/etc/systemd/system/flownote.service",
    "/etc/systemd/system/flownote.service.d",
    "/usr/local/share/flownote"))
DATA_PATHS = tuple(Path(p) for p in ("/etc/flownote", "/var/lib/flownote", "/var/backups/flownote"))
LOG_PATHS = (Path("/var/log/flownote-xray"), Path("/etc/logrotate.d/flownote-xray"))


def unmerged_config(original, before=None, after=None):
    result = copy.deepcopy(original)
    outbounds = result.get("outbounds", [])
    routing = result.get("routing", {})
    if not isinstance(outbounds, list) or not isinstance(routing, dict):
        raise ValueError("Xray 配置结构异常，停止自动卸载")
    rules = routing.get("rules", [])
    if not isinstance(rules, list) or not all(isinstance(x, dict) for x in outbounds + rules):
        raise ValueError("Xray 出站 / 路由结构异常，停止自动卸载")
    reference = merged_config({"outbounds": [{"tag": "direct", "protocol": "freedom"}]}, "/var/log/access.log")
    expected = reference["outbounds"][1:]
    for wanted in expected:
        found = [o for o in outbounds if o.get("tag") == wanted["tag"]]
        if len(found) > 1:
            raise ValueError("查询出站标签重复，请先人工检查")
        for outbound in found:
            candidate = copy.deepcopy(outbound)
            if wanted["tag"] == QUERY:
                final = candidate.get("settings", {}).pop("finalRules", None)
                if final not in (None, wanted["settings"]["finalRules"]):
                    raise ValueError("查询出站 finalRules 已自定义，停止自动卸载")
                wanted["settings"].pop("finalRules")
            if candidate != wanted or outbounds.index(outbound) == 0:
                raise ValueError("查询出站已自定义或成为默认出站，停止自动卸载")
    owned_rules = reference["routing"]["rules"]
    if any(r.get("outboundTag") in (QUERY, BLOCK) and r not in owned_rules for r in rules):
        raise ValueError("查询路由已自定义，请先人工移除相关出站引用")
    result["outbounds"] = [o for o in outbounds if o.get("tag") not in (QUERY, BLOCK)]
    if not result["outbounds"]:
        raise ValueError("卸载会清空默认出站，停止操作")
    if "rules" in routing:
        result["routing"]["rules"] = [r for r in rules if r not in owned_rules]
    removed_tags = [o["tag"] for o in outbounds if o.get("tag") in (QUERY, BLOCK)]
    for balancer in routing.get("balancers", []):
        if any(tag.startswith(prefix) for prefix in balancer.get("selector", [])
               for tag in removed_tags if isinstance(prefix, str)):
            raise ValueError("负载均衡 selector 仍匹配查询出站，停止自动卸载")
    def references(value):
        if isinstance(value, dict):
            return any(references(v) for v in value.values())
        if isinstance(value, list):
            return any(references(v) for v in value)
        return isinstance(value, str) and value in (QUERY, BLOCK)
    if references(result):
        raise ValueError("其他配置仍引用查询标签，请先人工检查")
    # Restore only the two log keys changed by setup, only if they still match its output.
    if before is not None and after is not None:
        old_log, installed_log = before.get("log", {}), after.get("log", {})
        log = result.get("log", {})
        if not all(isinstance(x, dict) for x in (old_log, installed_log, log)):
            raise ValueError("日志设置结构异常")
        for key in ("access", "maskAddress"):
            if key in installed_log and log.get(key) == installed_log[key]:
                if key in old_log:
                    log[key] = old_log[key]
                else:
                    log.pop(key, None)
    return result


def original_log_settings(root):
    if root.is_symlink():
        raise ValueError("备份目录不能为符号链接")
    # Look back through repeat setups for the first template without our tags.
    for directory in sorted(root.glob("*"), reverse=True):
        if directory.is_symlink() or not directory.is_dir():
            continue
        db, after = directory / "x-ui.before.db", directory / "xray-template.after.json"
        if db.is_symlink() or after.is_symlink() or not db.is_file() or not after.is_file():
            continue
        try:
            before = load_json(read_settings(db)["xrayTemplateConfig"])
            if any(o.get("tag") in (QUERY, BLOCK) for o in before.get("outbounds", [])):
                continue
            installed = load_json(after.read_text(encoding="utf-8"))
            # Require an actual wizard-shaped template rather than an arbitrary saved file.
            unmerged_config(installed)
            if not any(o.get("tag") == QUERY for o in installed.get("outbounds", [])):
                continue
            return before, installed
        except (OSError, ValueError, KeyError, AttributeError, sqlite3.Error):
            continue
    return None, None


def checked_removal(path, allowed):
    path = Path(path)
    if path not in allowed or not path.is_absolute() or path.resolve() != path:
        raise ValueError("拒绝清理非固定路径或符号链接: " + str(path))
    if path.is_dir():
        for directory, dirs, _ in os.walk(path, followlinks=False):
            if os.path.ismount(directory) or any(os.path.ismount(Path(directory) / d) for d in dirs):
                raise ValueError("清理目录包含挂载点，停止操作: " + str(path))
    return path


def remove_owned(path, allowed):
    path = checked_removal(path, allowed)
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def uninstall_xray(db, original, replacement, directory, core):
    stopped = updated = False
    try:
        stopped = True
        command(["systemctl", "stop", "x-ui"])
        updated = True
        snapshot_and_update(db, directory / "x-ui.before.db", original, replacement)
        command(["systemctl", "start", "x-ui"])
        wait_service("x-ui", core)
    except BaseException:
        rollback_failed = False
        if updated:
            try:
                command(["systemctl", "stop", "x-ui"])
                restore_setting(db, replacement, original)
            except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError):
                rollback_failed = True
        if stopped:
            try:
                command(["systemctl", "start", "x-ui"])
                wait_service("x-ui", core)
            except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError):
                rollback_failed = True
        if rollback_failed:
            print("Xray 自动回退未全部成功，请检查 x-ui 服务与备份。", file=sys.stderr)
        raise ValueError("查询配置清理失败，已尝试恢复模板；尚未删除 FlowNote 文件。备份: " + str(directory)) from None


def remove_service_account():
    try:
        account = pwd.getpwnam("flownote")
    except KeyError:
        return
    if account.pw_uid == 0 or account.pw_dir != "/var/lib/flownote" or account.pw_shell not in ("/usr/sbin/nologin", "/sbin/nologin"):
        print("flownote 账号不是标准服务账号，已保留，请人工检查。")
        return
    command(["userdel", "flownote"])  # Never use --remove: only fixed paths above may be deleted.
    try:
        group = grp.getgrnam("flownote")
    except KeyError:
        return
    if group.gr_gid != 0 and not group.gr_mem:
        command(["groupdel", "flownote"])


def uninstall(args):
    print("\n卸载与清理\n  1. 卸载程序，保留配置、Token、历史数据和备份\n  2. 完全清理（同时删除上述数据及可安全移除的专用日志）\n  0. 返回")
    mode = ask("选择", "0")
    if mode not in ("1", "2"):
        return False
    purge = mode == "2"
    db = Path(args.db).resolve()
    original = replacement = core = cleaned = None
    panel_active = subprocess.run(["systemctl", "is-active", "--quiet", "x-ui"], timeout=5).returncode == 0
    if db.is_file():
        settings = read_settings(db)
        original = settings.get("xrayTemplateConfig")
        if panel_active or original:
            base, _, core, _, _ = discover(args)
            if panel_active:
                check_environment(base, db, core)
        if original:
            template = load_json(original)
            before, after = original_log_settings(BACKUP_ROOT)
            cleaned = unmerged_config(template, before, after)
            if cleaned != template:
                if not panel_active:
                    raise ValueError("请先启动 x-ui，核对运行环境后再清理查询配置")
                replacement = json.dumps(cleaned, ensure_ascii=False)
        elif panel_active:
            # Fresh panel installs may never have persisted their template. Inspect but never persist runtime output.
            cleaned = load_json((core.parent / "config.json").read_text(encoding="utf-8"))
            if unmerged_config(cleaned) != cleaned:
                raise ValueError("仅发现运行时查询配置，请先在面板保存持久化模板后再卸载")
        else:
            raise ValueError("面板没有持久化模板且未运行，无法核对查询配置；请启动 x-ui 后重试")
    elif panel_active:
        raise ValueError("x-ui 正在运行但未找到数据库，请用 --db 指定实际文件后卸载")
    log_in_use = cleaned is not None and "/var/log/flownote-xray" in json.dumps(cleaned)
    allowed = set(APP_FILES + (DATA_PATHS + (() if log_in_use else LOG_PATHS) if purge else ()))
    protected = (db, Path(args.xui_dir).resolve()) + ((core,) if core else ())
    for path in sorted(allowed):
        checked_removal(path, allowed)
        if any(target == path or path in target.parents for target in protected):
            raise ValueError("3x-ui 文件与清理目录重叠，停止卸载: " + str(path))
    print("将停止并禁用 FlowNote，移除程序、菜单和 systemd 单元。")
    print("仅移除可核对的 FlowNote 查询出站 / 路由；3x-ui、节点和流量统计保留。")
    print("请先删除客户端的 6.6.6.6 分流规则；Xray 配置变更会短暂重启 x-ui。")
    if purge:
        print("将永久删除 /etc/flownote、/var/lib/flownote、/var/backups/flownote（含 Token、证书、历史和备份）。")
        print("自定义到这些目录以外的文件保留；共享日志、系统 journal 和面板 API Token 需另行处理。")
    if log_in_use:
        print("Xray 仍使用专用日志：保留该日志、轮转配置和服务账号，避免破坏面板日志。")
    confirmation = "DELETE" if purge else "UNINSTALL"
    if input("输入 " + confirmation + " 确认，其他输入取消: ").strip() != confirmation:
        print("已取消。")
        return False
    was_active = subprocess.run(["systemctl", "is-active", "--quiet", "flownote"], timeout=5).returncode == 0
    directory = None
    if replacement is not None:
        root = BACKUP_ROOT
        if root.is_symlink():
            raise ValueError("备份目录不能为符号链接")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chown(root, 0, 0)
        os.chmod(root, 0o700)
        directory = Path(tempfile.mkdtemp(prefix="uninstall-", dir=str(root)))
        write_private(directory / "xray-template.after.json", json.dumps(cleaned, ensure_ascii=False, indent=2))
        runtime = load_json((core.parent / "config.json").read_text(encoding="utf-8"))
        test_xray(core, unmerged_config(runtime, before, after), directory)
    command(["systemctl", "stop", "flownote"])
    try:
        if replacement is not None:
            uninstall_xray(db, original, replacement, directory, core)
    except BaseException:
        if was_active:
            command(["systemctl", "start", "flownote"])
        raise
    command(["systemctl", "disable", "flownote"])
    # Recheck exact paths immediately before each deletion; do not follow links or mounts.
    for path in APP_FILES:
        remove_owned(path, allowed)
    command(["systemctl", "daemon-reload"])
    subprocess.run(["systemctl", "reset-failed", "flownote"], capture_output=True, timeout=5)
    if purge:
        for path in DATA_PATHS[:2] + (() if log_in_use else LOG_PATHS):
            remove_owned(path, allowed)
        if not log_in_use:
            try:
                remove_service_account()
            except (OSError, subprocess.SubprocessError):
                print("程序与数据已清理，服务账号删除失败，请检查是否有残留进程。")
        remove_owned(DATA_PATHS[2], allowed)  # Drop rollback backups only after every other cleanup step.
    print("FlowNote 已卸载。" + ("默认目录的数据已清理。" if purge else "配置、Token、历史与备份已保留。"))
    print("请在面板撤销不再使用的 API Token；客户端分流规则与系统 journal 不会自动修改。")
    print("自定义日志文件及其 ACL 保留，请按原部署方式清理；不会删除共享 Xray 日志。")
    return True

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
    parser.add_argument("--advanced", action="store_true", help="手动指定面板地址、日志与验证客户端")
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
        print("\n流量笺 · FlowNote\n  1. 检测 3x-ui 安装\n  2. 配置 HTTP 查询入口\n  3. 查看服务状态与日志\n  4. 显示客户端分流规则\n  5. 卸载与清理\n  0. 退出")
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
            elif choice == "5":
                if uninstall(args):
                    return
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
