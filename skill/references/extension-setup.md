# Phase 2 companion extension setup (`burp-autopilot-ext.jar`)

Closes the gaps the base "MCP Server" extension lacks: **launching** active audits/crawls,
polling their status, and **scripted fuzzing** with machine-readable results (an
Intruder-equivalent built on the Montoya HTTP API — the GUI Intruder attack engine is not
programmable). It runs a loopback-only HTTP/JSON endpoint that `burp_client.py` calls.

## Build

From the repo's `extension/` directory (see `extension/README.md` for full detail):

```bash
cd extension
./fetch-deps.sh          # one-time: pulls montoya-api + org.json into lib/
./build.sh               # -> extension/build/burp-autopilot-ext.jar
```
Needs `javac` (JDK 21+). No Gradle/Maven. The Montoya API jar
(`lib/montoya-api-2026.4.jar`) is compile-only — Burp provides it at runtime. `org.json` is
shaded into the jar.

## Load into Burp (one-time)

1. Burp Suite Pro → **Extensions** → **Installed** → **Add**.
2. Extension type: **Java**.
3. Select `extension/build/burp-autopilot-ext.jar` (the jar you just built) → **Next**.
4. Output tab should show: `Autopilot: listening on http://127.0.0.1:9877 (no token - loopback only)`.

Verify from the skill:
```bash
python3 {baseDir}/scripts/burp_client.py autopilot-health
```

## Endpoint & client commands

| Client command | Endpoint | Purpose |
|---|---|---|
| `autopilot-health` | `GET /health` | confirm the extension is loaded |
| `scan-start --args '{...}'` | `POST /scan-start` | launch an active audit or crawl |
| `scan-status --task-id <id>` | `GET /scan-status` | poll status (`--task-id all` for every task) |
| `fuzz --args '{...}'` | `POST /fuzz` | scripted attack, returns per-request results |

### scan-start args
```json
{"type": "audit", "urls": ["https://in-scope.example/path"], "requireInScope": true}
```
- `type`: `"audit"` (active audit of the given request URLs) or `"crawl"` (crawl from seed URLs).
- `requireInScope` (default false): when true, URLs outside Burp's configured scope are rejected.
- Read findings afterwards with Phase 1 `scanner-issues`; track progress with `scan-status`.

### fuzz args
```json
{
  "host": "in-scope.example", "port": 443, "https": true,
  "baseRequest": "GET /search?q=§FUZZ§ HTTP/1.1\r\nHost: in-scope.example\r\n\r\n",
  "payloads": ["1", "1'", "1\" OR 1=1--"],
  "placeholder": "§FUZZ§", "maxRequests": 50, "delayMs": 100, "requireInScope": true
}
```
- The placeholder is substituted with each payload; payloads are **not** auto-encoded — encode
  them yourself (use Phase 1 `url-encode`) when the injection context needs it.
- `maxRequests` (default 50) caps **actually-sent** requests (hard ceiling 1000); skipped
  payloads don't consume a slot. `delayMs` rate-limits between sends.
- Results: `{ "sent": N, "results": [ {index, payload, status, length, timeMs}, ... ],
  "skipped": [ {index, reason}, ... ], "truncated": "..." }`. Diff status / length / timing
  across payloads to spot interesting responses; `skipped`/`truncated` appear only when relevant.

## Security

- Binds to `127.0.0.1` only. For defense-in-depth on a shared host, set `BURP_AUTOPILOT_TOKEN`
  in **both** Burp's launch environment and the skill's environment; requests then require the
  `X-Autopilot-Token` header (the client adds it automatically).
- Override the address with `BURP_AUTOPILOT_URL` / `BURP_AUTOPILOT_PORT` if 9877 is taken.
- This endpoint can launch scans and send attack traffic — keep the Scope & safety gate in
  SKILL.md in force: confirm in-scope targets, prefer `requireInScope: true`, rate-limit.
