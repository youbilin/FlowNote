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
