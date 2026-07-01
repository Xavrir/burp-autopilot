# Burp MCP tool catalog

Generated from the live `tools/list` of the installed **"MCP Server"** Burp extension
(`burp-mcp-all.jar`) — 27 tools. This is a snapshot for reference; the authoritative list is
always `burp_client.py list-tools` (re-run it if Burp's extension is updated). Every
`burp_client.py` convenience subcommand resolves to the **Tool** column by exact name, with a
fuzzy fallback for version drift.

## Live requests
| Subcommand | Tool | Key args |
|---|---|---|
| `send-request` | `send_http1_request` | `content` (raw HTTP/1.1), `targetHostname`, `targetPort`, `usesHttps` |
| `send-request-http2` | `send_http2_request` | `headers` (obj), `pseudoHeaders` (obj), `requestBody`, `targetHostname`, `targetPort`, `usesHttps` |

## Repeater / Intruder
| Subcommand | Tool | Key args |
|---|---|---|
| `repeater` | `create_repeater_tab` | `content`, `tabName`, `targetHostname`, `targetPort`, `usesHttps` |
| `repeater-http2` | `create_repeater_tab_http2` | `headers`, `pseudoHeaders`, `requestBody`, `tabName`, `targetHostname`, `targetPort`, `usesHttps` |
| `intruder-send` | `send_to_intruder` | `content`, `tabName`, `targetHostname`, `targetPort`, `usesHttps` |

> `send_to_intruder` only *populates* an Intruder tab; it does not run the attack or return
> results. Programmatic attacks + result harvesting come from the Phase 2 `fuzz` command.

## Collaborator (OOB)
| Subcommand | Tool | Key args |
|---|---|---|
| `collab-generate` | `generate_collaborator_payload` | `customData` (optional) |
| `collab-poll` | `get_collaborator_interactions` | `payloadId` (optional filter) |

## Proxy / WebSocket history (read-only)
| Subcommand | Tool | Key args |
|---|---|---|
| `proxy-history` | `get_proxy_http_history` | `count`, `offset` |
| `proxy-history-regex` | `get_proxy_http_history_regex` | `regex`, `count`, `offset` |
| `websocket-history` | `get_proxy_websocket_history` | `count`, `offset` |
| (use `call`) | `get_proxy_websocket_history_regex` | `regex`, `count`, `offset` |

## Scanner (read-only here)
| Subcommand | Tool | Key args |
|---|---|---|
| `scanner-issues` | `get_scanner_issues` | `count`, `offset` |

> Reading issues works today. There is **no** tool to *launch* an active scan/crawl — that gap
> is filled by the Phase 2 companion extension (`scan-start`) and/or Phase 3 REST API.

## Intercept / task engine / editor
| Subcommand | Tool | Key args |
|---|---|---|
| `intercept` | `set_proxy_intercept_state` | `intercepting` (bool) |
| `task-engine` | `set_task_execution_engine_state` | `running` (bool) |
| `editor-get` | `get_active_editor_contents` | — |
| `editor-set` | `set_active_editor_contents` | `text` |

## Configuration
| Subcommand | Tool | Key args |
|---|---|---|
| `config-export` | `output_project_options` | — |
| `config-export-user` | `output_user_options` | — |
| `config-modify` | `set_project_options` | `json` (string, merged) |
| `config-modify-user` | `set_user_options` | `json` (string, merged) |

> Each subcommand hits exactly one config scope (project vs user). Always export first to learn
> the schema, then merge with the matching modify command.

## Organizer
| Subcommand | Tool | Key args |
|---|---|---|
| `organizer` | `get_organizer_items` | `count`, `offset` |
| (use `call`) | `get_organizer_items_regex` | `regex`, `count`, `offset` |

## Encoders / utilities (no target traffic)
| Subcommand | Tool | Key args |
|---|---|---|
| `url-encode` | `url_encode` | `content` |
| `url-decode` | `url_decode` | `content` |
| `base64-encode` | `base64_encode` | `content` |
| `base64-decode` | `base64_decode` | `content` |
| `random-string` | `generate_random_string` | `length`, `characterSet` |

## Response shape

All tool calls return MCP content envelopes:
```json
{ "content": [ { "type": "text", "text": "..." } ], "isError": false, "_meta": {} }
```
`burp_client.py` truncates long string fields to 1000 chars and caps total output at 50 KB
(override with `--field-cap` / `--total-cap`, or `--raw` to disable — `--raw` can flood context).
For any tool not given a convenience subcommand, use:
```bash
burp_client.py call --tool <exact_name> --args '{"...":"..."}'
```
