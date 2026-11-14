# Contributing to FlowNote

Thanks for helping make traffic self-service easier to use. Chinese and English issues and pull requests are welcome.

## Before proposing a change

Read the [architecture and identity limitations](docs/DESIGN.md). The current scope is a single-server, read-only dashboard. Legacy Cookie authentication, multi-VPS aggregation, and notifications are out of scope. For larger behavior changes, open an issue before investing in implementation.

## Local checks

On Linux, install a Rust toolchain, C build tools, Python 3, and OpenSSL, then run:

```bash
cargo fmt --check
cargo clippy --locked -- -D warnings
cargo test --locked
cargo build --locked
python3 tests/e2e.py target/debug/flownote
```

The integration test starts only local fixture services and creates a temporary test certificate. It does not require a real panel. Keep `Cargo.lock` committed and use `--locked` when validating reproducibility.

For UI work, run `cargo run --locked -- --preview output/preview`, inspect light and dark modes at desktop and mobile widths, and include screenshots using synthetic data. Update the relevant deployment, UI, or architecture document when behavior changes.

## Reporting a bug

Include the FlowNote version, Xray / panel versions, deployment topology, redacted configuration, expected behavior, and minimal reproduction steps. Identify whether a report comes from a real deployment or simulated fixtures. Never attach real tokens, private keys, UUIDs, subscription links, unredacted access logs, or identifiable traffic records.

Use [private security reporting](SECURITY.md) for suspected cross-account exposure or credential leakage.

## Pull requests

Keep changes focused. Explain the user-facing problem, resulting behavior, and validation performed. Add regression tests for meaningful behavioral fixes. Do not broaden identity inference with guessed account fallbacks or weaken certificate verification. By submitting a contribution, you agree that it may be distributed under this project's MIT license.
