# burp-autopilot-ext (companion extension)

A single-file [Montoya](https://portswigger.github.io/burp-extensions-montoya-api/) extension
that adds the capabilities the native "MCP Server" extension lacks: **launching** active
audits/crawls, polling their status, and **scripted fuzzing** with machine-readable results
(an Intruder-equivalent built on the Montoya HTTP API — the GUI Intruder engine is not
programmable).

It runs a **loopback-only** HTTP/JSON server that `burp_client.py` calls.

## Build

Requires **JDK 21+** (`javac`). No Gradle/Maven.

```bash
./fetch-deps.sh    # one-time: pull montoya-api + org.json from Maven Central into lib/
./build.sh         # -> build/burp-autopilot-ext.jar
```

`montoya-api` is compile-only (Burp provides it at runtime); `org.json` is shaded into the jar.
See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Load into Burp (one-time)

1. Burp Suite → **Extensions** → **Installed** → **Add**.
2. Extension type: **Java**.
3. Select `build/burp-autopilot-ext.jar` → **Next**.
4. The Output tab should show:
   `Autopilot: listening on http://127.0.0.1:9877 (no token - loopback only)`.

Verify from the client:

```bash
python3 ../skills/controlling-burpsuite-autonomously/scripts/burp_client.py autopilot-health
```

> Scanning (`scan-start` / `scan-status`) requires **Burp Suite Pro** — Community has no
> Scanner. The `fuzz` endpoint works on both editions.

## Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | liveness + active task count |
| `/scan-start` | POST | launch an active audit or crawl |
| `/scan-status` | GET | poll one task (`?taskId=`) or all |
| `/fuzz` | POST | scripted attack; per-request results |

### `/fuzz` request shape

```json
{
  "host": "in-scope.example", "port": 443, "https": true,
  "baseRequest": "GET /search?q=§FUZZ§ HTTP/1.1\r\nHost: in-scope.example\r\n\r\n",
  "payloads": ["1", "1'", "1\" OR 1=1--"],
  "placeholder": "§FUZZ§", "maxRequests": 50, "delayMs": 100, "requireInScope": true
}
```

Payloads are **not** auto-encoded — encode them yourself when the injection context needs it.
`maxRequests` caps actually-sent requests (hard ceiling 1000); `delayMs` rate-limits between
sends. Results: `{ "sent": N, "results": [{index, payload, status, length, timeMs}, ...],
"skipped": [...], "truncated": "..." }`.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `BURP_AUTOPILOT_PORT` | `9877` | Listener port |
| `BURP_AUTOPILOT_TOKEN` | *(unset)* | Require `X-Autopilot-Token` on every request |
| `MONTOYA_VERSION` / `JSON_VERSION` | `2026.4` / `20250517` | Dependency versions for `fetch-deps.sh` |
| `MONTOYA_JAR` / `JSON_JAR` | `lib/…` | Override jar paths for `build.sh` |

## Security

Binds to `127.0.0.1` only. This endpoint can launch scans and send attack traffic — keep the
scope/safety gate in force: confirm in-scope targets, prefer `requireInScope: true`, and
rate-limit. For defense-in-depth on a shared host, set `BURP_AUTOPILOT_TOKEN` in **both** Burp's
launch environment and the client's environment.
