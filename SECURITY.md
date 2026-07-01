# Security Policy

## Authorized use only

Burp Autopilot sends **real HTTP traffic to real hosts** and can launch active scans and
fuzzing. Use it **exclusively** against systems you own or are **explicitly authorized** to
test — for example, an in-scope bug-bounty program or a contracted penetration test.

Unauthorized scanning, fuzzing, or exploitation of systems you do not have permission to test
is illegal in most jurisdictions. You are solely responsible for how you use this software.

The skill enforces a safety gate before any live action (see the "Scope & safety" section of
[`SKILL.md`](skills/controlling-burpsuite-autonomously/SKILL.md)):

- Confirm an explicit, in-scope target before every live request, scan, or fuzz.
- Honor each program's accepted-risk rules, rate limits, and excluded paths.
- No destructive/DoS automation, account mutation, or auth brute-force by default.
- Rate-limit fuzzing (`delayMs`), prefer the smallest payload set that proves the point, and
  prefer `requireInScope: true` for scans and fuzz runs.

## Network exposure

All components bind to **loopback only** by default:

- Companion extension: `127.0.0.1:9877` — additionally supports an optional
  `X-Autopilot-Token` shared secret (`BURP_AUTOPILOT_TOKEN`) for defense-in-depth on shared
  hosts. Do not expose this port beyond localhost.
- MCP transport (`:9876`) and REST API (`:1337`) are Burp's own loopback endpoints.

## Reporting a vulnerability

If you find a security issue in Burp Autopilot itself (not in a target you are testing), please
open a private report via GitHub Security Advisories on this repository, or open an issue
without exploit details and request a private channel. Please do not disclose publicly until a
fix is available.
