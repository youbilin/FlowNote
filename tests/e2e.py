"""Linux local integration: real TLS + PROXY, synthetic log and panel. No production access."""
import concurrent.futures
import http.server
import json
from pathlib import Path
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import unquote


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Panel(http.server.BaseHTTPRequestHandler):
    calls = {}
    lock = threading.Lock()
    def log_message(self, *_):
        pass
    def do_GET(self):
        assert self.headers.get("Authorization") == "Bearer fixture-only"
        assert self.path.startswith("/base/panel/api/clients/traffic/")
        email = unquote(self.path.rsplit("/", 1)[1])
        with self.lock:
            self.calls[email] = self.calls.get(email, 0) + 1
        self.send_response(200)
        self.end_headers()
        if email == "invalid-json":
            self.wfile.write(b"private upstream details not json")
            return
        if email == "oversized":
            self.wfile.write(b"x" * 70000)
            return
        if email == "missing":
            self.wfile.write(b'{"success":true,"obj":null}')
            return
        obj = dict(email="not-your-account" if email == "mismatch" else email,
                   up=-1 if email == "negative" else 1000, down=2000, total=10000,
                   enable=True, expiryTime=0, uuid="DO_NOT_LEAK", subId="DO_NOT_LEAK")
        self.wfile.write(json.dumps(dict(success=True, obj=obj)).encode())


