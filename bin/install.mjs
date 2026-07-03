#!/usr/bin/env node
/*
 * ResearchStudio interactive installer.
 *
 * Run with:  npx github:microsoft/ResearchStudio
 *
 * One entry point for every ResearchStudio plugin. It auto-detects which plugins
 * actually ship skills in this checkout (a plugin is a top-level ResearchStudio-*
 * folder with a skills/ dir), lets you pick which to install, prompts for each
 * selected plugin's API keys (read live from that plugin's .env.template), copies
 * the skills into your agent's skills dir, and writes one merged .env the skills'
 * own loaders will find. Plugins whose code has not landed yet show as "coming soon".
 *
 * .env goes at <skills-dir>/.env because the skills' _env.py / run.py loaders walk
 * up from each skill dir and that is the nearest common ancestor they check.
 *
 * Non-interactive (--yes or no TTY) takes env answers:
 *   RS_PLUGINS=idea,reel  RS_SCOPE=global|project  RS_AGENTS=claude,codex
 *   RS_PIP=0|1  + the key env vars.
 */
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { execSync } from 'node:child_process';

const PKG_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const AGENTS = { claude: '.claude', codex: '.codex' };

// Plugin registry. `dir` is the top-level folder in this repo; `pip` lists Python
// deps installed when that plugin is selected. Availability is detected at runtime.
const PLUGINS = [
  { key: 'idea', label: 'ResearchStudio-Idea', dir: 'ResearchStudio-Idea',
    blurb: 'idea-spark · paper-search · scoop-check',
    pip: ['feedparser', 'openreview-py', 'beautifulsoup4', 'pymupdf'] },
  { key: 'reel', label: 'ResearchStudio-Reel', dir: 'ResearchStudio-Reel',
    blurb: 'paper2assets · paper2poster · paper2video · paper2blog · paper2reel',
    pip: [] },
];

const C = { d: '\x1b[2m', b: '\x1b[1m', g: '\x1b[32m', y: '\x1b[33m', c: '\x1b[36m', r: '\x1b[0m' };
const say = (s = '') => process.stdout.write(s + '\n');
const NONINTERACTIVE = process.argv.includes('--yes') || process.argv.includes('-y') || !process.stdin.isTTY;

// ── discovery ────────────────────────────────────────────────────────────────
function discoverSkills(srcDir) {
  if (!fs.existsSync(srcDir)) return [];
  return fs.readdirSync(srcDir, { withFileTypes: true })
    .filter((d) => d.isDirectory() && fs.existsSync(path.join(srcDir, d.name, 'SKILL.md')))
    .map((d) => d.name);
}

