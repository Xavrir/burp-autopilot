# Phase 3 — Burp Pro REST API (complementary scan path)

Burp Suite Pro ships a built-in REST API that can launch and monitor automated scans. It is an
alternative to the Phase 2 companion extension for scanning — useful when you prefer Burp's
native scan task or want scans that outlive the session. It does **not** cover Repeater/Intruder/
Collaborator/proxy control (those stay on Phase 1).

## Enable it in Burp (one-time)

1. Burp → **Settings** → **Suite** → **REST API**.
2. Tick **Service running**. Default bind: `127.0.0.1:1337`.
3. (Recommended) create an **API key**. With a key, requests are prefixed by the key in the path.
4. Note the base URL Burp shows, e.g. `http://127.0.0.1:1337/`.

> The REST service and the MCP Server extension are different things that may both mention 1337.
> Confirm the actual REST address/port in the REST API settings panel before relying on it.

## Configure the skill

```bash
export BURP_REST_URL="http://127.0.0.1:1337"   # base, no trailing slash
export BURP_REST_KEY="<api-key-or-empty>"        # omit if no key configured
```
The client builds paths as `${BURP_REST_URL}/${BURP_REST_KEY}/v0.1/...` (the key segment is
dropped when empty).

## Client commands (added in Phase 3)

| Command | REST call | Purpose |
|---|---|---|
| `rest-scan-start --args '{"urls":["https://in-scope/"]}'` | `POST /v0.1/scan` | start a scan; returns the task id |
| `rest-scan-status --task-id <id>` | `GET /v0.1/scan/<id>` | scan progress + issue summary |

`POST /v0.1/scan` accepts a JSON body — minimally `{"urls": ["..."]}`, and optionally
`scan_configurations`, `application_logins`, `scope`, etc. (see Burp's REST API docs page linked
from the settings panel). On success Burp returns `201` with the new task id in the `Location`
header; the client surfaces that id for `rest-scan-status`.

## Verify

```bash
python3 {baseDir}/scripts/burp_client.py rest-scan-start --args '{"urls":["http://localhost:PORT/"]}'
python3 {baseDir}/scripts/burp_client.py rest-scan-status --task-id <id>
```
Use a deliberately vulnerable local lab target you are authorized to scan. Keep the Scope & safety
gate in force — REST scans send active attack traffic.
