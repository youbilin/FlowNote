FlowNote v0.3.2 adds **http://6.6.6.6/** as the default query entry. No domain, DNS or certificate is needed. Clients route this IP through their own account node; Xray intercepts TCP 80 and forwards HTTP with PROXY metadata to loopback FlowNote. The real public IP serves only as a routing convention.

- Existing HTTPS configurations remain compatible: missing protocol still means HTTPS.
- Host and port checks follow the configured protocol. HSTS is sent only over HTTPS.
- Same minimal dashboard, upload/download query-sample curves and API-token access. No panel subscription needed.
- Linux amd64 and arm64 static packages include HTTP and HTTPS configurations and routing fragments.
- README includes installation, log permissions, client routing, troubleshooting and migration steps.

Review install.sh from this release and run it with --version v0.3.2. Existing configurations and secrets are preserved. Changing an existing deployment to HTTP requires manually updating its configuration and both routing rules. First installs wait for configuration before starting.

HTTP has no independent origin authentication or integrity. Keep requests inside the correct authenticated encrypted node tunnel and loopback redirect. Keep port 8686 off the public network. Real Xray deployment still requires two-account validation; Mux, CDN frontends and shared underlying connections are unsupported.

Release builds run unit, HTTP/PROXY, TLS/PROXY and installer checks on both native architectures before publication. SHA256SUMS detects corruption and is not an independent signature.