// Derive key prompts from a plugin's .env.template (stays in sync with the repo).
function loadKeySpec(pluginDir) {
  const tpl = path.join(pluginDir, '.env.template');
  if (!fs.existsSync(tpl)) return [];
  const keys = [];
  let required = false, lastComment = '';
  for (const raw of fs.readFileSync(tpl, 'utf8').split('\n')) {
    const line = raw.trim();
    if (line.startsWith('#')) {
      const cm = line.replace(/^#+\s?/, '');
      if (/required/i.test(cm)) required = true;
      else if (/optional/i.test(cm)) required = false;
      if (cm && !/^-{3,}/.test(cm)) lastComment = cm;
      continue;
    }
    if (!line || !line.includes('=')) continue;
    const key = line.slice(0, line.indexOf('=')).trim();
    if (!/^[A-Z][A-Z0-9_]*$/.test(key)) continue;
    keys.push([key, lastComment || key, { required, secret: /PASS|KEY|TOKEN|SECRET/i.test(key) }]);
  }
  return keys;
}

// ── prompt helpers ───────────────────────────────────────────────────────────
function ask(query, def = '') {
  return new Promise((resolve) => {
    process.stdout.write(`${query}${def ? ` ${C.d}[${def}]${C.r}` : ''}: `);
    let buf = '';
    const onData = (d) => {
      buf += d;
      if (buf.includes('\n')) {
        process.stdin.removeListener('data', onData); process.stdin.pause();
        resolve((buf.split('\n')[0] || '').trim() || def);
      }
    };
    process.stdin.resume(); process.stdin.setEncoding('utf8'); process.stdin.on('data', onData);
  });
}
function askHidden(query) {
  return new Promise((resolve) => {
    process.stdout.write(`${query}: `);
    const stdin = process.stdin; let input = '';
    stdin.resume(); stdin.setRawMode(true); stdin.setEncoding('utf8');
    const onData = (ch) => {
      if (ch === '\r' || ch === '\n' || ch === '') {
        stdin.setRawMode(false); stdin.pause(); stdin.removeListener('data', onData);
        process.stdout.write('\n'); resolve(input.trim());
      } else if (ch === '') { process.stdout.write('\n'); process.exit(1); }
      else if (ch === '' || ch === '\b') { input = input.slice(0, -1); }
      else { input += ch; }
    };
    stdin.on('data', onData);
  });
}
async function askYN(query, def = true) {
  if (NONINTERACTIVE) return def;
  const a = (await ask(`${query} ${def ? '(Y/n)' : '(y/N)'}`)).toLowerCase();
  return a === '' ? def : a.startsWith('y');
}

// ── file helpers ─────────────────────────────────────────────────────────────
function parseEnv(text) {
  const m = {};
  for (const line of text.split('\n')) {
    const t = line.trim();
    if (!t || t.startsWith('#') || !t.includes('=')) continue;
    const i = t.indexOf('='); m[t.slice(0, i).trim()] = t.slice(i + 1).trim();
  }
  return m;
}
function writeEnv(dir, values) {
  const envPath = path.join(dir, '.env');
  let existing = {}, backedUp = false;
  if (fs.existsSync(envPath)) {
    fs.copyFileSync(envPath, envPath + '.bak'); backedUp = true;
    existing = parseEnv(fs.readFileSync(envPath, 'utf8'));
  }
  const merged = { ...existing, ...values };
  if (Object.keys(merged).length === 0) return null;
  const body = ["# ResearchStudio connector credentials (written by the installer).",
    "# Auto-loaded by the skills' env loaders. Shell-exported vars still take precedence.",
    ...Object.entries(merged).map(([k, v]) => `${k}=${v}`), ''].join('\n');
  fs.writeFileSync(envPath, body, { mode: 0o600 });
  return { envPath, backedUp };
}
function installSkills(skillsDir, srcDir, names) {
  fs.mkdirSync(skillsDir, { recursive: true });
  for (const s of names) {
    fs.rmSync(path.join(skillsDir, s), { recursive: true, force: true });
    fs.cpSync(path.join(srcDir, s), path.join(skillsDir, s), { recursive: true });
  }
}

// ── main ─────────────────────────────────────────────────────────────────────
async function main() {
  say(`\n${C.b}${C.c}ResearchStudio installer${C.r}\n`);

  // detect available plugins
  const catalog = PLUGINS.map((p) => {
    const src = path.join(PKG_DIR, p.dir, 'skills');
    const skills = discoverSkills(src);
    return { ...p, src, skills, available: skills.length > 0 };
  });
  if (!catalog.some((p) => p.available)) {
    say(`${C.y}No installable plugins found next to this installer.${C.r}`); process.exit(1);
  }

  // pick plugins
  say(`${C.b}Plugins${C.r}`);
  catalog.forEach((p, i) => say(
    `  ${p.available ? C.b + (i + 1) + C.r : C.d + (i + 1) + C.r}) ${p.label}  ` +
    `${C.d}(${p.available ? p.blurb : 'coming soon — not in this release'})${C.r}`));
  let selected;
  if (NONINTERACTIVE) {
    const want = (process.env.RS_PLUGINS || '').split(',').map((s) => s.trim()).filter(Boolean);
    selected = (want.length ? catalog.filter((p) => want.includes(p.key)) : catalog).filter((p) => p.available);
  } else {
    const ans = (await ask("Install which? numbers e.g. 1 or 1,2, or 'all'", 'all')).toLowerCase();
    const chosen = ans === 'all' ? catalog
      : ans.split(/[\s,]+/).map((n) => catalog[parseInt(n, 10) - 1]).filter(Boolean);
    selected = chosen.filter((p) => {
      if (!p.available) { say(`${C.y}  skipping ${p.label} — not available yet${C.r}`); return false; }
      return true;
    });
  }
  if (!selected.length) { say(`${C.y}Nothing selected.${C.r}`); process.exit(1); }

  // scope + agents
  let scope = (process.env.RS_SCOPE || 'global').toLowerCase();
  if (!NONINTERACTIVE) {
    const a = (await ask('Install globally (all projects) or into this project? g/p', 'g')).toLowerCase();
    scope = a.startsWith('p') ? 'project' : 'global';
  }
  let agents = (process.env.RS_AGENTS || 'claude').split(',').map((s) => s.trim()).filter(Boolean);
  if (!NONINTERACTIVE) {
    agents = ['claude'];
    if (await askYN('Also install for Codex (in addition to Claude Code)?', false)) agents.push('codex');
  }
  const base = scope === 'global' ? os.homedir() : process.cwd();
  const targets = agents.filter((a) => AGENTS[a]).map((a) => path.join(base, AGENTS[a], 'skills'));

  // union of keys from the selected plugins' templates (dedup by name)
  const keySpec = []; const seen = new Set();
  for (const p of selected) for (const k of loadKeySpec(path.join(PKG_DIR, p.dir))) {
    if (!seen.has(k[0])) { seen.add(k[0]); keySpec.push(k); }
  }
  const values = {};
  if (keySpec.length) {
    say(`\n${C.b}API keys${C.r} ${C.d}(Enter to skip optional ones; secret input is hidden)${C.r}`);
    for (const [env, prompt, opt] of keySpec) {
      let v = '';
      if (NONINTERACTIVE) v = process.env[env] || '';
      else v = opt.secret ? await askHidden('  ' + prompt) : await ask('  ' + prompt);
      if (v) values[env] = v;
      else if (opt.required) say(`    ${C.y}! blank — that connector stays off until you set ${env}${C.r}`);
    }
  }

  // install
  say('');
  for (const dir of targets) {
    for (const p of selected) installSkills(dir, p.src, p.skills);
    const total = selected.reduce((n, p) => n + p.skills.length, 0);
    say(`${C.g}✓${C.r} installed ${total} skills (${selected.map((p) => p.key).join(', ')}) → ${C.c}${dir}${C.r}`);
    const w = writeEnv(dir, values);
    if (w) say(`  ${C.g}✓${C.r} wrote ${Object.keys(values).length} key(s) → ${w.envPath}${w.backedUp ? `  ${C.d}(backup: .env.bak)${C.r}` : ''}`);
  }

  // python deps for whichever selected plugins declare them
  const pips = [...new Set(selected.flatMap((p) => p.pip))];
  if (pips.length) {
    const doPip = process.env.RS_PIP === '1' || (process.env.RS_PIP !== '0' &&
      await askYN(`\nInstall Python deps now (${pips.join(', ')})?`, true));
    if (doPip) {
      try {
        execSync(`python3 -m pip install --user -q ${pips.join(' ')}`, { stdio: 'inherit' });
        say(`${C.g}✓${C.r} Python deps installed`);
      } catch { say(`${C.y}! pip step failed — install those packages yourself later${C.r}`); }
    }
  }

  const ns = selected.map((p) => `/${p.dir.toLowerCase()}:<skill>`).join('  ');
  say(`\n${C.b}${C.g}Done.${C.r} Restart your agent, then invoke a skill, e.g.  ${C.c}${ns}${C.r}`);
  say(`${C.d}Reminder: also export your LLM backend key (e.g. ANTHROPIC_API_KEY) in your shell.${C.r}\n`);
  process.exit(0);
}
main().catch((e) => { say(`${C.y}error: ${e.message}${C.r}`); process.exit(1); });
