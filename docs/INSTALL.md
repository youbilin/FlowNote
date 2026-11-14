# FlowNote Linux package

This archive contains a static musl binary for its named architecture, an example configuration, a systemd unit, an Xray routing fragment, and the MIT license.

Verify the archive against SHA256SUMS from the same GitHub release before extracting it. This checksum detects corruption; it is not an independent signature.

Recommended installation: download install.sh from the matching release, inspect it, then run `sudo bash install.sh --version v0.3.1`. The installer verifies the archive and its binary version, creates the service account, and preserves existing configuration, token and certificates. It does not start a new unconfigured service. Active installations are restarted on upgrade; the previous binary is retained as /usr/local/bin/flownote.previous.

Before first start, configure /etc/flownote/config.toml with your domain, TLS certificate/key, panel token and access-log path. Grant the flownote account read access to the log, certificate and token. Merge xray-snippet.json into the existing Xray configuration and complete the two-account deployment acceptance checks.

History is optional and records cumulative counters only when users query. New configurations retain query samples for 30 days in /var/lib/flownote/history, at most once per hour unless counters reset. Old configurations without [history] keep history disabled. No daily usage or past records are reconstructed.

Full deployment guide: https://github.com/youbilin/FlowNote/blob/main/docs/DEPLOYMENT.md
