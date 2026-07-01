# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-01

Initial public release.

### Added
- **Phase 1 — MCP transport** (`skill/scripts/burp_client.py`): drives Burp's native
  "MCP Server" extension via a stdio↔SSE bridge, with a stdlib-only direct-SSE fallback. Live
  tool resolution (no hardcoded tool names) and built-in output-size discipline. Convenience
  subcommands for live HTTP/1.1 + HTTP/2 requests, proxy/WebSocket history search, Collaborator
  (OOB) generate/poll, scanner-issue reads, intercept toggle, config export/modify, and
  encoders.
- **Phase 2 — companion extension** (`extension/`): a single-file Montoya extension exposing
  loopback `scan-start`, `scan-status`, and a programmatic `fuzz` engine with per-request
  results, scope gating, size caps, and an optional shared-secret token.
- **Phase 3 — REST API** scan path (`rest-scan-start` / `rest-scan-status`).
- **`burp-browser`**: drive a Playwright Chromium through Burp's proxy as an automatable
  replacement for Burp's embedded browser.
- Agent skill packaging (`controlling-burpsuite-autonomously`), `install.sh`, reference docs,
  and full project scaffolding.
