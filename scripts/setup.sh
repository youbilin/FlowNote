#!/usr/bin/env bash
set -euo pipefail
if ! command -v python3 >/dev/null; then
    printf '%s\n' '需要 Python 3（标准库即可）。Debian / Ubuntu: sudo apt-get install -y python3' >&2
    exit 1
fi
if [[ ! -t 0 && -t 1 ]]; then
    exec python3 /usr/local/share/flownote/setup.py "$@" </dev/tty
fi
exec python3 /usr/local/share/flownote/setup.py "$@"
