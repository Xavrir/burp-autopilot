#!/usr/bin/env python3
"""burp_client.py - drive Burp Suite from the command line via the Burp MCP extension.

This is the transport layer for the `controlling-burpsuite-autonomously` skill. It speaks
the Model Context Protocol (JSON-RPC 2.0) to the Burp "MCP Server" extension, so an agent can
control Burp without registering an always-on MCP client.

Primary transport: spawn the existing `mcp-proxy.jar` stdio<->SSE bridge and talk JSON-RPC
over its stdin/stdout (the same bridge `~/.local/bin/burp-mcp-proxy` uses).
Fallback transport: connect directly to the Burp SSE endpoint with the Python stdlib.

The installed extension's tool set is the source of truth: `list-tools` queries it live and
the convenience subcommands resolve their tool name by fuzzy-matching that list, so nothing
is hardcoded to a brittle name.

Requires Burp Suite Pro running with the "MCP Server" extension enabled (loopback SSE on
127.0.0.1:9876 by default). Nothing here needs network access beyond that loopback.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, List, Optional

# --- configuration (mirrors ~/.local/bin/burp-mcp-proxy) ----------------------------------

JAVA_BIN = os.environ.get("BURP_MCP_JAVA", "/usr/bin/java")
PROXY_JAR = os.environ.get("BURP_MCP_PROXY_JAR", os.path.expanduser("~/mcp-proxy.jar"))
SSE_URL = os.environ.get("BURP_MCP_SSE_URL", "http://127.0.0.1:9876").rstrip("/")

PROTOCOL_VERSION = os.environ.get("BURP_MCP_PROTOCOL", "2024-11-05")
CLIENT_INFO = {"name": "burp-autopilot-client", "version": "0.1.0"}

# Phase 2 companion extension (burp-autopilot-ext.jar) loopback HTTP endpoint
AUTOPILOT_URL = os.environ.get("BURP_AUTOPILOT_URL", "http://127.0.0.1:9877").rstrip("/")
AUTOPILOT_TOKEN = os.environ.get("BURP_AUTOPILOT_TOKEN")
AUTOPILOT_TIMEOUT = float(os.environ.get("BURP_AUTOPILOT_TIMEOUT", "300"))

# Phase 3 Burp Pro built-in REST API (scan launch/monitor)
BURP_REST_URL = os.environ.get("BURP_REST_URL", "http://127.0.0.1:1337").rstrip("/")
BURP_REST_KEY = os.environ.get("BURP_REST_KEY", "")

# output-size discipline, mirroring burpsuite-project-parser/scripts/burp-search.sh
DEFAULT_FIELD_CAP = 1000          # max chars for any single string field
DEFAULT_TOTAL_CAP = 50_000        # max bytes emitted to stdout for a result
HANDSHAKE_TIMEOUT = float(os.environ.get("BURP_MCP_HANDSHAKE_TIMEOUT", "30"))
CALL_TIMEOUT = float(os.environ.get("BURP_MCP_CALL_TIMEOUT", "120"))


class BurpError(RuntimeError):
    """A user-facing error with a remediation hint."""


# --- JSON-RPC over the mcp-proxy stdio bridge ---------------------------------------------


class ProxyStdioClient:
    """Launch mcp-proxy.jar and speak newline-delimited JSON-RPC over its stdio."""

    def __init__(self) -> None:
        if not os.path.isfile(PROXY_JAR):
            raise BurpError(
                f"proxy jar not found at {PROXY_JAR}. Set BURP_MCP_PROXY_JAR or install it."
            )
        if not (os.path.isfile(JAVA_BIN) or _on_path(JAVA_BIN)):
            raise BurpError(f"java not found at {JAVA_BIN}. Set BURP_MCP_JAVA.")
        self.proc: Optional[subprocess.Popen] = None
        self._stdout_q: "queue.Queue[Optional[str]]" = queue.Queue()
        self._stderr_lines: List[str] = []
        self._reader: Optional[threading.Thread] = None
        self._errreader: Optional[threading.Thread] = None

    def __enter__(self) -> "ProxyStdioClient":
        env = dict(os.environ)
        env.setdefault("MCP_SSE_URL", SSE_URL)
        self.proc = subprocess.Popen(
            [JAVA_BIN, "-jar", PROXY_JAR, "--sse-url", SSE_URL],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        self._reader = threading.Thread(target=self._pump_stdout, daemon=True)
        self._reader.start()
        self._errreader = threading.Thread(target=self._pump_stderr, daemon=True)
        self._errreader.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()

    def _pump_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            self._stdout_q.put(line.rstrip("\n"))
        self._stdout_q.put(None)  # EOF sentinel

    def _pump_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        for line in self.proc.stderr:
            self._stderr_lines.append(line.rstrip("\n"))

    def _diag(self) -> str:
        tail = "\n".join(self._stderr_lines[-15:]).strip()
        return f"\n--- proxy stderr ---\n{tail}" if tail else ""

    def _send(self, payload: Dict[str, Any]) -> None:
        assert self.proc and self.proc.stdin
        if self.proc.poll() is not None:
            raise BurpError(
                "mcp-proxy exited before request could be sent. Is Burp running with the "
                f"MCP Server extension enabled at {SSE_URL}?{self._diag()}"
            )
        try:
            self.proc.stdin.write(json.dumps(payload) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            # the child can exit between the poll() above and this write
            raise BurpError(
                f"lost connection to mcp-proxy while sending ({exc}). Is Burp running with "
                f"the MCP Server extension at {SSE_URL}?{self._diag()}"
            )

    def _read_result(self, want_id: str, timeout: float) -> Dict[str, Any]:
        """Read lines until a JSON-RPC response with id==want_id arrives.

        Non-JSON lines (proxy logs that land on stdout) and unrelated messages are skipped.
        """
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BurpError(
                    f"timed out after {timeout:.0f}s waiting for Burp to answer "
                    f"(method id={want_id}).{self._diag()}"
                )
            try:
                line = self._stdout_q.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                if self.proc and self.proc.poll() is not None:
                    raise BurpError(
                        "mcp-proxy exited unexpectedly. Confirm Burp + MCP Server extension "
                        f"are running at {SSE_URL}.{self._diag()}"
                    )
                continue
            if line is None:
                raise BurpError(
                    f"mcp-proxy closed its output stream before answering.{self._diag()}"
                )
            line = line.strip()
            if not line or not (line.startswith("{") or line.startswith("[")):
                continue  # proxy log noise on stdout
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and msg.get("id") == want_id:
                if "error" in msg:
                    err = msg["error"]
                    raise BurpError(f"Burp returned an error: {json.dumps(err)}")
                return msg.get("result", {})

    def request(self, method: str, params: Optional[Dict[str, Any]] = None,
                timeout: float = CALL_TIMEOUT) -> Dict[str, Any]:
        req_id = uuid.uuid4().hex
        self._send({"jsonrpc": "2.0", "id": req_id, "method": method,
                    "params": params or {}})
        return self._read_result(req_id, timeout)

    def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def handshake(self) -> Dict[str, Any]:
        result = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
            timeout=HANDSHAKE_TIMEOUT,
        )
        self.notify("notifications/initialized")
        return result


def _on_path(name: str) -> bool:
    if os.path.sep in name:
        return False
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if d and os.path.isfile(os.path.join(d, name)):
            return True
    return False


# --- high level API -----------------------------------------------------------------------


class Burp:
    """Thin facade: handshake once, then list/call tools with name resolution."""

    def __init__(self, client: ProxyStdioClient) -> None:
        self.client = client
        self._tools: Optional[List[Dict[str, Any]]] = None

    def tools(self) -> List[Dict[str, Any]]:
        if self._tools is None:
            result = self.client.request("tools/list")
            self._tools = result.get("tools", [])
        return self._tools

    def resolve(self, *candidates: str) -> str:
        """Pick the live tool name best matching any candidate keyword set.

        We never hardcode a tool name; we match against what the installed extension reports.
        """
        names = [t.get("name", "") for t in self.tools()]
        lowered = {n.lower(): n for n in names}
        # exact match first (deterministic): first candidate that exists wins
        for cand in candidates:
            if cand.lower() in lowered:
                return lowered[cand.lower()]
        # fuzzy fallback: score every tool by its best candidate match
        scored = [
            (max((_match_score(c.lower(), n.lower()) for c in candidates), default=0.0), n)
            for n in names
        ]
        best_score = max((s for s, _ in scored), default=0.0)
        top = [n for s, n in scored if s == best_score]
        if best_score < 0.5 or not top:
            raise BurpError(
                f"could not find a Burp tool matching {candidates!r}. Available tools: "
                f"{names}. Use `list-tools` then `call --tool <name>` directly."
            )
        if len(top) > 1:
            # never guess between equally-good matches with different schemas
            raise BurpError(
                f"ambiguous tool match for {candidates!r}: {top}. Disambiguate with "
                "`call --tool <exact_name>`."
            )
        return top[0]

    def call(self, tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self.client.request("tools/call", {"name": tool, "arguments": arguments})


def _match_score(cand: str, name: str) -> float:
    cand_tokens = set(re.split(r"[^a-z0-9]+", cand)) - {""}
    name_tokens = set(re.split(r"[^a-z0-9]+", name)) - {""}
    if not cand_tokens:
        return 0.0
    overlap = len(cand_tokens & name_tokens) / len(cand_tokens)
    sub = 1.0 if cand.replace(" ", "") in name.replace("_", "") else 0.0
    return max(overlap, sub * 0.9)


# --- output discipline --------------------------------------------------------------------


def _truncate(obj: Any, field_cap: int) -> Any:
    if isinstance(obj, str):
        if len(obj) > field_cap:
            return obj[:field_cap] + "...[TRUNCATED]"
        return obj
    if isinstance(obj, list):
        return [_truncate(x, field_cap) for x in obj]
    if isinstance(obj, dict):
        return {k: _truncate(v, field_cap) for k, v in obj.items()}
    return obj


def emit(result: Any, field_cap: int = DEFAULT_FIELD_CAP,
         total_cap: int = DEFAULT_TOTAL_CAP, raw: bool = False) -> None:
    """Print a result as JSON, applying field truncation and a total byte cap."""
    payload = result if raw else _truncate(result, field_cap)
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if not raw and len(text.encode("utf-8")) > total_cap:
        text = text.encode("utf-8")[:total_cap].decode("utf-8", "ignore")
        text += "\n...[OUTPUT TRUNCATED at %d bytes - narrow your query]" % total_cap
    print(text)


# --- subcommands --------------------------------------------------------------------------


def _connect() -> "tuple[ProxyStdioClient, Burp]":
    client = ProxyStdioClient().__enter__()
    try:
        client.handshake()
    except BaseException:
        client.__exit__()  # never leak the spawned mcp-proxy on a failed handshake
        raise
    return client, Burp(client)


def _parse_json_arg(value: Optional[str]) -> Dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise BurpError(f"--args must be valid JSON: {exc}")
    if not isinstance(parsed, dict):
        raise BurpError("--args must be a JSON object")
    return parsed


def cmd_list_tools(args: argparse.Namespace) -> int:
    client, burp = _connect()
    try:
        tools = burp.tools()
        slim = [
            {
                "name": t.get("name"),
                "description": (t.get("description") or "")[:200],
                "input_schema": t.get("inputSchema", {}).get("properties", {}),
            }
            for t in tools
        ]
        emit({"count": len(slim), "tools": slim}, field_cap=400)
    finally:
        client.__exit__()
    return 0


def cmd_call(args: argparse.Namespace) -> int:
    client, burp = _connect()
    try:
        tool = args.tool
        if not any(t.get("name") == tool for t in burp.tools()):
            tool = burp.resolve(args.tool)
            print(f"# resolved tool -> {tool}", file=sys.stderr)
        result = burp.call(tool, _parse_json_arg(args.args))
        emit(result, field_cap=args.field_cap, total_cap=args.total_cap, raw=args.raw)
    finally:
        client.__exit__()
    return 0


def _wrapper(*tool_candidates: str):
    """Build a subcommand handler that resolves a tool then calls it with --args JSON."""

    def handler(args: argparse.Namespace) -> int:
        client, burp = _connect()
        try:
            tool = burp.resolve(*tool_candidates)
            print(f"# {tool_candidates[0]} -> {tool}", file=sys.stderr)
            result = burp.call(tool, _parse_json_arg(getattr(args, "args", None)))
            emit(result, field_cap=args.field_cap, total_cap=args.total_cap, raw=args.raw)
        finally:
            client.__exit__()
        return 0

    return handler


def cmd_ping(args: argparse.Namespace) -> int:
    """Preflight: confirm Burp + extension reachable, report tool count."""
    try:
        client, burp = _connect()
    except BurpError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2
    try:
        n = len(burp.tools())
        print(json.dumps({"ok": True, "sse_url": SSE_URL, "tool_count": n}, indent=2))
    finally:
        client.__exit__()
    return 0


# --- Phase 2: companion extension (scan launch + scripted fuzzing) ------------------------


def _autopilot(method: str, path: str, body: Optional[Dict[str, Any]] = None,
               params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Call the burp-autopilot-ext.jar loopback endpoint and return parsed JSON."""
    url = AUTOPILOT_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if AUTOPILOT_TOKEN:
        req.add_header("X-Autopilot-Token", AUTOPILOT_TOKEN)
    try:
        with urllib.request.urlopen(req, timeout=AUTOPILOT_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8") or "{}"
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise BurpError(f"autopilot returned non-JSON: {raw[:300]}")
    except urllib.error.HTTPError as exc:
        # HTTPError is also a response object; read+close its body for the detail
        try:
            detail = exc.read().decode("utf-8", "ignore")
        finally:
            exc.close()
        msg = detail[:300]
        try:
            parsed = json.loads(detail)
            if isinstance(parsed, dict) and parsed.get("error"):
                msg = parsed["error"]
        except json.JSONDecodeError:
            pass
        # any >=400 is a failure - never let it look like success to automation
        raise BurpError(f"autopilot HTTP {exc.code}: {msg}")
    except urllib.error.URLError as exc:
        raise BurpError(
            f"cannot reach the Autopilot companion extension at {AUTOPILOT_URL} ({exc.reason}). "
            "Load burp-autopilot-ext.jar in Burp (Extensions > Add > Java) and ensure it started. "
            "Override the address with BURP_AUTOPILOT_URL."
        )
    except (TimeoutError, OSError) as exc:
        raise BurpError(f"autopilot request to {url} failed: {exc}")


def cmd_autopilot_health(args: argparse.Namespace) -> int:
    try:
        emit(_autopilot("GET", "/health"))
    except BurpError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2
    return 0


def cmd_scan_start(args: argparse.Namespace) -> int:
    body = _parse_json_arg(args.args)
    if "urls" not in body:
        raise BurpError('scan-start needs --args with at least {"urls":["https://in-scope/..."]} '
                        'and optional "type":"audit"|"crawl", "requireInScope":true')
    emit(_autopilot("POST", "/scan-start", body=body), field_cap=args.field_cap,
         total_cap=args.total_cap, raw=args.raw)
    return 0


def cmd_scan_status(args: argparse.Namespace) -> int:
    emit(_autopilot("GET", "/scan-status", params={"taskId": args.task_id}),
         field_cap=args.field_cap, total_cap=args.total_cap, raw=args.raw)
    return 0


def cmd_fuzz(args: argparse.Namespace) -> int:
    body = _parse_json_arg(args.args)
    required = {"host", "port", "baseRequest", "payloads"}
    missing = required - set(body)
    if missing:
        raise BurpError(f"fuzz --args missing keys: {sorted(missing)}. Required: host, port, "
                        "baseRequest (contains placeholder), payloads[]. Optional: placeholder "
                        '(default "§FUZZ§"), https, maxRequests, delayMs, requireInScope')
    emit(_autopilot("POST", "/fuzz", body=body), field_cap=args.field_cap,
         total_cap=args.total_cap, raw=args.raw)
    return 0


# --- Phase 3: Burp Pro built-in REST API (complementary scan path) ------------------------


def _rest_base() -> str:
    return f"{BURP_REST_URL}/{BURP_REST_KEY}/v0.1" if BURP_REST_KEY else f"{BURP_REST_URL}/v0.1"


def _rest(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = _rest_base() + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=AUTOPILOT_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "ignore")
            location = resp.headers.get("Location")
            status = resp.status
        out: Dict[str, Any] = {"_status": status, "_location": location}
        if raw.strip():
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    out.update(parsed)
                else:
                    out["_data"] = parsed
            except json.JSONDecodeError:
                out["_body"] = raw[:500]
        return out
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "ignore")
        finally:
            exc.close()
        raise BurpError(f"Burp REST HTTP {exc.code}: {detail[:300]}")
    except urllib.error.URLError as exc:
        raise BurpError(
            f"cannot reach the Burp REST API at {BURP_REST_URL} ({exc.reason}). Enable it in "
            "Burp Settings > Suite > REST API, or set BURP_REST_URL / BURP_REST_KEY."
        )
    except (TimeoutError, OSError) as exc:
        raise BurpError(f"Burp REST request to {url} failed: {exc}")


