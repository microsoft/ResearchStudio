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
 *   RS_PLUGINS=idea,reel  RS_SCOPE=global|project  RS_AGENTS=claude,codex,qwenpaw
 *   RS_PIP=0|1  + the key env vars.
 */
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const PKG_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PYTHON = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');

const expandHome = (p) => (p.startsWith('~') ? path.join(os.homedir(), p.slice(1)) : p);

// Agent registry — every runtime that can host ResearchStudio skills. Adding
// support for a new agent host is one entry here. `skillsDir(base)` returns
// where SKILL.md folders go for a scope base (home dir for global, cwd for
// project). `pool: true` marks agents without a project-scoped skills dir:
// they install into one shared location regardless of scope.
const AGENTS = {
  claude: { label: 'Claude Code', skillsDir: (base) => path.join(base, '.claude', 'skills') },
  codex: { label: 'Codex CLI', skillsDir: (base) => path.join(base, '.codex', 'skills') },
  qwenpaw: { label: 'QwenPaw', skillsDir: () => qwenpawDirs().pool, pool: true },
};

// QwenPaw keeps one shared skill pool under its working dir; pool entries are
// then broadcast into per-agent workspaces from the Console. The working dir
// resolution mirrors QwenPaw's constant.py: QWENPAW_WORKING_DIR env var first,
// then the legacy ~/.copaw layout, then ~/.qwenpaw.
function qwenpawDirs() {
  const home = process.env.QWENPAW_WORKING_DIR
    ? path.resolve(expandHome(process.env.QWENPAW_WORKING_DIR))
    : [path.join(os.homedir(), '.copaw'), path.join(os.homedir(), '.qwenpaw')]
        .find((d) => fs.existsSync(d)) || path.join(os.homedir(), '.qwenpaw');
  return { home, pool: path.join(home, 'skill_pool') };
}

// QwenPaw picks up manually placed pool skills on its next manifest reconcile.
// If its CLI is on PATH, nudge one now so the skills show up immediately;
// otherwise the next Console/CLI skill operation reconciles the manifest.
function qwenpawReconcile() {
  try {
    execFileSync('qwenpaw', ['skills', 'list', '--pool'], { stdio: 'ignore', timeout: 60_000 });
    return true;
  } catch {
    return false;
  }
}

// Preserve an explicit editor choice while giving installer subprocesses a
// predictable fallback on machines where EDITOR is unset or empty.
process.env.EDITOR ||= 'vim';

