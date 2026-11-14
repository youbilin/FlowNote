# Security policy

FlowNote v0.3 is early software. The current 0.3 code is the only maintained line; there is no guaranteed response time or support SLA.

## Report privately

Use GitHub's **Security → Report a vulnerability** for this repository:

https://github.com/youbilin/FlowNote/security/advisories/new

Do not open a public issue with exploitation details or real user data. Include the affected version, topology, reproduction steps using synthetic accounts, and likely impact. Remove tokens, private keys, UUIDs, subscription links, and identifiable access logs before sharing any evidence.

## Deployment boundary

- FlowNote trusts the host running Xray and the correctness of its access logs and PROXY source metadata.
- Source-to-account correlation is topology-dependent. Mux, CDN frontends, and accounts sharing underlying connections are unsupported.
- Observed conflicts fail closed, but delayed log entries can leave conflicts unobserved. Two-account real deployment validation is required; local simulated tests do not prove isolation for every deployment.
- Keep the listener on loopback. Do not expose it through port forwarding or a conventional reverse proxy. Untrusted local processes can forge PROXY metadata.
- Use a dedicated service user, restricted log/token/key permissions, a valid certificate, and the smallest usable panel API scope.
- HTTPS protects transmission. It does not establish that a log-based account association is correct.

See [the design document](docs/DESIGN.md) and [deployment acceptance checks](docs/DEPLOYMENT.md) for the complete operational assumptions.

## Release installation and query history

Install only from the project's tagged GitHub Releases. The installer uses HTTPS, validates SHA-256, rejects unexpected archive paths and links, and checks the binary version. The manifest shares the release channel and does not provide independent signature verification. Review the installer before running it with root privileges. Existing configurations and secrets are preserved; a first installation does not start with placeholder credentials.

Optional history stores per-account cumulative query samples under `/var/lib/flownote/history` with restrictive permissions. SHA-256 account filenames are pseudonymous identifiers, not encryption. Protect backups as user data. Retention and capacity are bounded, with cleanup triggered by queries rather than a background scheduler; files can remain while idle. Disable history and remove the state directory to erase records. History failures do not prevent current traffic queries. Identity-association limitations also apply to history: enabling persistence does not improve account authentication.
