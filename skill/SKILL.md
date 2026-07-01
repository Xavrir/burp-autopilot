---
name: controlling-burpsuite-autonomously
description: Drive Burp Suite Pro autonomously from the command line instead of the Burp MCP server - send live HTTP/1.1+HTTP/2 requests, read/regex-search proxy & WebSocket history, create Repeater/Intruder tabs, generate and poll Burp Collaborator (OOB) payloads, read scanner issues, toggle proxy intercept, export/modify config, and chain these into multi-step testing workflows. Use when the user wants to send a request through Burp, search Burp proxy history, run Collaborator/OOB checks, fuzz a parameter via Burp, scan with Burp, or otherwise control Burp from the agent during authorized security testing.
version: 0.1.0
license: MIT
author: Rizky Mirzaviandy Priambodo
homepage: https://github.com/Xavrir/burp-autopilot
compatibility: claude-code opencode
tags:
  - burp-suite
  - security
  - pentest
  - web-security
  - automation
  - mcp
allowed-tools: Bash, Read
---

# Controlling Burp Suite autonomously

Drive Burp Suite Pro through the bundled `scripts/burp_client.py`, which speaks MCP (JSON-RPC)
to Burp's "MCP Server" extension. This replaces the always-on `burp` MCP server with an
on-demand, scriptable interface you can chain into autonomous workflows.

## Scope & safety — read first (this is authorized-testing tooling)

Burp sends real traffic to real targets. Before ANY live action (`send-request`,
`repeater`, `intruder-send`, `collab-*`, `fuzz`, scan):

1. **Confirm an explicit, in-scope target.** Never fire at a host the user has not named as
   in-scope for the current engagement. If scope is unclear, ask.
2. **Honor the program rules.** The user runs bug-bounty engagements (e.g. gojek-bbp, and per
   memory PlanetHoster / Agoda) — respect each program's accepted-risk rules, rate limits, and
   excluded paths.
3. **No destructive or DoS-style automation by default** — no high-volume fuzzing, no
   account/data mutation, no auth/MFA brute force unless the user explicitly authorizes it for
   a specific in-scope target.
4. **Rate-limit fuzzing** and prefer the smallest payload set that proves the point.
5. **Encoders, history reads, config export, and `list-tools` are safe** (no target traffic).

If a requested action targets an out-of-scope host, refuse and explain.

## Preflight (always run first)

```bash
python3 {baseDir}/scripts/burp_client.py ping
```
`{"ok": true, ...}` means Burp Pro is running with the MCP Server extension enabled. If
`ok:false`: start Burp Suite Pro, ensure the "MCP Server" extension is loaded/enabled (loopback
SSE `127.0.0.1:9876`), then retry. Override defaults with env vars `BURP_MCP_SSE_URL`,
`BURP_MCP_PROXY_JAR`, `BURP_MCP_JAVA` (same as `~/.local/bin/burp-mcp-proxy`).

## Discover the live tool surface

The installed extension is the source of truth — never hardcode tool names:
```bash
python3 {baseDir}/scripts/burp_client.py list-tools
```
See `references/tool-catalog.md` for a snapshot of the current 27 tools and their args.

## Intent → command

Run everything as `python3 {baseDir}/scripts/burp_client.py <subcommand> --args '<json>'`.
Arguments are the tool's own schema (see `list-tools` / the catalog).

| Goal | Command |
|---|---|
| Send a live HTTP/1.1 request | `send-request --args '{"content":"GET /x HTTP/1.1\r\nHost: t\r\n\r\n","targetHostname":"t","targetPort":443,"usesHttps":true}'` |
| Send HTTP/2 | `send-request-http2 --args '{"pseudoHeaders":{":method":"GET",":path":"/x"},"headers":{"host":"t"},"targetHostname":"t","targetPort":443,"usesHttps":true}'` |
| Stage in Repeater | `repeater` / `repeater-http2` |
| Stage in Intruder | `intruder-send` (populates tab only — for real attacks use Phase 2 `fuzz`) |
| Search proxy history | `proxy-history-regex --args '{"regex":"api/v1","count":50}'` |
| WebSocket history | `websocket-history --args '{"count":50}'` |
| Read scanner issues | `scanner-issues --args '{"count":50,"offset":0}'` |
| Generate OOB payload | `collab-generate` → use the returned URL in a request |
| Poll OOB hits | `collab-poll --args '{"payloadId":"<id>"}'` |
| Toggle intercept | `intercept --args '{"intercepting":false}'` |
| Pause/resume tasks | `task-engine --args '{"running":false}'` |
| Export project config (learn schema first) | `config-export` (user-level: `config-export-user`) |
| Modify project config (merge) | `config-modify --args '{"json":"{...}"}'` (user-level: `config-modify-user`) |
| Encode/decode | `url-encode` / `url-decode` / `base64-encode` / `base64-decode` |
| Any other tool | `call --tool <exact_name> --args '<json>'` |

