# Burp Autopilot

**Drive Burp Suite autonomously from the command line** — send live requests, search
proxy history, run Collaborator (OOB) checks, launch scans, and script fuzzing, all as
deterministic CLI subcommands you can chain into automated web-security workflows.

Burp Autopilot is an **on-demand alternative to an always-on Burp MCP server**. Instead of
registering a persistent MCP client, you invoke one small Python client that speaks to Burp
only when you need it — which makes it easy to compose into scripts, CI, or an AI coding
agent's tool loop.

It ships as two parts in one repo:

- **`skill/`** — an agent skill (`controlling-burpsuite-autonomously`) plus its transport
  client `burp_client.py` and a Playwright-through-Burp browser wrapper. Loadable by
  [Claude Code](https://docs.claude.com/en/docs/claude-code) / opencode-compatible skill
  runners, or usable as a plain CLI.
- **`extension/`** — an optional companion Burp extension (`burp-autopilot-ext`, built on the
  [Montoya API](https://portswigger.github.io/burp-extensions-montoya-api/)) that adds the two
  things the native MCP extension can't do: **launching scans** and a **programmatic fuzzing
  engine**.

> ⚠️ **Authorized testing only.** Burp sends real traffic to real hosts. Use this exclusively
> against targets you own or are explicitly authorized to test (e.g. an in-scope bug-bounty or
> pentest engagement). See [SECURITY.md](SECURITY.md) and the safety gate in
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
| **Launch active audits & crawls, poll status** | Companion extension (Phase 2) |
| **Scripted fuzzing with machine-readable per-request results** | Companion extension |
| Native REST-API scans that outlive a session | Burp Pro REST API (Phase 3) |
| Browse a target *through* Burp (Playwright) | `burp-browser` + Burp proxy |

## Architecture

Three layers, each optional beyond Phase 1:

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

- **Phase 1** is the core: `burp_client.py` spawns `mcp-proxy.jar` (a stdio↔SSE bridge) and
  speaks JSON-RPC to Burp's built-in **MCP Server** extension. Tool names are resolved *live*
  from the extension, never hardcoded.
- **Phase 2** adds the companion extension for scan launching and fuzzing over a separate
  loopback endpoint.
- **Phase 3** wires Burp's native REST API as an alternative scan path.

See [`docs/architecture.md`](docs/architecture.md) for the full design and its honest ceiling.

## Prerequisites

- **Burp Suite** with the built-in **"MCP Server"** extension enabled (Settings ▸ enable the
  MCP server; loopback SSE `127.0.0.1:9876`). **Community or Pro** — but note the
  [edition matrix](#burp-edition-community-vs-pro) below: Community covers request/proxy/encoder
  features and Playwright-through-Burp, while **scanning, Collaborator (OOB), and the REST API
  are Pro-only**.
- **`mcp-proxy.jar`** — a stdio↔SSE bridge for the MCP endpoint (user-supplied; see
  [Obtaining mcp-proxy.jar](#obtaining-mcp-proxyjar)). Point the client at it with
  `BURP_MCP_PROXY_JAR`.
- **Java 17+** (JDK 21 recommended — required to *build* the companion extension).
- **Python 3.8+** — standard library only, no `pip install` needed.
- *(Optional, for `burp-browser`)* [`playwright-cli`](https://github.com/microsoft/playwright)
  and `playwright-cli install-browser chromium`.

## Install

```bash
git clone https://github.com/Xavrir/burp-autopilot.git
cd burp-autopilot
```

### As a CLI

No install step — run the client directly:

```bash
python3 skill/scripts/burp_client.py ping
```

### As an agent skill

Symlink the `skill/` directory into your skills folder (the link name **must** match the
skill's `name:` frontmatter):

```bash
./install.sh          # links skill/ -> ~/.claude/skills/controlling-burpsuite-autonomously
```

### Companion extension (optional, for scans + fuzzing)

```bash
cd extension
./fetch-deps.sh       # one-time: pulls Montoya API + org.json from Maven Central into lib/
./build.sh            # -> extension/build/burp-autopilot-ext.jar
```

Then in Burp: **Extensions ▸ Installed ▸ Add ▸ Java**, select
`extension/build/burp-autopilot-ext.jar`. See [`extension/README.md`](extension/README.md).

## Quickstart

```bash
C="python3 skill/scripts/burp_client.py"

# 1. Preflight — is Burp up with the MCP Server extension?
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

Burp Autopilot runs against whatever your Burp edition exposes. Most transport and
request-level features work on **Community**; the value-add layer is **Pro-gated** because
those engines don't ship in Community.

| Feature | Community | Pro |
|---|:---:|:---:|
| `send-request` / `send-request-http2`, Repeater staging | ✅ | ✅ |
| Proxy / WebSocket history + regex search | ✅ | ✅ |
| Intercept toggle, encoders, config export/modify | ✅ | ✅ |
| `burp-browser` (Playwright through the proxy) | ✅ | ✅ |
| Scripted `fuzz` (companion extension, sends via HTTP API) | ✅¹ | ✅ |
| **Active/passive Scanner** — `scan-start`, `scan-status`, `scanner-issues` | ❌ | ✅ |
| **Burp Collaborator (OOB)** — `collab-generate`, `collab-poll` | ❌ | ✅ |
| **REST API scans** — `rest-scan-start`, `rest-scan-status` | ❌ | ✅ |
| Native **Intruder** attack engine | ⏳ throttled | ✅ |

¹ The companion `fuzz` engine issues requests via the Montoya HTTP API, so it is **not** subject
to Community's Intruder time-throttle. Keep payload sets small and set `delayMs` regardless.

> One caveat worth verifying in your setup: the native **"MCP Server" extension** (the Phase 1
> transport) must load in your edition. If `ping` fails on Community, that extension — not this
> tool — is the blocker.

## Obtaining `mcp-proxy.jar`

`mcp-proxy.jar` is a generic stdio↔SSE MCP bridge and is **not** redistributed here. Provide
your own build/download, place it anywhere, and point `BURP_MCP_PROXY_JAR` at it. As a
fallback, `burp_client.py` can also talk to the Burp SSE endpoint directly over the Python
standard library when no bridge jar is configured.

## Limits (in the interest of honesty)

Programmatic control is bounded by Burp's Montoya + REST surfaces. **Unreachable by any tool:**
DOM Invader, the embedded Chromium browser, BApp/extension management, and GUI-only dialogs.
The GUI Intruder attack engine is not fully programmable — the companion extension reimplements
attacks via the HTTP API instead. "Autonomous" means the full Montoya + REST surface, not
literally every GUI click.

## Contributing

Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). The companion extension links against third-party libraries listed in
[`extension/THIRD_PARTY_NOTICES.md`](extension/THIRD_PARTY_NOTICES.md).