// Plugin registry. `dir` is the top-level folder in this repo; `pip` lists Python
// deps installed when that plugin is selected. Availability is detected at runtime.
const PLUGINS = [
  { key: 'idea', label: 'ResearchStudio-Idea', dir: 'ResearchStudio-Idea',
    blurb: 'idea-spark · paper-search · scoop-check',
    pip: ['feedparser', 'openreview-py', 'beautifulsoup4', 'pymupdf'] },
  { key: 'reel', label: 'ResearchStudio-Reel', dir: 'ResearchStudio-Reel',
    blurb: 'paper2assets · paper2poster · paper2video · paper2blog · paper2reel',
    pip: ['pymupdf', 'pillow', 'numpy', 'python-docx>=1.1.2', 'qrcode',
          'playwright', 'imageio-ffmpeg', 'edge-tts>=7.2.8'] },
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

// Paper2Video delegates deck authoring to ppt-master and rendering/QA to
// pptx2video. Fetch both skills from their upstream repos via `npx skills add`,
// installing into skillsDir. Returns the names that were added.
function fetchDependencySkills(skillsDir) {
  fs.mkdirSync(skillsDir, { recursive: true });
  const DEPS = [
    { repo: 'hugohe3/ppt-master', name: 'ppt-master' },
    { repo: 'ai-nuts/pptx2video', name: 'pptx2video' },
  ];
  const added = [];
  for (const d of DEPS) {
    try {
      execFileSync('npx', ['-y', 'skills', 'add', d.repo, '--skill', d.name],
        { cwd: skillsDir, stdio: 'inherit' });
      // `skills add` drops content under <skillsDir>/.agents/skills/<name>
      // rather than the top level where the Reel/Idea skills live. Move it up
      // to the top level so the agent's top-level scan finds it.
      const src = path.join(skillsDir, '.agents', 'skills', d.name);
      const dst = path.join(skillsDir, d.name);
      if (fs.existsSync(src)) {
        fs.rmSync(dst, { recursive: true, force: true });
        fs.renameSync(src, dst);
      }
      added.push(d.name);
    } catch {
      say(`  ${C.y}! failed to fetch ${d.name} via npx skills add — install it manually:${C.r}`);
      say(`    ${C.c}npx skills add ${d.repo} --skill ${d.name}${C.r}`);
    }
  }
  // Remove the now-empty .agents scaffold left by `skills add`.
  fs.rmSync(path.join(skillsDir, '.agents'), { recursive: true, force: true });
  return added;
}

function commandWorks(command, args) {
  try {
    execFileSync(command, args, { stdio: 'ignore' });
    return true;
  } catch {
    return false;
  }
}

// uv-created environments do not include pip by default. Use pip for conda or
// pip-enabled environments, then fall back to uv targeting the same interpreter.
function installPythonDeps(packages) {
  if (commandWorks(PYTHON, ['-m', 'pip', '--version'])) {
    const attempts = [
      ['-m', 'pip', 'install', '-q', ...packages],
      ['-m', 'pip', 'install', '--user', '--break-system-packages', '-q', ...packages],
      ['-m', 'pip', 'install', '--user', '-q', ...packages],
    ];
    for (const args of attempts) {
      try {
        execFileSync(PYTHON, args, { stdio: 'inherit' });
        return 'pip';
      } catch { /* try the next safe installation mode */ }
    }
  }
  if (commandWorks('uv', ['--version'])) {
    execFileSync('uv', ['pip', 'install', '--python', PYTHON, '-q', ...packages], { stdio: 'inherit' });
    return 'uv';
  }
  throw new Error(`could not install with pip or uv for ${PYTHON}`);
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
  const base = scope === 'global' ? os.homedir() : process.cwd();
  const agentList = Object.entries(AGENTS);
  let agents = (process.env.RS_AGENTS || 'claude').split(',').map((s) => s.trim()).filter(Boolean);
  if (!NONINTERACTIVE) {
    say(`\n${C.b}Agents${C.r}`);
    agentList.forEach(([key, a], i) => say(
      `  ${i + 1}) ${a.label}  ${C.d}(→ ${a.skillsDir(base)})${C.r}`));
    const ans = (await ask('Install for which agents? numbers e.g. 1 or 1,3', '1')).toLowerCase();
    const picked = ans === 'all' ? agentList.map(([k]) => k)
      : ans.split(/[\s,]+/).map((n) => agentList[parseInt(n, 10) - 1]?.[0]).filter(Boolean);
    agents = picked.length ? picked : ['claude'];
  }
  agents = agents.filter((a) => {
    if (AGENTS[a]) return true;
    say(`${C.y}  skipping unknown agent '${a}' — known: ${Object.keys(AGENTS).join(', ')}${C.r}`);
    return false;
  });
  if (!agents.length) { say(`${C.y}No agent selected.${C.r}`); process.exit(1); }

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
  const reelSelected = selected.some((p) => p.key === 'reel');
  for (const key of agents) {
    const agent = AGENTS[key];
    const dir = agent.skillsDir(base);
    if (agent.pool && scope === 'project') {
      say(`${C.d}  ${agent.label} has no project-scoped skills dir — installing into its shared pool instead${C.r}`);
    }
    for (const p of selected) installSkills(dir, p.src, p.skills);
    const total = selected.reduce((n, p) => n + p.skills.length, 0);
    say(`${C.g}✓${C.r} installed ${total} skills (${selected.map((p) => p.key).join(', ')}) → ${C.c}${dir}${C.r}`);
    // Paper2Video needs its dependency skills (ppt-master, pptx2video),
    // fetched from their upstream repos via npx skills add.
    if (reelSelected) {
      const deps = fetchDependencySkills(dir);
      if (deps.length) say(`  ${C.g}✓${C.r} provisioned ${deps.length} Paper2Video dep skill(s) (${deps.join(', ')}) → ${C.c}${dir}${C.r}`);
    }
    // QwenPaw's runtime loads <working-dir>/.env into the process env its
    // skills run in, and the skills' own .env walker reaches that file from
    // the pool — so one merged .env there covers pool skills wherever they run.
    // Other agents keep the skills-dir .env (the nearest common ancestor their
    // loaders check).
    const envDir = key === 'qwenpaw' ? qwenpawDirs().home : dir;
    const w = writeEnv(envDir, values);
    if (w) say(`  ${C.g}✓${C.r} wrote ${Object.keys(values).length} key(s) → ${w.envPath}${w.backedUp ? `  ${C.d}(backup: .env.bak)${C.r}` : ''}`);
    if (key === 'qwenpaw') {
      const ok = qwenpawReconcile();
      say(`  ${C.d}pool skills are shared — load them into a workspace from QwenPaw Console → Workspace → Skills` +
        `${ok ? '' : ' (they appear after the next manifest reconcile)'}`);
    }
  }

  // python deps for whichever selected plugins declare them
  const pips = [...new Set(selected.flatMap((p) => p.pip))];
  if (pips.length) {
    const doPip = process.env.RS_PIP === '1' || (process.env.RS_PIP !== '0' &&
      await askYN(`\nInstall Python deps now (${pips.join(', ')})?`, true));
    if (doPip) {
      try {
        const installer = installPythonDeps(pips);
        say(`${C.g}✓${C.r} Python deps installed with ${installer} (${PYTHON})`);
      } catch { say(`${C.y}! pip/uv step failed — install those packages yourself later${C.r}`); }
    }
  }

  const ns = selected.map((p) => `/${p.dir.toLowerCase()}:<skill>`).join('  ');
  say(`\n${C.b}${C.g}Done.${C.r} Restart your agent, then invoke a skill, e.g.  ${C.c}${ns}${C.r}`);
  say(`${C.d}Reminder: also export your LLM backend key (e.g. ANTHROPIC_API_KEY) in your shell.${C.r}`);

  // Reel needs native binaries + a Playwright browser that this cross-platform
  // installer won't touch (sudo apt-get is Debian-only; the Chromium download
  // is ~300 MB). Print the exact commands so the user can run them themselves.
  if (selected.some((p) => p.key === 'reel')) {
    say(`\n${C.y}Reel needs native tools this installer can't touch — run these yourself:${C.r}`);
    say(`  ${C.c}# Debian/Ubuntu${C.r} (use brew/dnf/pacman on macOS/Fedora/Arch)`);
    say(`  sudo apt-get install -y poppler-utils libreoffice ffmpeg`);
    say(`  ${C.c}# Chromium for Paper2Poster HTML→PDF/PNG (~300 MB download)${C.r}`);
    say(`  ${PYTHON} -m playwright install chromium`);
    say(`  ${C.c}# pptx2video pip runtime for Paper2Video (skill was fetched via npx skills add)${C.r}`);
    say(`  ${PYTHON} -m pip install 'pptx2video[svg] @ git+https://github.com/ai-nuts/pptx2video.git'`);
  }
  say('');
  process.exit(0);
}
main().catch((e) => { say(`${C.y}error: ${e.message}${C.r}`); process.exit(1); });
