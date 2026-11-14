# FlowNote v0.3.2 Linux package

Static musl binary for Linux amd64 or arm64. Includes HTTP and HTTPS example configurations, Xray routing fragments, a systemd unit and the MIT license.

Verify the archive against SHA256SUMS from the same release. This detects corruption; it is not an independent signature. Review install.sh, then run it with --version v0.3.2. Existing configuration and secrets are preserved. First installation waits for configuration; active services restart on upgrade.

The default is http://6.6.6.6/, with no DNS or certificate. This real public IP is used only as an intercepted routing convention. Configure the panel API token and access log, grant restricted log permissions, merge xray-snippet.json into Xray, and route 6.6.6.6/32 through the correct account node in the client. Keep port 8686 on loopback. Complete two-account real deployment validation.

For HTTPS use config.https.example.toml and xray-https-snippet.json with an owned hostname and trusted certificate. Missing server.protocol remains HTTPS for old configurations. HTTP must be explicit. Restore HTTPS configuration and both routes before reverting to v0.3.1.

Optional history stores cumulative query samples, not exact daily bills. Default retention is 30 days with hourly sampling. Cleanup is query-triggered. Disabling history does not delete existing files.

Full guide: https://github.com/youbilin/FlowNote/blob/main/README.md
Deployment details: https://github.com/youbilin/FlowNote/blob/main/docs/DEPLOYMENT.md
