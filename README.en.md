<div align="center">
<img src="docs/assets/banner.svg" alt="FlowNote traffic dashboard" width="100%" />

# FlowNote

**Connect your node. Open a link. Know your traffic balance.**

A minimal traffic dashboard for users sharing a 3x-ui server through individual accounts. No panel subscription or end-user login required.

[![CI](https://github.com/youbilin/FlowNote/actions/workflows/ci.yml/badge.svg)](https://github.com/youbilin/FlowNote/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-0.3.6-246852)](CHANGELOG.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[简体中文](README.md) · **English**
</div>

## At a glance

<img src="docs/assets/desktop.png" alt="Remaining traffic, uploads, downloads, quota and expiry" width="100%" />

Screenshots use synthetic data. The UI is in Chinese; this README does not imply UI localization.

- Remaining / used traffic, uploads / downloads, total quota, expiry, account status and last online time.
- Optional cumulative curves sampled when users query; no historical backfill or exact daily billing.
- Responsive light / dark UI without JavaScript, external fonts, analytics or browser storage.
- HTML, text and JSON; GET / HEAD. Query parameters cannot select another account.
- Default **http://6.6.6.6/** without DNS or certificates. Existing native HTTPS deployments remain supported.

## Lightweight operation

One Rust process with a single asynchronous runtime thread; filesystem operations may use helper threads. No frontend build, database service or periodic traffic collector. Idle log checks run once per second and queries wake the reader immediately. New configurations disable history by default and skip history file I/O. Enable `[history] enabled = true` to retain query-time samples.

Working installations can upgrade without rerunning setup: use the installation command below **without `--setup`**. Existing configuration, tokens and history preferences are preserved. To disable previously enabled history, set `enabled = false` under `[history]` in `/etc/flownote/config.toml` and restart `flownote`. `MemoryMax=192M` is a ceiling, not reserved RAM. See [measurements and validation](docs/TESTING.md).

## Set up http://6.6.6.6/

6.6.6.6 is a real public address used only as an intercepted routing convention. FlowNote does not own or contact it. Do not assign it to an interface or expose port 8686.

1. Run Linux amd64 / arm64 with systemd. FlowNote and Xray must share a host **and network namespace**. The panel must support API tokens and `/panel/api/clients/traffic/{email}`. Each account needs a unique email label. Disable Mux and shared underlying connections.
2. Install the fixed release:

```bash
curl --proto '=https' --tlsv1.2 -fsSL https://github.com/youbilin/FlowNote/releases/download/v0.3.6/install.sh | sudo bash -s -- --version v0.3.6 --setup
```

The installer validates SHA-256, archive paths and binary version. First installs wait for configuration before starting. Existing configurations and secrets are preserved; active services restart on upgrade. You can download and inspect the script first, or use `--download-only ./flownote-download` without installing.

**Interactive setup is recommended for a standard local 3x-ui installation.** Install Python 3 if missing (`sudo apt-get install -y python3`). The command above opens the menu; reopen it anytime with:

```bash
sudo flownote-setup
# Read-only discovery:
sudo flownote-setup --detect
```

Choose `2` to configure the HTTP entry. Standard installations only need an API token (hidden input) and confirmation. The wizard discovers panel paths and the actual port/base path, prefers the running Xray log over the persisted template, and selects an existing client to validate API access. A client identifier is requested only when none is found. HTTPS panels require an explicit verified URL. Use `sudo flownote-setup --advanced` for manual overrides. If the persisted template is missing, save the current configuration once in the panel's Xray settings and rerun.

After confirmation, missing `logrotate` / `acl` tools are installed through apt-get, dnf or apk. After restarting the panel, the wizard verifies query routes and full source addresses, synchronizes the effective log path and checks read access before starting FlowNote. Shared log rotation must preserve permissions.

The initial Xray check uses a private temporary access log, so a not-yet-created production log directory does not fail first-time setup. After confirmation, the wizard prepares the real log and checks the exact candidate before restarting x-ui. Only an explicit unsupported `finalRules` error offers a compatibility retry. On failure, root-only `xray-check.stdout.log` and `xray-check.stderr.log` retain raw diagnostics at the displayed paths; redact credentials before sharing errors.

After explicit confirmation, it validates the panel, backs up to root-only `/var/backups/flownote/`, merges the query outbound/rules into the persisted template, grants log access, and starts FlowNote. Restarting x-ui can briefly interrupt connections. Existing custom FlowNote settings are backed up and replaced with the generated HTTP config with history disabled; Xray source-address masking is disabled for account correlation. On failure it attempts to restore only the template and FlowNote settings; it does not restore the whole traffic database. Installed packages, log files, ACLs or rotation changes may remain. The default dedicated log needs system `logrotate`; existing logs must retain read permissions across rotation.

**After successful setup, skip manual steps 3–5 and 7. Continue with client routing in step 6, then query and perform the real two-account checks in steps 8–9.** The wizard supports local systemd/SQLite installations; Docker, PostgreSQL and remote panels need manual configuration. Custom locations: `sudo flownote-setup --xui-dir /path/to/panel --db /path/to/x-ui.db --core /path/to/xray`.

3. Manual alternative: save the raw panel token in `/etc/flownote/token` (root:flownote, mode 0640). Edit `/etc/flownote/config.toml` using [the default template](deploy/config.example.toml):

```toml
[server]
listen = "127.0.0.1:8686"
protocol = "http"
domain = "6.6.6.6"

[xray]
access_log = "/usr/local/x-ui/access.log"
outbound_tag = "traffic-query"

[panel]
base_url = "http://127.0.0.1:2053"
token_file = "/etc/flownote/token"
```

Include your panel webBasePath in base_url if configured, without appending /panel/api. Remote panel HTTP is rejected; use verified HTTPS. Do not add `[tls]` in HTTP mode. The full template includes optional query history, disabled by default.

4. Enable Xray access logging at the same path. Grant flownote read permission on that file and traversal of its parent directories; preserve access after rotation. Do not recursively expose the panel directory or database.
5. Merge [xray-snippet.json](deploy/xray-snippet.json) into the persistent Xray configuration. Append the traffic-query freedom outbound with redirect `127.0.0.1:8686` and proxyProtocol `2`. Keep the existing default outbound first. Insert the exact `6.6.6.6/32`, TCP, port 80 routing rule before other rules; the following block rule prevents other traffic to that IP leaving the server. Explanatory keys are merge instructions, not Xray fields. Newer freedom versions may need a supported finalRules exception allowing only TCP loopback port 8686 for this outbound.
6. In Clash / Mihomo, insert this rule first, replacing the policy name:

```yaml
rules:
  - IP-CIDR,6.6.6.6/32,YOUR-NODE-OR-POLICY,no-resolve
  # existing rules follow
```

Select your own account node, not DIRECT or a group mixing accounts. Enable browser capture through system proxy, TUN or browser settings. Other clients need an equivalent IP rule. No DNS or hosts change is needed.

7. Validate the panel and start FlowNote:

```bash
sudo -u flownote /usr/local/bin/flownote /etc/flownote/config.toml --check-panel 'REAL-CLIENT-EMAIL'
sudo systemctl enable --now flownote
sudo journalctl -u flownote -n 50 --no-pager
```

8. Connect your node and open **http://6.6.6.6/**. Allow HTTP for this address if your browser upgrades it. HTTPS on this IP is intentionally unsupported. From your computer, replace the example SOCKS port with the real one:

```bash
curl --proxy socks5h://127.0.0.1:7891 'http://6.6.6.6/?format=text'
curl --proxy socks5h://127.0.0.1:7891 'http://6.6.6.6/json'
```

9. Validate with two distinct real accounts, including simultaneous queries behind the same NAT, reconnection and log rotation, before sharing the link. Direct curl to 8686 is rejected because PROXY metadata is required.

[Complete instructions, log ACL examples, routing JSON and troubleshooting (Chinese)](README.md#快速开始).

## Security and compatibility

HTTP has no independent origin authentication or integrity. An authenticated encrypted node tunnel protects traffic inside it; incorrect direct routing, an unencrypted LAN proxy hop and a compromised node remain risks. Keep loopback and account checks in place. This is not independent browser-to-FlowNote HTTPS.

Identity depends on Xray source / access-log correlation. Observed conflicts fail closed, but delayed logs can leave conflicts unobserved. Mux, CDN frontends and shared underlying connections are unsupported. Simulated tests do not replace real Xray validation. Expired / disabled accounts may be unable to reach the page if Xray rejects their connections.

Existing HTTPS configurations keep working: missing protocol defaults to HTTPS. Use [config.https.example.toml](deploy/config.https.example.toml) and [xray-https-snippet.json](deploy/xray-https-snippet.json) with an owned hostname and trusted certificate. DNS-01 does not require A / AAAA to point to the server. To switch to HTTP, update configuration and both routes, remove `[tls]`, restart and validate. Restore HTTPS settings and routes before reverting to v0.3.1.

Multi-VPS aggregation, groups and alerts are outside scope. v0.2 was skipped; v0.4 is not planned.

## Build and validate

```bash
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked
cargo build --locked
python3 tests/e2e.py target/debug/flownote
python3 tests/e2e.py target/debug/flownote --http
python3 tests/installer.py
cargo run --locked -- --preview output/preview
```

The preview contains synthetic static pages and needs no configuration or panel.

[Deployment](docs/DEPLOYMENT.md) · [Design](docs/DESIGN.md) · [UI](docs/UI.md) · [Test records](docs/TESTING.md) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Security reporting](SECURITY.md)

## License

[MIT](LICENSE) © 2026 You Bilin. Independent project, not affiliated with 3x-ui or Xray.

## Uninstall

Upgrade to v0.3.6, run `sudo flownote-setup`, then select **5**. Choose **1** and type `UNINSTALL` to remove the application, menu and service while retaining configuration, token, certificates, history, logs and backups. Choose **2** and type `DELETE` to additionally erase `/etc/flownote`, `/var/lib/flownote` and `/var/backups/flownote`, plus unused dedicated logs/rotation and the standard service account. Purging includes private certificates and all recovery backups and cannot be undone.

Both modes validate and remove only recognized wizard query outbounds/rules from the persistent Xray template, preserving nodes and traffic counters. Matching original backups can restore only unchanged log keys. Candidate-check or Xray-restart failure prevents application deletion; conflicting custom/HTTPS query rules need manual handling. If Xray still uses the dedicated log, its files, rotation and service account remain even during purge. Custom paths, shared log ACLs and system journals are retained. Remove client routing rules first and revoke unused panel API tokens separately.
