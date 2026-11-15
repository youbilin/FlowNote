#!/usr/bin/env bash
# FlowNote Linux installer. Downloads only published HTTPS release assets.
set -Eeuo pipefail

main() {
    local version='v0.3.7' interactive=false download_only='' arch='' release root_dir archive tmp expected actual dest was_active=false
    while (($#)); do
        case "$1" in
            --version) [[ $# -ge 2 ]] || die 'Missing --version value'; version="$2"; shift 2 ;;
            --download-only) [[ $# -ge 2 ]] || die 'Missing output directory'; download_only="$2"; shift 2 ;;
            --setup) interactive=true; shift ;;
            -h|--help) printf '%s\n' 'Usage: bash install.sh [--version v0.3.7] [--download-only DIR] [--setup]' 'Installs binary, example config and systemd unit; configure panel token, log access and Xray/client routing before first start.'; return ;;
            *) die "Unknown option: $1" ;;
        esac
    done
    [[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die 'Version must look like v0.3.7'
    [[ "$(uname -s)" == Linux ]] || die 'Only Linux is supported'
    case "$(uname -m)" in
        x86_64|amd64) arch=amd64 ;;
        aarch64|arm64) arch=arm64 ;;
        *) die 'Supported architectures: amd64 and arm64' ;;
    esac
    local tool
    for tool in curl tar sha256sum awk sort cmp mktemp install; do command -v "$tool" >/dev/null || die "Required command missing: $tool"; done
    if "$interactive"; then
        [[ -z "$download_only" ]] || die "--setup cannot be combined with --download-only"
        command -v python3 >/dev/null || die "Install Python 3 first: sudo apt-get install -y python3"
        [[ -t 0 || -t 1 ]] || die "--setup requires an interactive terminal"
    fi
    if [[ -z "$download_only" ]]; then
        [[ "$EUID" -eq 0 ]] || die 'Use sudo bash install.sh, or --download-only DIR without root'
        for tool in systemctl useradd getent; do command -v "$tool" >/dev/null || die "Required command missing: $tool"; done
        [[ -d /run/systemd/system ]] || die 'A running systemd host is required; use --download-only for other systems'
    fi
    tmp="$(mktemp -d)"
    flownote_tmp="$tmp"
    trap 'rm -rf -- "${flownote_tmp:?}"' EXIT
    root_dir="flownote-${version}-linux-${arch}"
    archive="${root_dir}.tar.gz"
    release="https://github.com/youbilin/FlowNote/releases/download/${version}"
    printf 'Downloading FlowNote %s (%s)...\n' "$version" "$arch"
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --tlsv1.2 --connect-timeout 15 --max-time 300 --output "$tmp/$archive" "$release/$archive"
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --tlsv1.2 --connect-timeout 15 --max-time 60 --output "$tmp/SHA256SUMS" "$release/SHA256SUMS"
    expected="$(awk -v name="$archive" '$2 == name {print $1}' "$tmp/SHA256SUMS")"
    [[ "$expected" =~ ^[a-f0-9]{64}$ ]] || die 'Checksum manifest has no unique valid entry for this archive'
    actual="$(sha256sum "$tmp/$archive")"
    [[ "${actual%% *}" == "$expected" ]] || die 'SHA-256 mismatch; installation stopped'
    # Reject unexpected paths, duplicate entries, links and special files before extraction.
    printf '%s\n' "$root_dir/" "$root_dir/flownote" "$root_dir/config.example.toml" "$root_dir/config.https.example.toml" "$root_dir/xray-https-snippet.json" "$root_dir/flownote.service" "$root_dir/xray-snippet.json" "$root_dir/LICENSE" "$root_dir/INSTALL.md" "$root_dir/setup.sh" "$root_dir/setup.py" | LC_ALL=C sort > "$tmp/expected"
    tar -tzf "$tmp/$archive" | LC_ALL=C sort > "$tmp/actual"
    cmp -s "$tmp/expected" "$tmp/actual" || die 'Unexpected archive layout'
    tar -tvzf "$tmp/$archive" | awk 'substr($0,1,1) != "-" && substr($0,1,1) != "d" {bad=1} END {exit bad}' || die 'Links or special files in archive'
    tar -xzf "$tmp/$archive" --no-same-owner --no-same-permissions -C "$tmp"
    [[ "$("$tmp/$root_dir/flownote" --version)" == "flownote ${version#v}" ]] || die 'Binary version mismatch'
    if [[ -n "$download_only" ]]; then
        mkdir -p -- "$download_only"
        dest="$(cd -- "$download_only" && pwd)"
        [[ ! -e "$dest/$archive" && ! -e "$dest/SHA256SUMS" ]] || die 'Output files already exist'
        install -m 0644 "$tmp/$archive" "$dest/$archive"
        install -m 0644 "$tmp/SHA256SUMS" "$dest/SHA256SUMS"
        printf 'Verified package saved to %s\n' "$dest/$archive"
        return
    fi
    if systemctl is-active --quiet flownote.service; then was_active=true; fi
    if ! getent passwd flownote >/dev/null; then
        useradd --system --user-group --home-dir /var/lib/flownote --no-create-home --shell /usr/sbin/nologin flownote
    fi
    getent group flownote >/dev/null || die 'Existing flownote user requires a flownote group'
    install -d -o root -g flownote -m 0750 /etc/flownote /etc/flownote/tls
    install -d -o flownote -g flownote -m 0700 /var/lib/flownote
    install -d -m 0755 /usr/local/bin
    if [[ ! -e /etc/flownote/config.toml && ! -L /etc/flownote/config.toml ]]; then
        install -o root -g flownote -m 0640 "$tmp/$root_dir/config.example.toml" /etc/flownote/config.toml
    fi
    install -o root -g flownote -m 0640 "$tmp/$root_dir/config.example.toml" /etc/flownote/config.example.toml
    if [[ -f /usr/local/bin/flownote ]]; then install -m 0755 /usr/local/bin/flownote /usr/local/bin/flownote.previous; fi
    install -m 0755 "$tmp/$root_dir/flownote" /usr/local/bin/flownote.new
    mv -f /usr/local/bin/flownote.new /usr/local/bin/flownote
    install -m 0644 "$tmp/$root_dir/flownote.service" /etc/systemd/system/flownote.service
    install -d -m 0755 /usr/local/share/flownote
    install -m 0644 "$tmp/$root_dir/xray-snippet.json" "$tmp/$root_dir/xray-https-snippet.json" "$tmp/$root_dir/config.https.example.toml" "$tmp/$root_dir/INSTALL.md" "$tmp/$root_dir/LICENSE" /usr/local/share/flownote/
    install -m 0644 "$tmp/$root_dir/setup.py" /usr/local/share/flownote/setup.py
    install -m 0755 "$tmp/$root_dir/setup.sh" /usr/local/bin/flownote-setup
    systemctl daemon-reload
    if "$was_active"; then
        local restarted=true
        systemctl restart flownote.service || restarted=false
        # systemctl restart can succeed before the application finishes loading its configuration.
        sleep 2
        if ! "$restarted" || ! systemctl is-active --quiet flownote.service; then
            if [[ -f /usr/local/bin/flownote.previous ]]; then
                install -m 0755 /usr/local/bin/flownote.previous /usr/local/bin/flownote.new
                mv -f /usr/local/bin/flownote.new /usr/local/bin/flownote
                systemctl restart flownote.service || true
            fi
            die 'Upgrade did not stay active; previous binary restored when available. Check journalctl -u flownote'
        fi
    fi
    printf '\nFlowNote %s installed.\n' "$version"
    if "$interactive"; then
        /usr/local/bin/flownote-setup
    elif ! "$was_active"; then
        printf '%s\n' 'Next: edit /etc/flownote/config.toml; save panel token; grant log access and merge /usr/local/share/flownote/xray-snippet.json.' 'Guide: https://github.com/youbilin/FlowNote/blob/main/docs/DEPLOYMENT.md' 'Interactive setup: sudo flownote-setup (requires Python 3)' 'Manual start: systemctl enable --now flownote.service'
    fi
}
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
main "$@"
