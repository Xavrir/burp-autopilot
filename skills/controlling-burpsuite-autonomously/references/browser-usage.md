# `burp-browser` — Playwright as the Burp browser

Burp's *embedded* Chromium can't be automated (no Montoya/MCP hook). `scripts/burp-browser`
replaces it: it drives a **Playwright Chromium through Burp's proxy**, so every request lands in
Burp's proxy history (readable via `burp_client.py proxy-history*`) and is passively scanned —
and you can snapshot/screenshot the page for visibility.

## How it works

`burp-browser open` launches a dedicated `playwright-cli` session ("burp") with a generated config:
```json
{ "browser": { "browserName": "chromium",
  "launchOptions": { "proxy": { "server": "http://127.0.0.1:8080" },
                     "args": ["--proxy-bypass-list=<-loopback>"] },
  "contextOptions": { "ignoreHTTPSErrors": true } } }
```
- `proxy.server` → Burp's proxy listener (so Burp sees everything).
- `--proxy-bypass-list=<-loopback>` → forces **localhost** targets through Burp too (Chromium
  bypasses loopback by default).
- `ignoreHTTPSErrors` → accepts Burp's MITM cert without installing the CA.

## Prerequisites (one-time)
- Burp proxy listener running on `127.0.0.1:8080` (default).
- Chromium for playwright-cli: `playwright-cli install-browser chromium`.

## Usage (mirrors playwright-cli, on the Burp-routed session)
```bash
B={baseDir}/scripts/burp-browser
$B open https://target/path        # launch through Burp + navigate
$B snapshot                         # a11y snapshot -> element refs (e3, e5, ...)
$B click e5
$B fill e3 "user@example.com"
$B press Enter
$B eval "document.title"
$B screenshot --filename=/path/page.png
$B close
```
Then analyze what Burp captured:
```bash
python3 {baseDir}/scripts/burp_client.py proxy-history-regex --args '{"regex":"target","count":50}'
python3 {baseDir}/scripts/burp_client.py scanner-issues --args '{"count":50,"offset":0}'
```

## Env
- `BURP_PROXY` — proxy listener (default `http://127.0.0.1:8080`).
- `BURP_BROWSER_SES` — session name (default `burp`).
- `BURP_BROWSER_HEADED=0` — run headless (default headed, so you can watch it). Headless needs
  `chromium-headless-shell`; headed needs the full Chromium (`install-browser chromium`).

## Autonomous loop this enables
`burp-browser` (crawl/interact) → Burp captures + passively scans → `proxy-history`/`scanner-issues`
(triage) → `scan-start` (active audit of discovered endpoints) → `fuzz` (probe a parameter). The
raw MCP can't orchestrate this; the skill can. Keep the Scope & safety gate in force — only browse
/ attack authorized targets.