## Output discipline

`burp_client.py` truncates long string fields (1000 chars) and caps output at 50 KB to protect
context. For big reads, narrow with regex + `count`/`offset` rather than `--raw`. Only use
`--raw` for a single small record you must see verbatim.

## Autonomous workflow recipes

Chain commands; check each result before the next step. Always start with the Scope & safety
gate and `ping`.

**OOB / SSRF check on an in-scope endpoint**
1. `collab-generate` → capture the payload URL + `payloadId`.
2. `send-request` with the payload injected into the target parameter.
3. Wait briefly, then `collab-poll --args '{"payloadId":"<id>"}'`.
4. Interactions present → likely OOB/SSRF; capture evidence and report.

**Triage what Burp already found**
1. `scanner-issues` → list issues (severity/confidence).
2. For promising issues, `proxy-history-regex` on the affected path to pull the raw exchange.
3. Validate manually with `send-request`/`repeater` before reporting — Burp findings are
   indicators, not proof.

**Recon a captured app**
1. `proxy-history-regex --args '{"regex":"<host>","count":100}'` to map endpoints.
2. Pull params of interest, then probe individually with `send-request`.
3. For OOB-prone params, run the SSRF recipe above.

## Launching scans & scripted fuzzing (companion extension)

The base extension can *read* scanner issues but cannot *launch* scans, and has no programmatic
attack engine. The Phase 2 companion extension (`burp-autopilot-ext.jar`) adds these over a
separate loopback endpoint. Load it once per `references/extension-setup.md`, then:

| Goal | Command |
|---|---|
| Confirm it's loaded | `autopilot-health` |
| Launch an active audit | `scan-start --args '{"type":"audit","urls":["https://in-scope/path"],"requireInScope":true}'` |
| Launch a crawl | `scan-start --args '{"type":"crawl","urls":["https://in-scope/"]}'` |
| Poll a scan | `scan-status --task-id <id>` (or `--task-id all`) |
| Read findings | `scanner-issues` (Phase 1) once the scan progresses |
| Scripted fuzz w/ results | `fuzz --args '{"host":"in-scope","port":443,"https":true,"baseRequest":"GET /q=§FUZZ§ HTTP/1.1\r\nHost: in-scope\r\n\r\n","payloads":["a","b"],"requireInScope":true}'` |

`fuzz` does not auto-encode payloads — `url-encode` them first when the context needs it. Honor
the Scope & safety gate: prefer `requireInScope:true`, set `delayMs`, keep payload sets small.

For automated scans that should outlive a session, Phase 3 wires Burp's REST API — see
`references/rest-api.md` when present.

## Autonomous browsing through Burp (`burp-browser`)

Burp's embedded browser can't be automated, but `scripts/burp-browser` drives a Playwright
Chromium **through Burp's proxy** — same effect: traffic flows into Burp's history and passive
scan, and you can screenshot the page. Full guide in `references/browser-usage.md`.

```bash
B={baseDir}/scripts/burp-browser
$B open https://authorized-target/      # routes through Burp (proxy 8080, ignores MITM cert)
$B snapshot ; $B click e5 ; $B fill e3 "x" ; $B screenshot --filename=p.png ; $B close
```
One-time setup: `playwright-cli install-browser chromium`. Then triage what Burp captured with
`proxy-history-regex` / `scanner-issues`. This unlocks the full loop: **browse → Burp captures →
triage → scan-start → fuzz** — only browse/attack authorized targets.

## Offline analysis (Burp not running)

To search a saved `.burp` project file without a live session, use the existing
`burpsuite-project-parser` skill (it drives `burpsuite_pro.jar` headless). That skill enforces
the same output-size discipline and covers `auditItems`, proxy/site-map sub-component filters,
and regex body/header search.

## Limits (be honest with the user)

Programmatic control is bounded by Burp's Montoya API + REST API. Unreachable by any tool:
**DOM Invader, the embedded Chromium browser, BApp/extension management, and GUI-only dialogs.**
"Everything" means the full Montoya + REST surface, not literally every GUI click. The GUI
Intruder attack engine is not fully programmable — Phase 2 reimplements attacks via the HTTP API
instead.
