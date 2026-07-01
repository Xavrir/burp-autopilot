# Architecture

Burp Autopilot layers three independent transports on top of Burp Suite, coordinated by a
single Python client (`skills/controlling-burpsuite-autonomously/scripts/burp_client.py`). Each
phase is optional beyond Phase 1, and each targets a different Burp capability.

```
  your CLI / agent / script
            │
            ▼
   burp_client.py
    │            │             │
    │ Phase 1    │ Phase 2     │ Phase 3
    │ stdio↔SSE  │ HTTP JSON   │ REST
    ▼            ▼             ▼
 mcp-proxy.jar   burp-autopilot-ext.jar   Burp Pro REST API
   SSE :9876       (Montoya) :9877            :1337
    │               ▲                          ▲
    ▼               │                          │
 Burp "MCP Server" extension  ────────────────-┘
    (27 live tools)   scan-start / scan-status / fuzz
```

## Phase 1 — MCP transport (core)

`burp_client.py` spawns `mcp-proxy.jar`, a generic **stdio↔SSE bridge**, and speaks
JSON-RPC 2.0 (MCP) to Burp's built-in **"MCP Server"** extension over loopback SSE
(`127.0.0.1:9876`). A stdlib-only direct-SSE fallback exists when no bridge jar is configured.

Key design decision: **tool names are resolved live** from the extension's `tools/list` rather
than hardcoded. The convenience subcommands (`send-request`, `proxy-history-regex`,
`collab-generate`, …) fuzzy-match against that live catalog, so the client survives extension
updates that rename or add tools. `references/tool-catalog.md` is only a snapshot.

Output discipline is enforced here: long string fields are truncated (1000 chars) and total
output is capped (50 KB) to protect an agent's context window. Narrow big reads with regex +
`count`/`offset` instead of dumping raw.

## Phase 2 — companion extension (scans + fuzzing)

The native MCP extension can *read* scanner issues but cannot *launch* scans, and has no
programmatic attack engine. `extension/` is a single-file **Montoya** extension that runs a
loopback-only HTTP/JSON server (`127.0.0.1:9877`) exposing:

- `POST /scan-start` — launch an active audit or crawl (optionally scope-gated)
- `GET  /scan-status` — poll one task or all
- `POST /fuzz` — an Intruder-equivalent that substitutes a placeholder with each payload and
  returns per-request `{index, payload, status, length, timeMs}`

Safety is built into the extension, not just the client: loopback-only bind, an optional
`X-Autopilot-Token` shared secret, request-body size caps, a per-payload size cap, a hard
ceiling of 1000 requests per fuzz run, and an optional `requireInScope` gate checked against
Burp's configured scope.

Because `fuzz` sends via the Montoya HTTP API rather than the GUI Intruder engine, it is not
subject to Burp Community's Intruder time-throttle — but you should still keep payload sets
small and set `delayMs`.

## Phase 3 — Burp Pro REST API

An alternative scan path using Burp Pro's native REST service (`127.0.0.1:1337` by default):
`rest-scan-start` / `rest-scan-status`. Useful when you want a native scan task that outlives
the session. It does not cover Repeater/Intruder/Collaborator/proxy control — those stay on
Phase 1.

## `burp-browser` — Playwright as the Burp browser

Burp's embedded Chromium cannot be automated. The skill's `scripts/burp-browser` instead drives a
**Playwright Chromium through Burp's proxy** (`127.0.0.1:8080`), so every request lands in
Burp's proxy history and passive scan. This unlocks the full loop:
**browse → Burp captures → triage (`proxy-history`/`scanner-issues`) → `scan-start` → `fuzz`.**

## Edition gating

Phase-1 request/proxy/encoder tools and `burp-browser` work on **Burp Community**. Scanning,
Collaborator (OOB), and the REST API are **Pro-only** engines — see the edition matrix in the
[README](../README.md#burp-edition-community-vs-pro).

## The honest ceiling

Programmatic control is bounded by Burp's Montoya + REST surfaces. **Unreachable by any tool:**
DOM Invader, the embedded Chromium browser, BApp/extension management, and GUI-only dialogs.
The GUI Intruder attack engine is not fully programmable — Phase 2 reimplements attacks via the
HTTP API instead. "Autonomous" means the full Montoya + REST surface, not literally every GUI
click.