def cmd_rest_scan_start(args: argparse.Namespace) -> int:
    body = _parse_json_arg(args.args)
    if "urls" not in body:
        raise BurpError('rest-scan-start needs --args with {"urls":["https://in-scope/..."]} '
                        "(optional: scan_configurations, scope, application_logins)")
    res = _rest("POST", "/scan", body=body)
    location = res.get("_location")
    if not location:
        raise BurpError(
            f"Burp REST returned no Location header (HTTP {res.get('_status')}); cannot determine "
            f"the scan id. Response: {json.dumps(res)[:200]}"
        )
    task_id = urllib.parse.urlparse(location).path.rstrip("/").rsplit("/", 1)[-1]
    if not task_id:
        raise BurpError(f"could not parse a scan id from Location header: {location}")
    emit({"taskId": task_id, "httpStatus": res.get("_status"), "location": location},
         field_cap=args.field_cap, total_cap=args.total_cap, raw=args.raw)
    return 0


def cmd_rest_scan_status(args: argparse.Namespace) -> int:
    task_id = urllib.parse.quote(args.task_id, safe="")
    emit(_rest("GET", f"/scan/{task_id}"),
         field_cap=args.field_cap, total_cap=args.total_cap, raw=args.raw)
    return 0


# --- argument parsing ---------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="burp_client.py",
        description="Drive Burp Suite via the MCP Server extension.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp: argparse.ArgumentParser, with_args: bool = True) -> None:
        if with_args:
            sp.add_argument("--args", help="JSON object of tool arguments")
        sp.add_argument("--field-cap", type=int, default=DEFAULT_FIELD_CAP,
                        help="max chars per string field (default %(default)s)")
        sp.add_argument("--total-cap", type=int, default=DEFAULT_TOTAL_CAP,
                        help="max bytes of output (default %(default)s)")
        sp.add_argument("--raw", action="store_true",
                        help="do not truncate (DANGER: can flood context)")

    sp = sub.add_parser("ping", help="preflight reachability check")
    sp.set_defaults(func=cmd_ping)

    sp = sub.add_parser("list-tools", help="list tools the installed extension exposes")
    add_common(sp, with_args=False)
    sp.set_defaults(func=cmd_list_tools)

    sp = sub.add_parser("call", help="call a tool by name with --args JSON")
    sp.add_argument("--tool", required=True, help="exact or fuzzy tool name")
    add_common(sp)
    sp.set_defaults(func=cmd_call)

    # Convenience wrappers. The FIRST candidate is the exact tool name on the currently
    # installed "MCP Server" extension (27 tools); resolve() matches it exactly. Extra
    # candidates are fuzzy fallbacks so the skill survives extension version drift.
    # No cross-protocol or project-vs-user fallbacks: tools with incompatible schemas must
    # never substitute for each other. Each wrapper resolves exactly one capability.
    wrappers = {
        "send-request": ("send_http1_request",),
        "send-request-http2": ("send_http2_request",),
        "repeater": ("create_repeater_tab",),
        "repeater-http2": ("create_repeater_tab_http2",),
        "intruder-send": ("send_to_intruder",),
        "proxy-history": ("get_proxy_http_history",),
        "proxy-history-regex": ("get_proxy_http_history_regex",),
        "websocket-history": ("get_proxy_websocket_history",),
        "scanner-issues": ("get_scanner_issues",),
        "collab-generate": ("generate_collaborator_payload",),
        "collab-poll": ("get_collaborator_interactions",),
        "intercept": ("set_proxy_intercept_state",),
        "task-engine": ("set_task_execution_engine_state",),
        "config-export": ("output_project_options",),
        "config-export-user": ("output_user_options",),
        "config-modify": ("set_project_options",),
        "config-modify-user": ("set_user_options",),
        "editor-get": ("get_active_editor_contents",),
        "editor-set": ("set_active_editor_contents",),
        "organizer": ("get_organizer_items",),
        "url-encode": ("url_encode",),
        "url-decode": ("url_decode",),
        "base64-encode": ("base64_encode",),
        "base64-decode": ("base64_decode",),
        "random-string": ("generate_random_string",),
    }
    for name, candidates in wrappers.items():
        sp = sub.add_parser(name, help=f"resolve & call the '{candidates[0]}' tool")
        add_common(sp)
        sp.set_defaults(func=_wrapper(*candidates))

    # Phase 2 - companion extension (separate loopback HTTP transport)
    sp = sub.add_parser("autopilot-health", help="check the companion extension is loaded")
    sp.set_defaults(func=cmd_autopilot_health)

    sp = sub.add_parser("scan-start", help="launch an active audit/crawl (companion ext)")
    add_common(sp)
    sp.set_defaults(func=cmd_scan_start)

    sp = sub.add_parser("scan-status", help="poll a launched scan (companion ext)")
    sp.add_argument("--task-id", default="all", help="task id from scan-start, or 'all'")
    add_common(sp, with_args=False)
    sp.set_defaults(func=cmd_scan_status)

    sp = sub.add_parser("fuzz", help="scripted Intruder-style attack with results (companion ext)")
    add_common(sp)
    sp.set_defaults(func=cmd_fuzz)

    # Phase 3 - Burp Pro built-in REST API (alternative scan path)
    sp = sub.add_parser("rest-scan-start", help="launch a scan via Burp's REST API")
    add_common(sp)
    sp.set_defaults(func=cmd_rest_scan_start)

    sp = sub.add_parser("rest-scan-status", help="poll a scan via Burp's REST API")
    sp.add_argument("--task-id", required=True, help="scan id returned by rest-scan-start")
    add_common(sp, with_args=False)
    sp.set_defaults(func=cmd_rest_scan_status)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BurpError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
