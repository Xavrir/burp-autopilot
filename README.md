# Burp Autopilot Skill

**Drive Burp Suite from the command line.** It sends live requests, searches proxy history,
runs Collaborator (OOB) checks, launches scans, and scripts fuzzing, each as a plain CLI
subcommand you can chain into a web-security workflow.

It's an on-demand alternative to running an always-on Burp MCP server. Instead of registering a
persistent MCP client, you call one small Python client that talks to Burp only when you need
it. That makes it easy to drop into a script, a CI job, or a coding agent's tool loop.

The repo has two parts:

- `skill/` holds the agent skill (`controlling-burpsuite-autonomously`), its transport client
  `burp_client.py`, and a wrapper that drives a browser through Burp. Load it into
  [Claude Code](https://docs.claude.com/en/docs/claude-code) or an opencode-compatible runner,
  or just call the client as a CLI.
- `extension/` is an optional companion Burp extension (`burp-autopilot-ext`, built on the
  [Montoya API](https://portswigger.github.io/burp-extensions-montoya-api/)). It adds the two
  things the native MCP extension can't do: launching scans, and a scriptable fuzzing engine.

> **Authorized testing only.** Burp sends real traffic to real hosts. Use it only against
> targets you own or are explicitly authorized to test, such as an in-scope bug-bounty or
> pentest engagement. See [SECURITY.md](SECURITY.md) and the safety gate in
> [`skill/SKILL.md`](skill/SKILL.md).

---

## What it can do

| Capability | Backed by |
|---|---|
| Send live HTTP/1.1 & HTTP/2 requests | Native MCP extension (Phase 1) |
| Read / regex-search proxy & WebSocket history | Native MCP extension |
| Generate & poll Burp Collaborator (OOB) payloads | Native MCP extension |
| Read scanner issues, toggle intercept, export/modify config | Native MCP extension |
| Encode/decode (URL, base64) | Native MCP extension |
| Launch active audits & crawls, poll status | Companion extension (Phase 2) |
| Scripted fuzzing with machine-readable per-request results | Companion extension |
| Native REST-API scans that outlive a session | Burp Pro REST API (Phase 3) |
| Browse a target *through* Burp (Playwright) | `burp-browser` + Burp proxy |

## Architecture

Three layers. Only Phase 1 is required; the rest are optional.

```
  your CLI / agent / script
            │
            ▼
   skill/scripts/burp_client.py ────────────────────────────────────────┐
            │                         │                                   │
   (Phase 1)│ stdio↔SSE        (Phase 2)│ loopback HTTP        (Phase 3)  │ REST
            ▼                         ▼                                   ▼
      mcp-proxy.jar            burp-autopilot-ext.jar             Burp Pro REST API
            │  SSE :9876              (Montoya)  :9877                    :1337
            ▼                         ▲                                   ▲
   Burp "MCP Server" ext ────────────┘───────────────────────────────────┘
      (27 live tools)            scan-start / scan-status / fuzz

   burp-browser → Playwright Chromium ──proxy :8080──▶ Burp (history + passive scan)
```

- Phase 1 is the core. `burp_client.py` spawns `mcp-proxy.jar` (a stdio↔SSE bridge) and speaks
  JSON-RPC to Burp's built-in MCP Server extension. Tool names are resolved *live* from the
  extension rather than hardcoded, so the client survives extension updates.
- Phase 2 adds the companion extension for scan launching and fuzzing over a separate loopback
  endpoint.
- Phase 3 wires Burp's native REST API as an alternative scan path.

For the full design and where it stops, see [`docs/architecture.md`](docs/architecture.md).

## Prerequisites

- Burp Suite with the built-in "MCP Server" extension enabled (Settings, then turn on the MCP
  server; loopback SSE `127.0.0.1:9876`). Community or Pro both work, but read the
  [edition matrix](#burp-edition-community-vs-pro) first: Community covers the request, proxy,
  and encoder features plus Playwright-through-Burp, while scanning, Collaborator (OOB), and the
  REST API need Pro.
- `mcp-proxy.jar`, a stdio↔SSE bridge for the MCP endpoint. You supply this yourself (see
  [Obtaining mcp-proxy.jar](#obtaining-mcp-proxyjar)) and point the client at it with
  `BURP_MCP_PROXY_JAR`.
- Java 17+. Building the companion extension needs JDK 21.
- Python 3.8+. The client uses the standard library only, so there is nothing to `pip install`.
- Optional, only for `burp-browser`:
  [`playwright-cli`](https://github.com/microsoft/playwright) and
  `playwright-cli install-browser chromium`.

## Install

### Quickest: npx

Drop the skill into your harness's skills folder with one command. This runs straight from
GitHub, so there's nothing to clone or publish:

```bash
npx github:Xavrir/burp-autopilot
```

It copies the skill into `~/.claude/skills/controlling-burpsuite-autonomously`. Options:

```bash
npx github:Xavrir/burp-autopilot --dir ~/.config/opencode/skill   # a different skills folder
npx github:Xavrir/burp-autopilot --force                          # overwrite an existing install
SKILLS_DIR=/some/where npx github:Xavrir/burp-autopilot           # or set the folder via env
```

The installer only handles the skill (the Python client and references). The companion
extension needs a Java build and a manual load into Burp, covered below.

### Or paste a prompt into your agent

If you'd rather let your CLI agent do it, paste this in:

```text
Install the Burp Autopilot skill for me. Run:

    npx github:Xavrir/burp-autopilot

That copies the skill into ~/.claude/skills/controlling-burpsuite-autonomously. If npx or Node
isn't available, instead: clone https://github.com/Xavrir/burp-autopilot and copy its skill/
directory to ~/.claude/skills/controlling-burpsuite-autonomously (the folder name must stay
exactly that). Then confirm SKILL.md is in place. Do not send any live Burp traffic until I
give you an authorized, in-scope target.
```

### Manual

```bash
git clone https://github.com/Xavrir/burp-autopilot.git
cd burp-autopilot
./install.sh          # symlinks skill/ -> ~/.claude/skills/controlling-burpsuite-autonomously
```

Or skip installing entirely and run the client from the clone:

```bash
python3 skill/scripts/burp_client.py ping
```

### Companion extension (optional, for scans + fuzzing)

```bash
cd extension
./fetch-deps.sh       # one-time: pulls Montoya API + org.json from Maven Central into lib/
./build.sh            # -> extension/build/burp-autopilot-ext.jar
```

Then in Burp, go to **Extensions ▸ Installed ▸ Add ▸ Java** and select
`extension/build/burp-autopilot-ext.jar`. See [`extension/README.md`](extension/README.md).

## Quickstart

```bash
C="python3 skill/scripts/burp_client.py"

# 1. Preflight: is Burp up with the MCP Server extension?
$C ping

# 2. Discover the live tool surface (source of truth; never hardcode tool names)
$C list-tools

# 3. Send a live request through Burp (authorized target only)
$C send-request --args '{"content":"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n","targetHostname":"example.com","targetPort":443,"usesHttps":true}'

# 4. Regex-search what Burp has captured
$C proxy-history-regex --args '{"regex":"api/v1","count":50}'
```

With the companion extension loaded:

```bash
$C autopilot-health
$C scan-start  --args '{"type":"audit","urls":["https://in-scope.example/path"],"requireInScope":true}'
$C scan-status --task-id all
```

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `BURP_MCP_PROXY_JAR` | `~/mcp-proxy.jar` | Path to the stdio↔SSE bridge jar |
| `BURP_MCP_SSE_URL` | `http://127.0.0.1:9876` | Burp MCP Server SSE endpoint |
| `BURP_MCP_JAVA` | `/usr/bin/java` | Java binary used to run the bridge |
| `BURP_AUTOPILOT_URL` / `_PORT` | `http://127.0.0.1:9877` | Companion extension endpoint |
| `BURP_AUTOPILOT_TOKEN` | *(unset)* | Optional `X-Autopilot-Token` shared secret |
| `BURP_REST_URL` / `BURP_REST_KEY` | `http://127.0.0.1:1337` | Burp Pro REST API (Phase 3) |
| `BURP_PROXY` | `http://127.0.0.1:8080` | Proxy listener used by `burp-browser` |

## Burp edition: Community vs Pro

Burp Autopilot runs against whatever your edition of Burp exposes. Most of the transport and
request-level features work on Community. The scanning layer needs Pro, because those engines
don't ship in Community at all.

| Feature | Community | Pro |
|---|:---:|:---:|
| `send-request` / `send-request-http2`, Repeater staging | Yes | Yes |
| Proxy / WebSocket history + regex search | Yes | Yes |
| Intercept toggle, encoders, config export/modify | Yes | Yes |
| `burp-browser` (Playwright through the proxy) | Yes | Yes |
| Scripted `fuzz` (companion extension, sends via HTTP API) | Yes¹ | Yes |
| Active/passive scanner (`scan-start`, `scan-status`, `scanner-issues`) | No | Yes |
| Burp Collaborator / OOB (`collab-generate`, `collab-poll`) | No | Yes |
| REST API scans (`rest-scan-start`, `rest-scan-status`) | No | Yes |
| Native Intruder attack engine | Throttled | Yes |

¹ The companion `fuzz` engine sends requests through the Montoya HTTP API, so Community's
Intruder time-throttle doesn't apply to it. Keep payload sets small and set `delayMs` anyway.

> One thing worth checking in your own setup: the native "MCP Server" extension (the Phase 1
> transport) has to load in your edition. If `ping` fails on Community, that extension is the
> blocker, not this tool.

## Obtaining `mcp-proxy.jar`

`mcp-proxy.jar` is a generic stdio↔SSE MCP bridge, and it isn't shipped in this repo. Build or
download your own, put it anywhere, and point `BURP_MCP_PROXY_JAR` at it. If you don't configure
a bridge jar, `burp_client.py` falls back to talking to the Burp SSE endpoint directly with the
Python standard library.

## Limits

What you can automate is whatever the Montoya and REST APIs expose. A few things stay out of
reach for any tool: DOM Invader, the embedded Chromium browser, BApp and extension management,
and GUI-only dialogs. The GUI Intruder attack engine isn't fully scriptable either, which is why
the companion extension rebuilds fuzzing on top of the HTTP API. So "autonomous" here means the
whole Montoya plus REST surface, not literally every click in the GUI.

## Contributing

Issues and PRs are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). The companion extension links against third-party libraries listed in
[`extension/THIRD_PARTY_NOTICES.md`](extension/THIRD_PARTY_NOTICES.md).
