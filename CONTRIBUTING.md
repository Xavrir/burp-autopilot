# Contributing

Thanks for your interest in improving Burp Autopilot. Issues and pull requests are welcome.

## Repo layout

```
skill/        the agent skill: SKILL.md + burp_client.py + burp-browser + references/
extension/    the companion Burp (Montoya) extension: Java source + build scripts
docs/         architecture and design notes
install.sh    links skill/ into ~/.claude/skills/
```

## Development setup

- **Client (`skill/scripts/burp_client.py`)** — Python 3.8+, standard library only. No
  dependencies to install. Run `python3 skill/scripts/burp_client.py --help`.
- **Extension** — JDK 21+. From `extension/`, run `./fetch-deps.sh` once to pull the build
  dependencies from Maven Central, then `./build.sh` to produce
  `extension/build/burp-autopilot-ext.jar`. Load it into Burp via
  **Extensions ▸ Installed ▸ Add ▸ Java**.

## Guidelines

- **Keep tool names dynamic.** The client resolves Burp tool names live from `list-tools`;
  don't hardcode names that could drift when the extension updates.
- **Respect output discipline.** Long fields are truncated and total output capped to protect
  an agent's context — keep new subcommands within that budget.
- **Safety first.** Any new capability that sends target traffic must honor the scope/safety
  gate: default to conservative behavior, support rate limiting, and prefer scope checks.
- **No vendored binaries.** Build dependencies are fetched from Maven Central, not committed.
- **Docs stay in sync.** Update `SKILL.md`, the relevant `references/*.md`, and `README.md`
  when behavior changes. Bump `version` in `SKILL.md` and add a `CHANGELOG.md` entry.

## Pull requests

- Keep changes focused and describe the testing you did (against an authorized/lab target).
- Note any new environment variables or endpoints in the README configuration table.
