#!/usr/bin/env node
'use strict';

// Installer for the Burp Autopilot skill. Copies (or symlinks) the skill/ directory into a
// CLI harness's skills folder. Zero dependencies: Node standard library only.
//
//   npx github:Xavrir/burp-autopilot            # install into ~/.claude/skills
//   npx github:Xavrir/burp-autopilot --dir DIR  # install into a custom skills dir
//   npx github:Xavrir/burp-autopilot --symlink  # link instead of copy (local clones only)
//
// Env: SKILLS_DIR overrides the destination skills folder.

const fs = require('fs');
const os = require('os');
const path = require('path');

const SKILL_NAME = 'controlling-burpsuite-autonomously';
const SKIP = new Set(['__pycache__', '.playwright-cli', '.DS_Store']);

function parseArgs(argv) {
  const out = { dir: null, force: false, symlink: false, help: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--dir' || a === '-d') out.dir = argv[++i];
    else if (a === '--force' || a === '-f') out.force = true;
    else if (a === '--symlink' || a === '-s') out.symlink = true;
    else if (a === '--help' || a === '-h') out.help = true;
    else { console.error(`unknown argument: ${a}`); process.exit(2); }
  }
  return out;
}

function usage() {
  console.log(`Burp Autopilot skill installer

Usage:
  npx github:Xavrir/burp-autopilot [options]

Options:
  -d, --dir <path>   Skills directory (default: $SKILLS_DIR or ~/.claude/skills)
  -s, --symlink      Symlink the source instead of copying (for local clones)
  -f, --force        Overwrite an existing install
  -h, --help         Show this help
`);
}

function skillsDir(arg) {
  if (arg) return path.resolve(arg);
  if (process.env.SKILLS_DIR) return path.resolve(process.env.SKILLS_DIR);
  return path.join(os.homedir(), '.claude', 'skills');
}

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (SKIP.has(entry.name) || entry.name.endsWith('.pyc')) continue;
    const s = path.join(src, entry.name);
    const d = path.join(dest, entry.name);
    if (entry.isDirectory()) copyDir(s, d);
    else fs.copyFileSync(s, d);
  }
}

function makeExecutable(dir) {
  for (const rel of ['scripts/burp_client.py', 'scripts/burp-browser']) {
    const p = path.join(dir, rel);
    if (fs.existsSync(p)) { try { fs.chmodSync(p, 0o755); } catch (_) {} }
  }
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) return usage();

  const src = path.join(__dirname, '..', 'skill');
  if (!fs.existsSync(path.join(src, 'SKILL.md'))) {
    console.error(`error: could not find skill/SKILL.md next to the installer (looked in ${src})`);
    process.exit(1);
  }

  const dir = skillsDir(args.dir);
  const dest = path.join(dir, SKILL_NAME);

  // Handle an existing install.
  let existing = null;
  try { existing = fs.lstatSync(dest); } catch (_) {}
  if (existing) {
    if (!args.force) {
      console.error(`error: ${dest} already exists. Re-run with --force to overwrite.`);
      process.exit(1);
    }
    fs.rmSync(dest, { recursive: true, force: true });
  }

  fs.mkdirSync(dir, { recursive: true });

  if (args.symlink) {
    fs.symlinkSync(path.resolve(src), dest);
    console.log(`linked  ${dest} -> ${path.resolve(src)}`);
  } else {
    copyDir(src, dest);
    makeExecutable(dest);
    console.log(`installed  ${dest}`);
  }

  console.log(`
Next steps:
  1. Start Burp Suite and enable the built-in "MCP Server" extension.
  2. Provide an mcp-proxy.jar bridge and set BURP_MCP_PROXY_JAR (see the README).
  3. Preflight:  python3 "${path.join(dest, 'scripts', 'burp_client.py')}" ping

Optional (scans + fuzzing): build and load the companion extension from extension/.
Authorized testing only: never fire live requests at a host you are not cleared to test.`);
}

main();
