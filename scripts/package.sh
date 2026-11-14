#!/usr/bin/env bash
set -euo pipefail
# Usage: scripts/package.sh TARGET ARCH [OUTPUT_DIRECTORY]
target="${1:?target triple required}"
arch="${2:?release architecture required}"
out="${3:-output/dist}"
version="$(awk -F '"' '/^version = / {print $2; exit}' Cargo.toml)"
root="flownote-v${version}-linux-${arch}"
mkdir -p "$out/$root"
install -m 0755 "target/$target/release/flownote" "$out/$root/flownote"
install -m 0644 deploy/config.example.toml deploy/config.https.example.toml deploy/flownote.service deploy/xray-snippet.json deploy/xray-https-snippet.json LICENSE docs/INSTALL.md "$out/$root/"
tar -C "$out" -czf "$out/$root.tar.gz" "$root/"
printf '%s\n' "$out/$root.tar.gz"
