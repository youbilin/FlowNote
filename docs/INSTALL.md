# FlowNote v0.3.3 Linux package

Static musl binary for Linux amd64 or arm64. Includes HTTP / HTTPS templates, Xray routing fragments, a systemd unit, the Python 3 setup wizard and the MIT license.

Verify the archive against SHA256SUMS from the same release. This detects corruption; it is not an independent signature. Review install.sh, then run:

```bash
sudo bash install.sh --version v0.3.3 --setup
# Reopen the installed menu anytime:
sudo flownote-setup
# Inspect only:
sudo flownote-setup --detect
```

Python 3 is required for the menu; only the standard library is used. Install it first if needed (`sudo apt-get install -y python3` on Debian / Ubuntu). Omitting --setup keeps installation noninteractive and does not modify Xray. Existing settings survive installation; active FlowNote services restart on upgrade.

For a standard local 3x-ui installation, choose 2. Defaults: /usr/local/x-ui, /etc/x-ui/x-ui.db and the architecture-specific Xray executable under bin/. The panel port and base path come from settings, not a hard-coded port. Enter an API token (hidden input) and a real client email for API validation. A TLS panel requires its verified HTTPS address. Subscriptions may remain disabled. If the Xray template has never been persisted, save the current configuration in the panel Xray settings once and rerun.

The wizard previews and tests the candidate configuration, then asks before applying. It validates the panel, backs up to root-only /var/backups/flownote/, changes only the persisted Xray template, sets log permissions, and starts the services. Restarting x-ui can interrupt connections briefly. Generated HTTP/history settings replace custom FlowNote settings after backup; source-address masking in the access log is disabled for account correlation. Failure recovery restores the template and FlowNote settings without rolling the entire traffic database back; log files, ACLs and rotation configuration may remain.

Default log: /var/log/flownote-xray/access.log. The generated /etc/logrotate.d/flownote-xray needs system logrotate installed. Existing logs need persistent read permissions across rotation and may require acl. Do not use logs under /root or /home because the service uses ProtectHome.

Automatic setup supports local systemd x-ui and SQLite in the same network namespace. Custom locations use --xui-dir, --db and --core. Docker, PostgreSQL and remote panels require manual configuration. Do not edit generated runtime bin/config.json as a panel template.

After setup, add the client rule before broader rules, replacing the policy name:

```yaml
rules:
  - IP-CIDR,6.6.6.6/32,YOUR-NODE-OR-POLICY,no-resolve
```

Connect your own account node, enable system proxy / TUN, disable Mux for this connection, then open http://6.6.6.6/. No domain, DNS or certificate is required. 6.6.6.6 is a real public IP used only as an intercepted routing convention. Keep 8686 bound to loopback and do not expose it publicly. HTTP has no independent browser-to-service HTTPS protection.

For HTTPS, use config.https.example.toml and xray-https-snippet.json with your own domain and valid certificate. Do not use the HTTP wizard to overwrite an existing conflicting HTTPS query route.

Before sharing, perform the README real two-account tests, including same-NAT concurrency, reconnection, conflicting identities and log rotation. Service startup alone does not prove the identity chain. Never publish tokens, backup databases, candidate configs with node credentials or real logs.

Full instructions: https://github.com/youbilin/FlowNote#readme
