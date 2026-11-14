"""Linux process measurement with synthetic panel/logs; never touches host services.
Usage: python3 tests/performance.py BINARY [--seconds 8]
Reports measured RSS, process CPU, thread count and query latency; no universal thresholds.
"""
import argparse
import http.server
import json
import os
from pathlib import Path
import socket
import statistics
import subprocess
import tempfile
import threading
import time


def port():
    with socket.socket() as stream:
        stream.bind(("127.0.0.1", 0))
        return stream.getsockname()[1]


class Panel(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer fixture-only":
            self.send_error(403)
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"success": True, "obj": {
            "email": "alice", "up": 1000, "down": 2000, "total": 10000,
            "expiryTime": 0, "enable": True,
        }}).encode())


def stats(pid):
    root = Path("/proc") / str(pid)
    fields = (root / "stat").read_text().rsplit(")", 1)[1].split()
    status = dict(line.split(":", 1) for line in (root / "status").read_text().splitlines())
    io = dict(line.split(":", 1) for line in (root / "io").read_text().splitlines())
    return {"cpu_seconds": (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK"),
            "rss_kib": int(status["VmRSS"].split()[0]), "threads": int(status["Threads"]),
            "read_syscalls": int(io["syscr"])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("--seconds", type=float, default=8)
    args = parser.parse_args()
    panel = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Panel)
    threading.Thread(target=panel.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="flownote-perf-") as folder:
            root = Path(folder)
            log = root / "access.log"
            log.touch()
            listen = port()
            config = root / "config.toml"
            config.write_text(f'''[server]
listen = "127.0.0.1:{listen}"
protocol = "http"
domain = "6.6.6.6"
[xray]
access_log = "{log}"
[panel]
base_url = "http://127.0.0.1:{panel.server_port}"
token = "fixture-only"
[history]
enabled = false
directory = "{root / "history"}"
''')
            process = subprocess.Popen([str(args.binary.resolve()), str(config)],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("startup failed")
                    try:
                        with socket.create_connection(("127.0.0.1", listen), .1):
                            break
                    except OSError:
                        time.sleep(.05)
                else:
                    raise RuntimeError("startup timeout")
                time.sleep(.3)
                before = stats(process.pid)
                started = time.monotonic()
                time.sleep(args.seconds)
                after = stats(process.pid)
                elapsed = time.monotonic() - started
                idle = {**after, "window_seconds": round(elapsed, 3),
                        "cpu_seconds": round(after["cpu_seconds"] - before["cpu_seconds"], 4),
                        "read_syscalls": after["read_syscalls"] - before["read_syscalls"]}
                latencies = []
                for number in range(30):
                    source = 41000 + number
                    with log.open("a") as file:
                        file.write(f"2026/11/14 12:00:00 from 203.0.113.10:{source} accepted tcp:6.6.6.6:80 [in >> traffic-query] email: alice\n")
                    started = time.monotonic()
                    with socket.create_connection(("127.0.0.1", listen), 4) as stream:
                        stream.sendall(f"PROXY TCP4 203.0.113.10 127.0.0.1 {source} 8686\r\nGET /json HTTP/1.1\r\nHost: 6.6.6.6\r\nConnection: close\r\n\r\n".encode())
                        data = b""
                        while chunk := stream.recv(65536):
                            data += chunk
                    assert data.startswith(b"HTTP/1.1 200"), data[:200]
                    latencies.append((time.monotonic() - started) * 1000)
                    time.sleep(.05)
                result = {"binary": str(args.binary), "idle": idle, "after_queries": stats(process.pid),
                          "queries": len(latencies), "latency_median_ms": round(statistics.median(latencies), 2),
                          "latency_max_ms": round(max(latencies), 2),
                          "history_directory_created": (root / "history").exists()}
                print(json.dumps(result, indent=2))
            finally:
                process.terminate()
                process.wait(timeout=5)
    finally:
        panel.shutdown()
        panel.server_close()


if __name__ == "__main__":
    main()