def main():
    binary = Path(sys.argv[1] if len(sys.argv) > 1 else "target/debug/flownote").resolve()
    plain = "--http" in sys.argv[2:]
    domain = "6.6.6.6" if plain else "traffic.example.test"
    scheme = "HTTP" if plain else "TLS"
    panel = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Panel)
    threading.Thread(target=panel.serve_forever, daemon=True).start()
    checks = []
    def check(name, value):
        assert value, name
        checks.append(name)
        print("PASS", name)
    with tempfile.TemporaryDirectory(prefix="flownote-e2e-") as folder:
        root = Path(folder)
        cert, key = root / "cert.pem", root / "key.pem"
        if not plain:
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                            "-keyout", str(key), "-out", str(cert), "-subj", "/CN=traffic.example.test",
                            "-addext", "subjectAltName=DNS:traffic.example.test"],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log = root / "access.log"
        log.touch()
        port = free_port()
        cfg = root / "config.toml"
        transport = 'protocol = "http"' if plain else f'[tls]\ncert_file = "{cert}"\nkey_file = "{key}"'
        cfg.write_text(f'''[server]
listen = "127.0.0.1:{port}"
domain = "{domain}"
{transport}
[xray]
access_log = "{log}"
lookup_timeout_ms = 300
[panel]
base_url = "http://127.0.0.1:{panel.server_port}/base"
token = "fixture-only"
[history]
enabled = true
directory = "{root / "history"}"
''')
        proc = subprocess.Popen([str(binary), str(cfg)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                if proc.poll() is not None:
                    raise RuntimeError("FlowNote startup failed")
                try:
                    socket.create_connection(("127.0.0.1", port), .1).close()
                    break
                except OSError:
                    time.sleep(.05)
            else:
                raise RuntimeError("startup timeout")
            time.sleep(.3)  # initial tail must open before fixture records are appended
            client = None if plain else ssl.create_default_context(cafile=str(cert))
            counter = 41000
            lock = threading.Lock()
            def record(src, email, tag="traffic-query"):
                with log.open("a") as f:
                    f.write(f"2026/11/14 12:00:00 from {src} accepted tcp:{domain}:{80 if plain else 443} [in-test >> {tag}] email: {email}\n")
            def request(email="alice", path="/json", method="GET", version=2, source=None,
                        host=domain, sni="traffic.example.test", log_enabled=True,
                        delay=0, tag="traffic-query", extra="", accept="text/html"):
                nonlocal counter
                with lock:
                    counter += 1
                    sport = counter
                source = source or f"203.0.113.10:{sport}"
                ip, sport = source.rsplit(":", 1)
                if log_enabled:
                    if delay:
                        threading.Timer(delay, record, args=(source, email, tag)).start()
                    else:
                        record(source, email, tag)
                        time.sleep(.15)
                sock = socket.create_connection(("127.0.0.1", port), timeout=4)
                if version == 1:
                    sock.sendall(f"PROXY TCP4 {ip} 127.0.0.1 {sport} 8686\r\n".encode())
                else:
                    sock.sendall(b"\r\n\r\n\x00\r\nQUIT\n" + b"\x21\x11" + struct.pack("!H", 12)
                                 + socket.inet_aton(ip) + socket.inet_aton("127.0.0.1")
                                 + struct.pack("!HH", int(sport), 8686))
                with (sock if plain else client.wrap_socket(sock, server_hostname=sni)) as tls:
                    tls.sendall(f"{method} {path} HTTP/1.1\r\nHost: {host}\r\nAccept: {accept}\r\n{extra}Connection: close\r\n\r\n".encode())
                    raw = b""
                    while True:
                        chunk = tls.recv(65536)
                        if not chunk:
                            break
                        raw += chunk
                head, _, body = raw.partition(b"\r\n\r\n")
                status = int(head.split(b" ")[1])
                return status, head.decode(), body.decode()
            status, headers, body = request()
            check(scheme + " + PROXY v2 JSON self query", status == 200 and json.loads(body)["email"] == "alice")
            check("no secret projection", "uuid" not in body and "subId" not in body and "DO_NOT_LEAK" not in body)
            check("security headers", all(v in headers.lower() for v in ["no-store", "content-security-policy", "no-referrer", "nosniff"]))
            check("HSTS matches configured protocol", ("strict-transport-security" in headers.lower()) == (not plain))
            check("explicit default Host port", request(host=f"{domain}:{80 if plain else 443}")[0] == 200)
            check("wrong Host port denied", request(host=f"{domain}:{443 if plain else 80}")[0] == 421)
            forwarded = request(extra="X-Forwarded-Proto: https\r\nForwarded: proto=https\r\n")
            check("forwarded protocol cannot change transport headers", ("strict-transport-security" in forwarded[1].lower()) == (not plain))
            check("PROXY v1 compatibility", request("bob", version=1)[0] == 200)
            alice = json.loads(request()[2])
            check("history uses actual cumulative counters", alice["history"] == [{"at_ms": alice["history"][0]["at_ms"], "up": 1000, "down": 2000}])
            check("cached snapshots do not add samples", len(alice["history"]) == 1)
            bob = json.loads(request("bob")[2])
            check("history isolated per account", len(bob["history"]) == 1 and bob["email"] == "bob")
            import hashlib
            history_path = root / "history" / (hashlib.sha256(b"alice").hexdigest() + ".json")
            check("history persists without raw account filenames", json.loads(history_path.read_text()) == alice["history"] and not (root / "history" / "alice.json").exists())
            history_path.write_text("corrupt")
            res = request()
            check("history failure preserves live query", res[0] == 200 and json.loads(res[2])["used"] == 3000 and json.loads(res[2])["history"] == [])
            history_path.write_text(json.dumps(alice["history"]))
            check("delayed log association", request("late", delay=.1)[0] == 200)
            check("unknown identity denied", request(log_enabled=False)[0] == 403)
            check("other outbound ignored", request("outsider", tag="direct")[0] == 403)
            check("spoofed account parameter rejected", request(path="/json?email=bob")[0] == 400)
            check("forwarded headers cannot select identity", json.loads(request(extra="X-Forwarded-For: 1.2.3.4\r\nX-User: bob\r\n")[2])["email"] == "alice")
            check("HTML UI", "剩余流量" in request(path="/")[2])
            check("text negotiation", "已用:" in request(path="/?format=text")[2])
            head = request(method="HEAD")
            check("HEAD has no body", head[0] == 200 and head[2] == "")
            check("method rejected", request(method="POST")[0] == 405)
            check("unknown path rejected", request(path="/admin")[0] == 404)
            check("wrong Host rejected", request(host="other.example.test")[0] == 421)
            check("absolute-form rejected", request(path="https://traffic.example.test/json")[0] == 421)
            for name in ["missing", "mismatch", "negative", "invalid-json", "oversized"]:
                res = request(name)
                check("upstream rejected: " + name, res[0] == 502 and "private upstream" not in res[2] and "not-your-account" not in res[2])
            src = "203.0.113.20:52000"
            record(src, "alice")
            record(src, "bob")
            time.sleep(.2)
            check("known conflicting source denied", request(source=src, log_enabled=False)[0] == 403)
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                results = list(pool.map(lambda _: request("cached-user"), range(6)))
            check("cache coalesces concurrent fetches", all(r[0] == 200 for r in results) and Panel.calls["cached-user"] == 1)
            # Owned test log only: truncate and then rotate.
            log.write_text("")
            time.sleep(.2)
            check("log truncate recovery", request("after-truncate")[0] == 200)
            log.rename(root / "access.log.1")
            log.touch()
            time.sleep(.2)
            check("log rotation recovery", request("after-rotate")[0] == 200)
            with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
                sock.sendall(b"GET / HTTP/1.1\r\nHost: traffic.example.test\r\n\r\n")
                try:
                    raw = sock.recv(4096)
                except ConnectionResetError:
                    raw = b""
            check("non-PROXY request gets no data", not raw)
            if not plain:
                # Untrusted TLS certificate fails without altering system trust.
                sock = socket.create_connection(("127.0.0.1", port), timeout=3)
                sock.sendall(b"PROXY TCP4 203.0.113.10 127.0.0.1 55000 8686\r\n")
                try:
                    ssl.create_default_context().wrap_socket(sock, server_hostname="traffic.example.test")
                    raise AssertionError("untrusted certificate accepted")
                except ssl.SSLCertVerificationError:
                    check("certificate validation enforced by client", True)
                finally:
                    sock.close()
                for sni in ["wrong.example.test", None]:
                    context = ssl.create_default_context(cafile=str(cert))
                    context.check_hostname = False  # isolate the server-side SNI check, CA verification stays on
                    sock = socket.create_connection(("127.0.0.1", port), timeout=3)
                    sock.sendall(b"PROXY TCP4 203.0.113.10 127.0.0.1 55001 8686\r\n")
                    rejected = False
                    try:
                        with context.wrap_socket(sock, server_hostname=sni) as tls:
                            tls.sendall(b"GET / HTTP/1.1\r\nHost: traffic.example.test\r\n\r\n")
                            rejected = not tls.recv(4096)
                    except (ssl.SSLError, ConnectionError):
                        rejected = True
                    finally:
                        sock.close()
                    check("server rejects SNI: " + str(sni), rejected)
            else:
                check("HTTP starts without certificate files", not cert.exists() and not key.exists())
            check("favicon carries no private data", request(path="/favicon.ico")[0] == 204)
            print(f"{len(checks)} integration checks passed; synthetic fixtures only")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            panel.shutdown()
            panel.server_close()


if __name__ == "__main__":
    main()
