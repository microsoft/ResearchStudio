"""IdeaSpark orchestrator.

Why this script exists:
  Phase 0 (literature grounding) and Phase 3 Step 3.1 (collision check) must run
  via the in-skill literature-search connectors (Phase 0 retrieval scripts) —
  NOT via WebSearch fallback or model-knowledge inline retrieval. This
  orchestrator is the canonical Bash entry point that subprocess-invokes the
  connector scripts directly, bypassing any Skill-tool indirection that could
  leave the model room to substitute WebSearch.

Design rationale (from the SKILL.md design doc):
  Skills are advisory — when SKILL.md says "run Phase 0 literature search", the
  model still has multiple paths it can take (Skill tool, direct Bash, WebSearch
  simulation, fetch arxiv URL). Each is "satisfying the spirit" of Phase 0.
  Soft rules don't reliably prevent tool drift. The orchestrator collapses the
  choice space: SKILL.md Phase 0 says "run THIS Bash command" — model has only
  one path or must explicitly admit failure. Coupled with Phase 1's entry
  assertion (lens_probe.txt checks lit_grounding_mode + retrieved_via), bypass
  becomes mechanically detectable, not just discouraged.

CLI (invocable from ANY working directory — run.py self-locates its skill root;
     $SKILL_DIR = where this skill is installed, $RUN_DIR = any absolute output dir):
  # Phase 0 — literature grounding (map mode)
  python3 "$SKILL_DIR/scripts/run.py" phase0 --query "<research question>" --out $RUN_DIR/phase0/

  # Phase 3 Step 3.1 — collision check
  python3 "$SKILL_DIR/scripts/run.py" phase3_collision --idea-json $RUN_DIR/phase2_winner.json --out $RUN_DIR/phase3_collision/

  # Optional: explicit web-fallback (for environments with no connectors)
  python3 "$SKILL_DIR/scripts/run.py" phase0 --query "..." --allow-webfallback

  # Sanity check connectors before running anything
  python3 "$SKILL_DIR/scripts/run.py" check_connectors

  # Legacy equivalent (still works): cd "$SKILL_DIR" && python3 -m scripts.run <subcommand> ...

Outputs (Phase 0):
  $RUN_DIR/phase0/lit_results.json         — ~30 deduped papers (role-based retrieval target)
  $RUN_DIR/phase0/lit_table.md             — paper-level evidence table (ideation pattern tags + bottleneck + open_issue)
  $RUN_DIR/phase0/.lit_grounding_mode      — sentinel file: "real" | "webfallback" | "connector_failure"

Phase 1's lens_probe enforces a hard assertion at entry that lit_grounding_mode
is present and acceptable; if not, downstream phases stop with a clear error.
"""
from __future__ import annotations
import argparse
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import warnings

# LibreSSL/urllib3 noise: macOS system Python links LibreSSL, so urllib3 v2 warns on
# every import — pure noise repeated by each connector call. Filter for this process,
# and via PYTHONWARNINGS (message-prefix form, no import needed) for every
# connector/dedup subprocess, preserving any user-set entries.
_URLLIB3_WARN_FILTER = 'ignore:urllib3 v2 only supports OpenSSL'
warnings.filterwarnings('ignore', message='urllib3 v2 only supports OpenSSL')
os.environ['PYTHONWARNINGS'] = (os.environ['PYTHONWARNINGS'] + ',' + _URLLIB3_WARN_FILTER
                                if os.environ.get('PYTHONWARNINGS') else _URLLIB3_WARN_FILTER)
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# SUB aliases ROOT: the Phase 0 / 3.1 connector scripts + rubrics live in this
# skill, so connector subprocess calls and rubric reads resolve in-skill.
SUB = ROOT

# Harness-agnostic invocation: allow `python3 /abs/path/scripts/run.py <cmd> ...`
# from ANY working directory, not only `cd <skill> && python3 -m scripts.run`.
# Claude Code injects a skill-dir CWD; other harnesses (Codex CLI, plain shells,
# cron) do not, so the `-m scripts.run` form and the in-package
# `from scripts.X import` / `-m scripts.X` subprocess calls would fail to resolve
# the `scripts` package. Putting the skill root on sys.path makes both work
# regardless of the caller's CWD. Idempotent; no effect under the `-m` form.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_env_file() -> None:
    """Auto-load .env from project root (and parents up to 4 levels) if present.

    Why this exists: connector probes (e.g. openreview) check os.environ for credentials.
    If the user invokes `python3 -m scripts.run phase0` without first running
    `set -a; source .env; set +a` in their shell, env vars from .env are NOT inherited
    into the subprocess and connectors silently skip with "missing env vars".

    This loader walks up from the skill directory looking for .env, and populates
    os.environ for any KEY=VALUE pair that is not already set (shell-provided values
    take precedence so users can override).
    """
    candidates = [ROOT, ROOT.parent, ROOT.parent.parent, ROOT.parent.parent.parent]
    for d in candidates:
        env_file = d / '.env'
        if env_file.exists():
            try:
                for line in env_file.read_text().splitlines():
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    k, _, v = line.partition('=')
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
            except Exception:
                pass  # silent fallback — user can still source .env manually
            break


_load_env_file()


# --- robustness guards (cross-platform) ------------------------------------

def _guard_project_path(raw: str, argname: str) -> None:
    """Fail loud + early when a path argument came from a mis-set run-dir
    variable (the single most common onboarding break).

    Three failure shapes are caught:
      1. An UNEXPANDED shell variable (`$RUN_DIR`, `${CLAUDE_PROJECT_DIR}`,
         any spelling) survived into the path — the host never set it, so
         the shell passed it through verbatim.
      2. The variable expanded to the EMPTY string, so `$RUN_DIR/phase0`
         collapsed to an absolute `/phase0` (or `/phaseN...`) at filesystem root.
         That is never an intended output location and otherwise surfaces only
         as a confusing `FileNotFoundError: /phase0/...` deep in a later phase.
      3. A RELATIVE `--out`, which would resolve against the caller's CWD —
         not stable across harnesses (Claude Code injects a skill-dir CWD;
         Codex CLI / plain shells / cron do not).

    Works identically on macOS and Linux (pure string / path-shape checks, no
    platform-specific assumptions).
    """
    if raw is None:
        return
    s = str(raw)
    # An unexpanded shell variable of ANY name survived into the path (the host
    # never set it, so the shell passed the literal `$VAR` / `${VAR}` through).
    # Checking for `$` generically covers $RUN_DIR, $CLAUDE_PROJECT_DIR,
    # $IDEA_SPARK_PROJECT_DIR, and any future spelling with one rule.
    if '$' in s:
        sys.stderr.write(
            f'\nERROR: {argname}={s!r} contains an unexpanded shell variable.\n'
            f'  The variable is not set in this shell, so it was passed through\n'
            f'  literally instead of expanding to a directory.\n'
            f'  Fix: pick any absolute run directory and set the variable first, e.g.\n'
            f'      RUN_DIR="$PWD/idea_run" && mkdir -p "$RUN_DIR"\n'
            f'  then re-run with an absolute --out (the run dir is just an output\n'
            f'  location you choose; the variable name does not matter).\n')
        sys.exit(2)
    # Root-level /phaseN means the var expanded empty.
    import re as _re
    if _re.match(r'^/phase[0-9]', s) or _re.match(r'^/(phase[0-9_a-z]*)/?$', s):
        sys.stderr.write(
            f'\nERROR: {argname}={s!r} resolves to filesystem root — this almost\n'
            f'  always means a run-dir variable expanded to the empty string.\n'
            f'  Fix: point the run dir at an absolute path, e.g.\n'
            f'      export IDEA_SPARK_PROJECT_DIR="$PWD/idea_run" && mkdir -p "$IDEA_SPARK_PROJECT_DIR"\n'
            f'  then re-run (or pass an explicit absolute --out).\n')
        sys.exit(2)
    # A relative --out resolves against the process CWD, which differs between
    # harnesses (Claude Code injects a skill-dir CWD; Codex/plain shells do not),
    # so outputs would silently land in the wrong place. Catch the set-but-wrong
    # case the empty/literal checks above miss.
    if argname == '--out' and not Path(s).is_absolute():
        sys.stderr.write(
            f'\nERROR: {argname}={s!r} is a RELATIVE path.\n'
            f'  It would resolve against the current working directory, which is not\n'
            f'  stable across harnesses. Pass an ABSOLUTE run directory, e.g.\n'
            f'      --out "$IDEA_SPARK_PROJECT_DIR/phase0/"\n')
        sys.exit(2)


def _warn_degraded_connectors(out_dir: Path, phase: str, available_labels: list[str]) -> None:
    """Make a partial-connector run IMPOSSIBLE to miss.

    The skill degrades gracefully when a connector package/cred is absent —
    but a single quiet `[skip]` line buried in a long log let a 2/4-connector
    collision run pass for a complete one. Here we (a) print a prominent banner
    and (b) drop a `.connectors_degraded` marker in out_dir so the degradation
    is auditable after the fact. No-op when all four connectors ran.
    """
    all_labels = [c[0] for c in CONNECTORS]
    skipped = [l for l in all_labels if l not in available_labels]
    if not skipped:
        # Clean run — clear any stale marker from a previous degraded run so it
        # can't mislead a later reader into thinking THIS run was partial.
        try:
            (out_dir / '.connectors_degraded').unlink(missing_ok=True)
        except Exception:
            pass
        return
    banner = (
        f'\n{"!" * 70}\n'
        f'  ⚠️  {phase}: CONNECTORS DEGRADED — ran {len(available_labels)}/{len(all_labels)}.\n'
        f'       used:    {", ".join(available_labels) or "(none)"}\n'
        f'       SKIPPED: {", ".join(skipped)}\n'
        f'       Retrieval/collision coverage is WEAKER than a full run.\n'
        f'       Common cause: the connector package is not importable in THIS\n'
        f'       process (e.g. a background/non-login shell that dropped the\n'
        f'       pip --user site-packages). Re-run `check_connectors` in the SAME\n'
        f'       shell you launch phases from, or install into the active env.\n'
        f'{"!" * 70}\n'
    )
    sys.stderr.write(banner)
    try:
        (out_dir / '.connectors_degraded').write_text(
            json.dumps({'phase': phase, 'used': available_labels, 'skipped': skipped},
                       ensure_ascii=False, indent=2))
    except Exception:
        pass


# Connectors: (label, module_path_in_subskill, requires_env_keys, requires_pip_packages)
CONNECTORS = [
    ('arxiv',           'scripts.search_arxiv',           [],                                       ['feedparser']),
    ('openalex',        'scripts.search_openalex',        [],                                       []),  # OPENALEX_API_KEY optional (polite pool works without)
    ('semanticscholar', 'scripts.search_semanticscholar', [],                                       []),  # SEMANTICSCHOLAR_API_KEY optional (anonymous tier works at lower rate)
    ('openreview',      'scripts.search_openreview',      ['OPENREVIEW_USER', 'OPENREVIEW_PASS'],   ['openreview']),
]

# Phase 0 map-mode retrieval is a list of JOBS, not one-job-per-connector: one
# connector may run several windows, and the 0-6mo freshness window is covered by
# TWO engines on purpose (overlap is a feature; SS-priority dedup merges it).
# Rationale: references/design-notes.md, "Why the freshness window is dual-engine".
# Caps are per-JOB overridable via IDEASPARK_POOL (see _resolve_pool_caps).
PHASE0_RETRIEVAL_JOBS = [
    # arxiv 0-6mo: bump max_per_query because sortBy=relevance returns top-50 across all time;
    # only ~5-8% of relevance-ranked top-50 fall within 6 months for typical queries, so we cast
    # a wider net (200 per query) and filter to window. Total API calls per query is still 1.
    # Caps are wide on purpose: a downstream host relevance-partition (Phase 0.4) admits only
    # `core` papers to the gap corpus + deep-read pool, so casting a wider net raises recall
    # without diluting Phase 1 — the marginal on-topic papers live in ranks N..~3N, not the tail.
    # Measured: at the old 18/15 caps every connector returned EXACTLY its cap (saturated), so
    # relevant work sat just below the cutoff, invisible to Phase 1/deep-read/collision.
    # timeout 600s: cost is max_per_query(200) x QUERY COUNT plus a 4s inter-request floor, NOT
    # max_results (which only truncates post-merge). A 6-query run measured >300s and the whole
    # connector was dropped — losing the freshest source entirely. 600s matches openreview.
    {'job': 'arxiv',            'connector': 'arxiv',           'window_min': 0, 'window_max': 6,  'max_results': 40, 'max_per_query': 200, 'extra_args': [], 'timeout': 600},
    {'job': 'ss_recent',        'connector': 'semanticscholar', 'window_min': 0, 'window_max': 6,  'max_results': 30, 'max_per_query': 40,  'extra_args': [], 'timeout': 300},
    {'job': 'oa_recent',        'connector': 'openalex',        'window_min': 0, 'window_max': 6,  'max_results': 0,  'max_per_query': 25,  'extra_args': ['--published-only'], 'timeout': 300},
    {'job': 'openalex',         'connector': 'openalex',        'window_min': 6, 'window_max': 24, 'max_results': 30, 'max_per_query': 40,  'extra_args': ['--published-only'], 'timeout': 300},
    {'job': 'semanticscholar',  'connector': 'semanticscholar', 'window_min': 6, 'window_max': 24, 'max_results': 30, 'max_per_query': 40,  'extra_args': ['--published-only'], 'timeout': 300},
    # openreview iterates ~20k notes per venue × 3 venues; cannot early-stop on broad queries.
    # Per-query cost is 2-5 min; 600s lets multi-query batches finish. Smallest cap: slowest
    # connector, in-review (unrefereed) quality, and ML submissions mostly mirror to arXiv anyway.
    {'job': 'openreview',       'connector': 'openreview',      'window_min': 0, 'window_max': 6,  'max_results': 10, 'max_per_query': 50,  'extra_args': [], 'timeout': 600},
]


def _resolve_pool_caps():
    """Per-job max_results, with IDEASPARK_POOL env overrides.

    IDEASPARK_POOL="job=N,job=N,..." (e.g. "arxiv=18,ss_recent=15,oa_recent=6").
    Unknown job names raise; a job set to 0 is skipped entirely (this is how
    oa_recent stays off by default and how a user turns it on per run). Missing
    jobs keep their PHASE0_RETRIEVAL_JOBS default. Fail-fast: a malformed value
    aborts Phase 0 rather than silently retrieving a wrong-sized pool.
    """
    caps = {j['job']: j['max_results'] for j in PHASE0_RETRIEVAL_JOBS}
    raw = os.environ.get('IDEASPARK_POOL', '').strip()
    if not raw:
        return caps
    for tok in raw.split(','):
        tok = tok.strip()
        if not tok:
            continue
        if '=' not in tok:
            raise ValueError(f"IDEASPARK_POOL entry {tok!r} must be job=N")
        job, val = (s.strip() for s in tok.split('=', 1))
        if job not in caps:
            raise ValueError(f"IDEASPARK_POOL unknown job {job!r}; valid: {sorted(caps)}")
        try:
            n = int(val)
        except ValueError as e:
            raise ValueError(f"IDEASPARK_POOL {job}={val!r} must be a non-negative integer") from e
        if n < 0:
            raise ValueError(f"IDEASPARK_POOL {job}={n} must be >= 0")
        caps[job] = n
    return caps

# Phase 3.1 collision retrieval windows (months). Two channels:
#   - signature channel: the candidate's OWN vocabulary (signature_terms) over a
#     recent window — catches contemporaneous scoops. Phase 0's broad-domain
#     queries cover 0-24mo but by TOPIC, not mechanism; 10mo (up from 6) narrows
#     the mechanism-specific gap at negligible retrieval cost.
#   - alias channel: OTHER communities' names for the same mechanism (alias_terms,
#     produced from parametric knowledge at Phase 2.2) over a multi-year window —
#     catches renamed ancestors. Widening the signature window alone cannot do
#     this: a same-mechanism paper from another community 2-3 years back uses
#     vocabulary the signature terms never contain (the "goal-conditioned success
#     detector vs goal-image conditioned scorer" failure mode), so the blind spot
#     is lexical, not temporal.
COLLISION_WINDOW_MONTHS = 10
ALIAS_COLLISION_WINDOW_MONTHS = 48

# Per-channel cap on the audit-facing collision pool. Dual-channel retrieval can
# return 600+ raw hits (~720KB) — beyond what the Phase 3.2 audit context can
# read whole. Hits are ranked by a lexical relevance score (how many distinct
# content words from the hit's own channel's query terms appear in title+abstract);
# ZERO-score hits are dropped unconditionally (BM25 phrase-fragment accidents —
# a true same-mechanism paper is retrieved BY those terms, so its score cannot
# be 0), then each channel keeps its top-N. The untruncated pool is preserved in
# `collision_hits.full.json`; drops are printed (no silent caps).
COLLISION_CHANNEL_CAP = 120

# Dedup priority when the same paper appears in multiple connectors.
# Higher priority means: keep this connector's record, drop the others.
# Semantic Scholar wins because its `externalIds` block (DOI + ArXiv + DBLP keys all in one record)
# makes it the strongest cross-source dedup anchor; it also returns abstracts + TLDR.
# Then openalex (peer-reviewed metadata) > openreview (in-review) > arxiv (preprint).
DEDUP_PRIORITY = {'semanticscholar': 4, 'openalex': 3, 'openreview': 2, 'arxiv': 1}


# --- connector availability ------------------------------------------------

def check_connector(label: str, module_path: str, env_keys: list[str],
                    packages: list[str]) -> tuple[bool, str]:
    """Return (available, reason_if_not)."""
    # 1) packages
    for pkg in packages:
        try:
            importlib.import_module(pkg)
        except ImportError:
            return False, f'package not installed: {pkg} (pip install {pkg})'
    # 2) env keys
    missing_env = [k for k in env_keys if not os.environ.get(k)]
    if missing_env:
        return False, f'missing env vars: {", ".join(missing_env)}'
    # 3) probe the actual script
    try:
        r = subprocess.run(
            [sys.executable, '-m', module_path, '--help'],
            cwd=str(SUB), capture_output=True, text=True, timeout=15
        )
        if r.returncode != 0:
            return False, f'script probe failed: {r.stderr[:200]}'
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return False, f'script probe error: {e}'
    return True, 'available'


def cmd_check_connectors(args) -> int:
    print('Connector availability check:')
    print('=' * 70)
    any_available = False
    for label, module_path, env_keys, pkgs in CONNECTORS:
        ok, reason = check_connector(label, module_path, env_keys, pkgs)
        any_available |= ok
        status = '✅ available' if ok else f'❌ {reason}'
        print(f'  {label:12s}  {status}')
    print('=' * 70)

    # Full-text fetch deps (Phase 0+) are NOT exercised by the connector probes
    # above, yet a missing one silently degrades every fetch to abstract-only
    # (Phase 1's gate only checks the file exists, not its content). Surface it
    # here so onboarding catches it instead of shipping a degraded run.
    print('Full-text fetch dependencies (Phase 0+):')
    for pkg, pip_name in (('fitz', 'pymupdf'), ('bs4', 'beautifulsoup4')):
        try:
            importlib.import_module(pkg)
            print(f'  {pip_name:14s}  ✅ available')
        except ImportError:
            print(f'  {pip_name:14s}  ⚠️  not installed (pip install {pip_name}) — '
                  f'full-text fetch will degrade to abstract-only')
    print('=' * 70)

    if not any_available:
        print('\nERROR: no connector is available. Install at least one:')
        print('  pip install feedparser  # arxiv (always works without key)')
        print('  pip install openreview-py + export OPENREVIEW_USER / OPENREVIEW_PASS')
        return 1
    print('\nTip: pip install feedparser openreview-py beautifulsoup4 pymupdf (or run ./install.sh) covers all of the above.')
    print('Proceed with the available connectors above; missing ones will be skipped.')
    return 0


# --- unified host-LLM sentinel handshake ------------------------------------

def emit_host_llm_sentinel(out_dir: Path, step_name: str, rubric_file: Path,
                           inputs: dict, expected_outputs: list[str],
                           instruction: str, re_invocation: str,
                           exit_code: int = 10) -> int:
    """Common pattern: orchestrator can't call an LLM (no NOVELTY_LLM_CLASSIFY_FAST_CMD env)
    so it emits a sentinel describing what the host LLM should do, then exits.

    The host LLM reads the sentinel, executes the step (per the rubric), produces the
    expected outputs in out_dir, and re-invokes the orchestrator (or proceeds to the
    next phase, depending on the step). The sentinel filename is `.{step_name}_pending`.

    All three Phase 0 + 3.1 LLM-driven steps use this helper:
      - intent_extraction (Phase 0): produce search queries from user_query
      - pattern_summary (Phase 0): classify retrieved papers into methodologies
      - signature_extraction (Phase 3.1): produce signature_terms from candidate idea
    """
    sentinel = out_dir / f'.{step_name}_pending'
    sentinel.write_text(json.dumps({
        'step_name': step_name,
        'rubric_file': str(rubric_file),
        'inputs': inputs,
        'expected_outputs': expected_outputs,
        'instruction': instruction,
        're_invocation': re_invocation,
    }, ensure_ascii=False, indent=2))
    print(f'\nhost-LLM mode: {step_name} pending.\n'
          f'  Sentinel: {sentinel}\n'
          f'  Action: {instruction[:200]}{"..." if len(instruction) > 200 else ""}\n'
          f'  Re-invocation: {re_invocation}\n',
          file=sys.stderr)
    return exit_code


# --- system clock guard ----------------------------------------------------

def assert_sane_now() -> datetime:
    now = datetime.now(timezone.utc)
    floor = datetime(2024, 1, 1, tzinfo=timezone.utc)
    ceiling = datetime(2027, 1, 1, tzinfo=timezone.utc)
    if now < floor:
        raise RuntimeError(
            f'System clock returns {now.isoformat()}, which is before 2024-01-01. '
            f'Sandbox time-freeze, NTP failure, or wrong TZ suspected. '
            f'Connector windows are runtime-relative, so window arithmetic is corrupted. '
            f'Fix the system clock / TZ before retrying. (Note: --as-of backdates the '
            f'retrieval reference date but does NOT bypass this real-clock sanity check.)'
        )
    if now > ceiling:
        print(f'WARNING: system clock returns {now.isoformat()}; window arithmetic will use this. '
              f'Verify intentional.', file=sys.stderr)
    return now


# --- Phase 0 orchestrator --------------------------------------------------

# Cross-run retrieval cache: a Phase 0 re-run otherwise re-hammers all four APIs
# (three runs inside ~15 min rate-limited arXiv AND Semantic Scholar to zero).
# Keyed on everything that changes the result set, so any real change misses.
# Short TTL because the windows are relative to the clock. Successful NON-EMPTY
# results only — caching a throttled `[]` would persist one bad minute for a day.
# Disable with IDEASPARK_RETRIEVAL_CACHE=off; set it to a path to relocate.
_RETRIEVAL_CACHE_TTL_S = int(os.environ.get('IDEASPARK_RETRIEVAL_CACHE_TTL_S', 24 * 3600))


def _retrieval_cache_dir():
    loc = os.environ.get('IDEASPARK_RETRIEVAL_CACHE', '').strip()
    if loc.lower() == 'off':
        return None
    return Path(loc) if loc else Path.home() / '.cache' / 'ideaspark' / 'retrieval'


# Bump when the connector RECORD SCHEMA changes. The key must version the schema, not
# just the request: after `from_query` provenance was added, a same-day cache hit would
# otherwise have served pre-provenance records and the per-query yield report would have
# reported them as '(unattributed)' with no indication anything was stale.
_RETRIEVAL_CACHE_SCHEMA = 2


def _retrieval_cache_key(module_path: str, queries_json: str, window_min_months: int,
                         window_max_months: int, max_results: int, max_per_query: int,
                         extra_args, as_of: str) -> str:
    import hashlib
    payload = json.dumps([_RETRIEVAL_CACHE_SCHEMA,
                          module_path, queries_json, window_min_months, window_max_months,
                          max_results, max_per_query, sorted(extra_args or []), as_of],
                         sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def run_connector_subprocess(module_path: str, queries_json: str, window_max_months: int,
                             out_path: Path, label: str, timeout: int = 300,
                             window_min_months: int = 0, max_results: int = 0,
                             max_per_query: int = 0, extra_args: list[str] | None = None,
                             as_of: str = '') -> bool:
    # Cache hit? Serve the stored records instead of re-hitting the API.
    _cdir = _retrieval_cache_dir()
    _ckey = _retrieval_cache_key(module_path, queries_json, window_min_months,
                                 window_max_months, max_results, max_per_query,
                                 extra_args, as_of) if _cdir else None
    _cfile = (_cdir / f'{_ckey}.json') if _cdir else None
    if _cfile is not None and _cfile.exists():
        try:
            if (time.time() - _cfile.stat().st_mtime) <= _RETRIEVAL_CACHE_TTL_S:
                _body = _cfile.read_text()
                _recs = json.loads(_body)
                if isinstance(_recs, list) and _recs:
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(_body)
                    _age_h = (time.time() - _cfile.stat().st_mtime) / 3600
                    print(f'  [{label}] {len(_recs)} records from the retrieval cache '
                          f'({_age_h:.1f}h old; IDEASPARK_RETRIEVAL_CACHE=off to bypass)',
                          file=sys.stderr)
                    return True
        except Exception:
            pass  # a cache is an accelerator, never a failure source

    # Resolve out_path to absolute — subprocess runs with cwd=SUB (the skill root),
    # so relative paths from the skill's invocation site would resolve against
    # the wrong directory and the connector would fail at write time.
    cmd = [
        sys.executable, '-m', module_path,
        '--queries', queries_json,
        '--window-months', str(window_max_months),
        '--window-min-months', str(window_min_months),
        '--out', str(out_path.resolve()),
    ]
    if max_results > 0:
        cmd.extend(['--max-results', str(max_results)])
    if max_per_query > 0:
        cmd.extend(['--max-per-query', str(max_per_query)])
    # Backdate the retrieval reference date (forward-prediction evals). Threaded to every
    # connector so all four windows shift consistently; connectors validate the value.
    if as_of:
        cmd.extend(['--as-of', as_of])
    if extra_args:
        cmd.extend(extra_args)
    try:
        r = subprocess.run(cmd, cwd=str(SUB), capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            print(f'  [{label}] failed (rc={r.returncode}):\n--- full stderr ---\n{r.stderr}\n--- full stdout ---\n{r.stdout}\n--- end ---', file=sys.stderr)
            return False
        if not out_path.exists() or out_path.stat().st_size == 0:
            print(f'  [{label}] produced empty output', file=sys.stderr)
            return False
        # Surface the connector's own progress lines on SUCCESS too. They were only
        # printed on rc != 0, so every diagnostic a healthy connector emits — the
        # round-robin merge stats, per-query yields, OpenAlex's semantic-booster
        # report — was captured and discarded, and the operator saw a bare paper
        # count with no way to tell WHICH query earned it.
        if r.stderr.strip():
            for _line in r.stderr.strip().splitlines():
                print(f'  {_line}', file=sys.stderr)
        # Cache successful, NON-EMPTY results only: a throttled `[]` cached for a
        # day would turn one bad minute into a day of silently-thin corpora.
        if _cfile is not None:
            try:
                _body = out_path.read_text()
                _recs = json.loads(_body)
                if isinstance(_recs, list) and _recs:
                    _cdir.mkdir(parents=True, exist_ok=True)
                    _cfile.write_text(_body)
            except Exception:
                pass
        return True
    except subprocess.TimeoutExpired:
        print(f'  [{label}] timed out after {timeout}s', file=sys.stderr)
        return False


def cmd_phase0(args) -> int:
    now = assert_sane_now()
    as_of = getattr(args, 'as_of', '') or ''
    if as_of:
        # Each connector re-validates and re-reports; this is the orchestrator-level notice.
        print(f'[phase0] --as-of {as_of}: retrieval windows will be computed relative to '
              f'{as_of}, not the real clock ({now.date().isoformat()}).', file=sys.stderr)
    # Resolve out_dir to absolute so all downstream paths passed to subprocesses
    # (which run with cwd=SUB) resolve against the user's invocation site, not SUB.
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Extract user-provided paper references from the query string (URL / arxiv ID / DOI / OpenReview ID).
    # Title-based references must be filled by the host LLM during intent-extraction (the
    # sentinel schema includes a `user_refs[]` slot). We persist the regex hits here so the
    # downstream `phase0_fulltext` subcommand can ingest them without re-parsing the query.
    try:
        from scripts.extract_user_refs import extract_refs_from_query
        user_refs = extract_refs_from_query(args.query)
    except Exception:
        user_refs = []
    user_refs_path = out_dir / 'user_refs.json'
    existing: list = []
    if user_refs_path.exists():
        try:
            existing = json.loads(user_refs_path.read_text())
        except Exception:
            existing = []
    seen_keys = {f"{r['type']}:{r['value']}" for r in user_refs}
    merged = list(user_refs) + [r for r in existing if f"{r.get('type','')}:{r.get('value','')}" not in seen_keys]
    user_refs_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False))
    if merged:
        print(f"[phase0] extracted {len(merged)} user reference(s) → {user_refs_path}", file=sys.stderr)

    # Step 1: intent extraction (LLM-driven; expects --queries from caller, or NOVELTY_LLM_CLASSIFY_FAST_CMD external CLI, or sentinel handshake with host LLM)
    queries = args.queries.split('|') if args.queries else None
    if queries:
        # On re-invocation with --queries, clear any prior intent-extraction sentinel
        prior_sentinel = out_dir / '.intent_extraction_pending'
        if prior_sentinel.exists():
            prior_sentinel.unlink()
    if not queries:
        intent_cmd = os.environ.get('NOVELTY_LLM_CLASSIFY_FAST_CMD')
        if intent_cmd:
            sys_prompt = (SUB / 'references' / 'intent-recognition.md').read_text()
            user = json.dumps({'mode': 'map', 'query': args.query})
            r = subprocess.run(intent_cmd, input=f'<<SYSTEM>>\n{sys_prompt}\n<<USER>>\n{user}',
                               shell=True, capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                try:
                    queries = json.loads(r.stdout).get('queries')
                except (json.JSONDecodeError, AttributeError):
                    queries = None
        if not queries:
            # No --queries provided AND no LLM CLI configured. Emit unified sentinel
            # and exit; do NOT silently fall back to using args.query verbatim — long
            # sentences with parens/quotes fail URL encoding at the connector layer.
            return emit_host_llm_sentinel(
                out_dir, step_name='intent_extraction',
                rubric_file=SUB / 'references' / 'intent-recognition.md',
                inputs={'user_query': args.query, 'mode': 'map'},
                expected_outputs=['re-invoke phase0 with --queries "q1|q2|q3"'],
                instruction=(
                    'Read the rubric file whose absolute path is in this sentinel\'s '
                    '`rubric_file` field (Map mode). Produce 3-5 search queries from user_query '
                    'per rubric: query 1 broad-domain, query 2 method-signature, query 3 '
                    'most-similar-problem, optional query 4 application-angle, optional query 5 '
                    'venue-insider. ALSO: scan user_query for paper-title references the user '
                    'intends as anchors (e.g., "based on Sora", "extending CycleResearcher", '
                    '"the LoRA paper") and register each via '
                    '`python3 <skill>/scripts/run.py add_user_ref --out <out_dir> --title "<full title>" '
                    '--raw-match "<user phrasing>"` (deterministic merge into user_refs.json; do NOT '
                    'hand-edit the file). Skip this step if no titles are mentioned (URL/ID refs are '
                    'handled by regex). '
                    'Apply the OOD short-circuit: if user_query matches the parent skill\'s '
                    'intake-routing.md trigger #1 (Too broad) or #2 (No anchor), return '
                    '{"ood": true, "trigger_id": ..., "trigger_quote": ..., "match_evidence": ...} '
                    'instead of queries — Phase 1 will emit do_not_generate.'
                ),
                re_invocation=f'python3 -m scripts.run phase0 --query "{args.query}" --queries "q1|q2|q3|..." --out {out_dir}',
                exit_code=10,
            )
    print(f'queries: {queries}')

    # Step 2: probe connectors
    available = []
    for label, module_path, env_keys, pkgs in CONNECTORS:
        ok, reason = check_connector(label, module_path, env_keys, pkgs)
        if ok:
            available.append((label, module_path))
        else:
            print(f'  [skip] {label}: {reason}', file=sys.stderr)

    _warn_degraded_connectors(out_dir, 'Phase 0', [l for l, _ in available])

    if not available:
        if args.allow_webfallback:
            print('NO connectors available; emitting webfallback sentinel as user requested.')
            (out_dir / '.lit_grounding_mode').write_text('webfallback')
            (out_dir / 'WEBFALLBACK_README.md').write_text(
                '# WebSearch fallback active\n\n'
                'No connector worked. The host LLM should construct queries with year tokens '
                f'derived from system date {now.date()} (NOT from training-time priors), and '
                'tag every retrieved paper with `retrieved_via: webfallback` in lit_table.md.\n\n'
                'Output is flagged as model-recall-grounded, not connector-grounded; downstream consumers should treat it as lower-confidence than a normal run.\n'
            )
            return 0
        print('\nERROR: no connector is available, and --allow-webfallback was not passed.\n'
              'Install at least one connector (`python3 -m scripts.run check_connectors` for diagnostic).\n'
              'Phase 0 cannot proceed.', file=sys.stderr)
        return 2

    # Step 3: run each retrieval JOB in its window (a connector may run >1 job).
    # See PHASE0_RETRIEVAL_JOBS for the per-window role + cap rationale.
    try:
        pool_caps = _resolve_pool_caps()
    except ValueError as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 2
    module_of = {label: mp for label, mp in available}
    queries_json = json.dumps(queries)
    hits_files = []            # list of (out_path, connector_label) for dedup priority
    successes = []             # connector labels that returned hits (for coverage checks)
    zero_yield = []            # jobs that ran cleanly but returned 0 records (throttling, usually)
    # Window-sibling compensation: if a job contributes nothing, the survivor
    # covering the SAME window absorbs its cap (<=2x, so one engine cannot balloon
    # the pool past what the partition can triage). See the dual-engine note below.
    dead_by_window: dict = {}
    for jobcfg in PHASE0_RETRIEVAL_JOBS:
        job = jobcfg['job']
        connector = jobcfg['connector']
        cap = pool_caps[job]
        if cap <= 0:
            continue           # job disabled (e.g. oa_recent default 0)
        _wkey = (jobcfg['window_min'], jobcfg['window_max'])
        _dead = dead_by_window.get(_wkey)
        if _dead:
            _bonus = min(sum(c for _n, c in _dead), cap)   # <= 2x this job's own cap
            print(f'  [{job}] absorbing +{_bonus} from failed same-window job(s) '
                  f'{", ".join(n for n, _c in _dead)} — window '
                  f'{_wkey[0]}-{_wkey[1]}mo would otherwise be under-covered',
                  file=sys.stderr)
            cap += _bonus
            dead_by_window[_wkey] = []
        module_path = module_of.get(connector)
        if module_path is None:
            continue           # connector unavailable; other jobs carry on
        out_path = out_dir / f'{job}_phase0.json'
        extra_args = list(jobcfg.get('extra_args', []))
        # Semantic recall booster for OpenAlex only (the one connector with a working semantic-search
        # endpoint). ON by default: it adds conceptually-adjacent papers BM25 misses, field-gated to
        # the BM25 pool's home field(s), and is safe in Phase 0 because Phase 0 queries are topical.
        # A CLI flag the host LLM would have to opt into is effectively dead (the LLM won't flip it),
        # so the useful behavior is the default; --no-openalex-semantic is a human escape hatch.
        # Bump the connector timeout because the semantic endpoint is rate-limited to 1 req/s.
        timeout = jobcfg.get('timeout', 300)
        if not getattr(args, 'no_openalex_semantic', False) and connector == 'openalex':
            extra_args = extra_args + ['--with-semantic']
            timeout = max(timeout, 600)
        def _run_job(_timeout):
            return run_connector_subprocess(
                module_path, queries_json,
                window_max_months=jobcfg['window_max'],
                out_path=out_path,
                label=f'{job}_{jobcfg["window_min"]}-{jobcfg["window_max"]}mo',
                window_min_months=jobcfg['window_min'],
                max_results=cap,
                max_per_query=jobcfg.get('max_per_query', 0),
                extra_args=extra_args,
                timeout=_timeout,
                as_of=as_of,
            )

        def _yield_of() -> int:
            # rc=0 + a non-empty FILE != records returned: a throttled connector
            # writes a valid `[]`. -1 = unparseable; let dedup surface that.
            try:
                _recs = json.loads(out_path.read_text())
                if isinstance(_recs, dict):
                    _recs = _recs.get('results') or _recs.get('papers') or _recs.get('hits') or []
                return len(_recs)
            except Exception:
                return -1

        ok = _run_job(timeout)
        n_rec = _yield_of() if ok else 0
        # One bounded retry, on EITHER failure mode — a lost connector costs the run
        # its whole contribution, and the usual causes clear in seconds (a query that
        # timed out at 300s returned in 1.8s minutes later). Zero-yield MUST be covered:
        # throttled connectors return rc=0 with `[]`, so an rc-keyed retry would miss
        # the exact case it exists for.
        if not ok or n_rec == 0:
            _why = 'failed' if not ok else 'returned 0 records'
            _pause = float(os.environ.get('IDEASPARK_RETRY_PAUSE_S', '45'))
            print(f'  [{job}] {_why}; retrying once in {_pause:.0f}s with a '
                  f'{int(timeout * 1.5)}s budget (a lost connector costs the whole run '
                  f'its contribution)', file=sys.stderr)
            time.sleep(_pause)
            ok = _run_job(int(timeout * 1.5))
            n_rec = _yield_of() if ok else 0
            if ok and n_rec != 0:
                print(f'  [{job}] retry succeeded ({n_rec} records)', file=sys.stderr)

        if not ok or n_rec == 0:
            if ok:      # ran cleanly but yielded nothing
                zero_yield.append(job)
                print(f'  [{job}] still 0 records after one retry (connector ran but '
                      f'yielded nothing — usually rate-limiting/throttling, or a window '
                      f'with no matches). NOT counted as a working source.', file=sys.stderr)
            dead_by_window.setdefault(_wkey, []).append((job, cap))
            continue

        hits_files.append((out_path, connector))
        if connector not in successes:
            successes.append(connector)

    # Second compensation pass: the in-loop absorption only fires when the dead job
    # runs BEFORE its window sibling. Re-run the survivor of any window still holding
    # an unclaimed dead cap, at its own cap plus the dead one (<=2x, same ceiling).
    for _wkey, _dead in list(dead_by_window.items()):
        if not _dead:
            continue
        _survivor = next((j for j in PHASE0_RETRIEVAL_JOBS
                          if (j['window_min'], j['window_max']) == _wkey
                          and j['connector'] in successes
                          and pool_caps.get(j['job'], 0) > 0
                          and j['job'] not in [n for n, _c in _dead]), None)
        if _survivor is None:
            continue
        _own = pool_caps[_survivor['job']]
        _bonus = min(sum(c for _n, c in _dead), _own)
        _sjob = _survivor['job']
        print(f'  [{_sjob}] re-running with +{_bonus} absorbed from failed same-window '
              f'job(s) {", ".join(n for n, _c in _dead)} — window {_wkey[0]}-{_wkey[1]}mo '
              f'is otherwise under-covered', file=sys.stderr)
        _sout = out_dir / f'{_sjob}_phase0.json'
        _sextra = list(_survivor.get('extra_args', []))
        _stimeout = _survivor.get('timeout', 300)
        if not getattr(args, 'no_openalex_semantic', False) and _survivor['connector'] == 'openalex':
            _sextra = _sextra + ['--with-semantic']
            _stimeout = max(_stimeout, 600)
        if run_connector_subprocess(
                module_of[_survivor['connector']], queries_json,
                window_max_months=_survivor['window_max'], out_path=_sout,
                label=f'{_sjob}_compensated', window_min_months=_survivor['window_min'],
                max_results=_own + _bonus, max_per_query=_survivor.get('max_per_query', 0),
                extra_args=_sextra, timeout=_stimeout, as_of=as_of):
            dead_by_window[_wkey] = []

    if zero_yield:
        print(f'\nWARNING: {len(zero_yield)} retrieval job(s) returned 0 records: '
              f'{", ".join(zero_yield)}. The corpus is SMALLER than the configured caps imply. '
              f'Back-to-back Phase 0 runs are the usual cause (arXiv + Semantic Scholar both '
              f'throttle); wait a few minutes and re-run if a whole source is missing.',
              file=sys.stderr)

    if not hits_files:
        print('\nERROR: connectors probed OK but all retrieval calls failed.\n'
              'Check API quotas, network, or per-connector errors above.', file=sys.stderr)
        return 3

    # Detect partial published-source coverage (informational, not blocking):
    # if both openalex + semanticscholar failed but at least one of arxiv/openreview worked,
    # the published-window (6-24mo peer-reviewed) is empty. Currently informational;
    # downstream can decide whether to downgrade lit_grounding_mode.
    published_succeeded = any(s in successes for s in ('openalex', 'semanticscholar'))
    if not published_succeeded:
        print(f'\nNOTE: no published-source connector succeeded (openalex + semanticscholar both unavailable). '
              f'Phase 0 ran on preprint-only sources ({", ".join(successes)}); '
              f'6-24mo peer-reviewed window is empty. Phase 1 will see preprint-only evidence.',
              file=sys.stderr)

    # Step 4: dedup_merge with priority-aware ordering. hits_files is (path, connector);
    # sort by the CONNECTOR's dedup priority (not the job/filename) so overlapping windows
    # of the same connector, and cross-connector duplicates, keep the highest-priority
    # record. Ties (same connector, two windows) preserve list order = recency-first.
    hits_files_sorted = [p for p, _c in
                         sorted(hits_files, key=lambda pc: -DEDUP_PRIORITY.get(pc[1], 0))]
    merged_out = out_dir / 'lit_results.json'
    dedup_cmd = [sys.executable, '-m', 'scripts.dedup_merge', '--inputs'] + [str(f) for f in hits_files_sorted] + ['--out', str(merged_out)]
    r = subprocess.run(dedup_cmd, cwd=str(SUB), capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print(f'dedup_merge failed: {r.stderr[:600]}', file=sys.stderr)
        return 4

    # Survey demotion: survey/review titles are magnets for broad queries but rarely
    # carry a mechanism to anchor on; stable-sort them to the BOTTOM of lit_results
    # (never dropped — pattern tagging still sees them; the demotion lowers their
    # salience in the fulltext-pool ranking and closest_adjacent scanning). Skipped
    # when the user's query itself asks for surveys.
    try:
        if not re.search(r'survey|review|综述', (args.query or ''), re.I):
            merged = json.loads(merged_out.read_text())
            papers_list = merged['papers'] if isinstance(merged, dict) and 'papers' in merged else merged
            is_survey = lambda p: bool(re.search(
                r'^(a |an )?(comprehensive |systematic |brief )*(survey|review|meta-analysis)\b'
                r'|:\s*(a )?(comprehensive |systematic )*(survey|review)\b',
                (p.get('title') or ''), re.I))
            n_surveys = sum(1 for p in papers_list if is_survey(p))
            if n_surveys:
                papers_list.sort(key=is_survey)  # stable: relative order preserved within groups
                merged_out.write_text(json.dumps(merged, indent=2, ensure_ascii=False))
                print(f'  demoted {n_surveys} survey/review-titled paper(s) to the bottom of '
                      f'lit_results (kept, not dropped)', file=sys.stderr)
    except Exception as e:
        print(f'  (survey demotion skipped: {e})', file=sys.stderr)

    # retrieved_via backfill: connector hit records don't all carry the field, but
    # the lit_table schema has a retrieved_via column and Phase 1's entry assertion
    # references it — absent values surface as None in every downstream reader.
    # Default = the winning connector (source); webfallback mode tags elsewhere.
    try:
        merged = json.loads(merged_out.read_text())
        papers_list = merged['papers'] if isinstance(merged, dict) and 'papers' in merged else merged
        n_fill = sum(1 for p in papers_list if not p.get('retrieved_via'))
        if n_fill:
            for p in papers_list:
                if not p.get('retrieved_via'):
                    p['retrieved_via'] = p.get('source') or 'unknown'
            merged_out.write_text(json.dumps(merged, indent=2, ensure_ascii=False))
            print(f'  backfilled retrieved_via for {n_fill} paper(s) (= source)', file=sys.stderr)
    except Exception as e:
        print(f'  (retrieved_via backfill skipped: {e})', file=sys.stderr)

    # Step 5: pattern_summary (LLM-driven; tags methodology, bottleneck, open_issue, resolves_problem).
    # Only emits lit_table.md — the methodology distribution + saturation flags are recomputed
    # by Phase 1 Step 1.0 directly from lit_table.md (via methodology-tag aggregation by time bucket),
    # so a separate novelty_pattern_summary.md is duplicate work.
    pattern_cmd_env = os.environ.get('NOVELTY_LLM_CLASSIFY_FAST_CMD')
    if pattern_cmd_env:
        pattern_cmd = [sys.executable, '-m', 'scripts.pattern_summary',
                       '--lit-results', str(merged_out),
                       '--rubric', str(SUB / 'references' / 'pattern-summary-rubric.md'),
                       '--out-table', str(out_dir / 'lit_table.md')]
        r = subprocess.run(pattern_cmd, cwd=str(SUB), capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            print(f'pattern_summary failed: {r.stderr[:300]}', file=sys.stderr)
            return 5
    else:
        emit_host_llm_sentinel(
            out_dir, step_name='pattern_summary',
            rubric_file=SUB / 'references' / 'pattern-summary-rubric.md',
            inputs={
                'lit_results': str(merged_out),
                'lit_table_columns': ['paper_id', 'year_month', 'venue', 'title', 'ideation pattern tags',
                                      'bottleneck this paper targets', 'open issue / unresolved gap',
                                      'resolves_problem', 'retrieved_via'],
            },
            expected_outputs=['lit_table.md'],
            instruction=(
                'Read the rubric file whose absolute path is in this sentinel\'s `rubric_file` '
                'field, classify each paper from lit_results into 1-3 of the 15 ideation patterns, '
                'tag bottleneck_targeted / open_issue / resolves_problem per the rubric '
                '(resolves_problem is high-bar; ≤5% of papers — leave empty otherwise). '
                'Render lit_table.md only (columns per inputs). The ideation pattern distribution and '
                'saturation flags are derived by Phase 1 Step 1.0 from lit_table directly; no '
                'separate summary file needed. Pure classification — do NOT spend the large '
                'reasoning model on it: default to a cheaper/faster model tier or lower '
                'reasoning effort when the harness supports routing (the '
                'NOVELTY_LLM_CLASSIFY_FAST_CMD tier).'
            ),
            re_invocation='no re-invocation; write lit_table.md directly to out_dir; Phase 1 entry assertion will pick it up',
            exit_code=0,
        )

    # Step 6: emit lit_grounding_mode sentinel (real because connector(s) succeeded).
    # `.lit_grounding_mode` is the only gate sentinel — Phase 1's entry assertion reads it.
    # `.connectors_used` and `.retrieved_at` were observability-only and have been removed;
    # the same info appears in Phase 0's stdout and is recoverable from the per-source JSON files'
    # mtime if needed for forensics.
    (out_dir / '.lit_grounding_mode').write_text('real')

    print(f'\n✅ Phase 0 complete. lit_grounding_mode = real')
    print(f'   connectors used: {", ".join(successes)}')
    print(f'   retrieved at:    {now.isoformat()}')
    print(f'   outputs in:      {out_dir}')
    return 0


# --- Phase 3 Step 3.1 collision orchestrator --------------------------------

def cmd_phase3_collision(args) -> int:
    now = assert_sane_now()
    as_of = getattr(args, 'as_of', '') or ''
    if as_of:
        print(f'[phase3_collision] --as-of {as_of}: collision windows computed relative to '
              f'{as_of}, not the real clock ({now.date().isoformat()}).', file=sys.stderr)
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    idea = json.loads(Path(args.idea_json).read_text())

    # Probe connectors (collision uses arxiv + openalex + semanticscholar + openreview)
    available = []
    for label, module_path, env_keys, pkgs in CONNECTORS:
        ok, reason = check_connector(label, module_path, env_keys, pkgs)
        if ok:
            available.append((label, module_path))
        else:
            print(f'  [skip] {label}: {reason}', file=sys.stderr)

    _warn_degraded_connectors(out_dir, 'Phase 3.1 collision', [l for l, _ in available])

    if not available:
        if args.allow_webfallback:
            (out_dir / '.lit_grounding_mode').write_text('webfallback')
            return 0
        print('ERROR: no connector available for collision check.', file=sys.stderr)
        return 2

    # Build collision queries from signature_terms (+ alias_terms). If the idea.json is
    # missing signature_terms, emit a sentinel for the host LLM to fill in (same pattern as
    # Phase 0 intent extraction). Falling back to [title, core_mechanism, novelty_claim] is
    # dangerous because those are long sentences that fail URL encoding at the connector layer.
    sig = idea.get('signature_terms')
    if not sig:
        return emit_host_llm_sentinel(
            out_dir, step_name='signature_extraction',
            rubric_file=SUB / 'references' / 'intent-recognition.md',
            inputs={'idea_json': args.idea_json, 'mode': 'collision'},
            expected_outputs=['edit idea_json to add signature_terms[] AND alias_terms[]'],
            instruction=(
                'Read the rubric file whose absolute path is in this sentinel\'s `rubric_file` '
                'field (Collision mode). Produce BOTH term sets: 3-5 signature_terms (mechanism + '
                'claim + setting + 1-2 specific identifiers, each 3-7 words, the candidate\'s own '
                'vocabulary) AND 2-4 alias_terms (other communities\' names for the same mechanism '
                '— parametric knowledge, not paraphrase). Add both fields to idea_json and '
                're-invoke. Long sentences (title / core_mechanism verbatim) fail URL encoding at '
                'the connector — keep terms tight.'
            ),
            re_invocation=f'python3 -m scripts.run phase3_collision --idea-json {args.idea_json} --out {out_dir}',
            exit_code=11,
        )
    alias = [a for a in (idea.get('alias_terms') or []) if a]
    if not alias:
        print('\nWARNING: candidate has no alias_terms[] — the cross-vocabulary collision channel '
              f'(same mechanism under other communities\' names, {ALIAS_COLLISION_WINDOW_MONTHS}mo '
              'window) is SKIPPED. Renamed same-mechanism ancestors will NOT be checked. Add '
              'alias_terms[] to the candidate JSON (rubric: intent-recognition.md Collision mode) '
              'and re-run to close this blind spot.\n', file=sys.stderr)

    def _run_channel(terms: list, window_months: int, suffix: str) -> list:
        queries_json = json.dumps([t for t in terms if t])
        files = []
        for label, module_path in available:
            out_path = out_dir / f'{label}_{suffix}.json'
            # Per-connector timeout = max over that connector's Phase 0 jobs (notably:
            # openreview gets 600s, since iterate-notes cost is the same in collision).
            timeout = max([j['timeout'] for j in PHASE0_RETRIEVAL_JOBS
                           if j['connector'] == label] or [300])
            if run_connector_subprocess(module_path, queries_json, window_months, out_path,
                                        f'{label}_{suffix}_{window_months}mo',
                                        timeout=timeout, as_of=as_of):
                files.append(out_path)
        return files

    sig_files = _run_channel(sig, COLLISION_WINDOW_MONTHS, 'collision')
    alias_files = _run_channel(alias, ALIAS_COLLISION_WINDOW_MONTHS, 'alias_collision') if alias else []

    if not sig_files and not alias_files:
        print('ERROR: all collision retrievals failed.', file=sys.stderr)
        return 3

    # Dedup each channel, then cross-channel merge with per-hit channel tags (signature wins
    # on overlap — a paper found by the candidate's own vocabulary is the stronger threat
    # signal for the audit). Phase 3.1 = retrieval + dedup only; Phase 3.2 audit's
    # paper-pointed threat search does subsumption judgment.
    def _dedup_channel(files: list, out_name: str) -> list:
        if not files:
            return []
        merged = out_dir / out_name
        cmd = [sys.executable, '-m', 'scripts.dedup_merge', '--inputs'] + \
              [str(f) for f in files] + ['--out', str(merged)]
        subprocess.run(cmd, cwd=str(SUB), check=True, capture_output=True, text=True, timeout=120)
        try:
            return json.loads(merged.read_text())
        except Exception:
            return []

    def _title_norm(t) -> str:
        return ' '.join(''.join(c.lower() if c.isalnum() else ' ' for c in (t or '')).split())

    sig_hits = _dedup_channel(sig_files, '.sig_channel_hits.json')
    alias_hits = _dedup_channel(alias_files, '.alias_channel_hits.json')
    for h in sig_hits:
        h['collision_channel'] = 'signature'
    seen_titles = {_title_norm(h.get('title')) for h in sig_hits}
    n_alias_new = 0
    for h in alias_hits:
        if _title_norm(h.get('title')) not in seen_titles:
            h['collision_channel'] = 'alias'
            sig_hits.append(h)
            n_alias_new += 1
    all_hits = sig_hits
    print(f'  channels: signature={len(all_hits) - n_alias_new} hits '
          f'({COLLISION_WINDOW_MONTHS}mo), alias=+{n_alias_new} unique hits '
          f'({ALIAS_COLLISION_WINDOW_MONTHS}mo{", SKIPPED" if not alias else ""})', file=sys.stderr)

    # Relevance-rank + truncate per channel (see COLLISION_CHANNEL_CAP comment).
    _STOP = {'with', 'from', 'that', 'this', 'into', 'over', 'under', 'then',
             'than', 'them', 'their', 'through', 'based', 'using', 'toward',
             'towards', 'via'}

    def _term_words(terms: list) -> set:
        words = set()
        for t in terms:
            for w in re.split(r'[^a-z0-9]+', str(t).lower()):
                if len(w) > 3 and w not in _STOP:
                    words.add(w)
        return words

    def _score(h: dict, words: set) -> int:
        text = ((h.get('title') or '') + ' ' + (h.get('abstract') or '')).lower()
        tokens = set(re.split(r'[^a-z0-9]+', text))
        # startswith gives crude stemming: 'watermark' matches 'watermarking/watermarks'
        return sum(1 for w in words if any(tok.startswith(w) for tok in tokens))

    channel_terms = {'signature': _term_words(sig), 'alias': _term_words(alias)}
    kept = []
    for ch in ('signature', 'alias'):
        ch_hits = [h for h in all_hits if h.get('collision_channel') == ch]
        if not ch_hits:
            continue
        for h in ch_hits:
            h['relevance_score'] = _score(h, channel_terms[ch])
        nonzero = sorted((h for h in ch_hits if h['relevance_score'] > 0),
                         key=lambda h: -h['relevance_score'])
        n_zero = len(ch_hits) - len(nonzero)
        # Adaptive relevance floor: score 1-2 is generic-word overlap, which admits
        # pure BM25 noise (observed live: humor-studies and cosmology hits riding a
        # skill-library query) whenever the corpus is rich. When at least half the
        # cap clears score>=3 the sub-3 tail is almost surely noise — drop it.
        # Thin channels keep the permissive floor so sparse corpora aren't starved.
        n_floor = 0
        strong = [h for h in nonzero if h['relevance_score'] >= 3]
        if len(strong) >= COLLISION_CHANNEL_CAP // 2:
            n_floor = len(nonzero) - len(strong)
            nonzero = strong
        n_cap = max(0, len(nonzero) - COLLISION_CHANNEL_CAP)
        kept_ch = nonzero[:COLLISION_CHANNEL_CAP]
        kept.extend(kept_ch)
        min_kept = f'; min kept score {kept_ch[-1]["relevance_score"]}' if kept_ch else ''
        print(f'  truncation[{ch}]: kept {len(kept_ch)}/{len(ch_hits)} '
              f'(dropped {n_zero} zero-relevance + {n_floor} below adaptive floor + '
              f'{n_cap} over cap {COLLISION_CHANNEL_CAP}{min_kept})',
              file=sys.stderr)

    # Full untruncated pool for forensics; the audit-facing file is the kept set.
    (out_dir / 'collision_hits.full.json').write_text(
        json.dumps(all_hits, ensure_ascii=False, indent=1))
    merged_out = out_dir / 'collision_hits.json'
    merged_out.write_text(json.dumps(kept, ensure_ascii=False, indent=1))

    # Slim collision_hits.json for the LLM-facing reader (Phase 3.2 audit). Full
    # abstracts blow the audit prompt; the paper-pointed-threat search needs
    # title + a truncated abstract + ids. (Hit-count control is the per-channel
    # relevance truncation above; abstract length is the per-hit knob here.)
    _COLLISION_ABSTRACT_CHARS = 1000  # 0 = keep the full abstract
    try:
        _hits = json.loads(merged_out.read_text())
        _keep = ('title', 'paper_id', 'venue', 'year', 'tldr', 'semantic_recall', 'source',
                 'collision_channel', 'relevance_score')
        def _slim(h):
            o = {k: h[k] for k in _keep if h.get(k) is not None}
            a = h.get('abstract') or ''
            if a:
                o['abstract'] = a[:_COLLISION_ABSTRACT_CHARS] if _COLLISION_ABSTRACT_CHARS else a
            return o
        merged_out.write_text(json.dumps([_slim(h) for h in _hits], ensure_ascii=False, indent=1))
    except Exception as _e:  # never fail the phase on a slim hiccup
        print(f'collision_hits slim skipped: {_e}', file=sys.stderr)

    # Sidecar recording WHICH terms produced these hits. `next` compares it
    # against the canonical candidate's terms so that a collision run launched
    # in PARALLEL with the 2.3 coherence gate stays valid: if a 2.3 patch later
    # changed signature/alias terms (rare — scoped to mechanism-changing
    # repairs), the mismatch is detected and collision is re-issued.
    (out_dir / '.collision_terms.json').write_text(json.dumps(
        {'signature_terms': sorted(t for t in (sig or []) if t),
         'alias_terms': sorted(t for t in (alias or []) if t)},
        ensure_ascii=False, indent=1))

    (out_dir / '.lit_grounding_mode').write_text('real')
    print(f'✅ Phase 3.1 collision retrieval complete. {merged_out.name} has {len(json.loads(merged_out.read_text()))} hits. retrieved at: {now.isoformat()}')
    return 0


# --- validators -------------------------------------------------------------

def _write_fulltext_split(out_dir: Path, cache: dict, lit_results: list) -> None:
    """Derived per-paper read view of fulltext_cache.json (the blob stays canonical).

    Downstream LLM phases read exactly the papers they need with plain file reads
    (offset/limit on a .md) instead of slicing a ~300KB JSON blob. Regenerated
    WHOLESALE on every blob write — including phase1_fulltext_topup — so the view
    can never go stale relative to the blob. index.json carries tier/source_used/
    warning per paper because the Phase 1 contract downgrades residue confidence
    for source_used=failed entries; dropping that marker would hide the downgrade.
    """
    titles = {}
    for p in lit_results or []:
        pid = p.get('paper_id') or p.get('id')
        if pid:
            titles[pid] = p.get('title') or ''
    # A U-tier user ref is SYNTHETIC — never in lit_results, so the loop above cannot
    # name it and its index row rendered untitled. That row is usually the anchor the
    # user named, and Phase 1 picks what to open off this index, so label it.
    for pid in cache:
        if titles.get(pid):
            continue
        if str(pid).startswith('user_ref:'):
            _val = str(pid).split(':', 2)[-1]
            titles[pid] = f'[user-supplied anchor] {_val}'
        elif pid not in titles:
            titles[pid] = ''
    split_dir = out_dir / 'fulltext'
    split_dir.mkdir(parents=True, exist_ok=True)
    for old in split_dir.glob('*.md'):  # exact mirror: drop leftovers from a prior, larger cache
        old.unlink()
    index = {}
    for pid, entry in cache.items():
        fname = re.sub(r'[^A-Za-z0-9._-]', '_', str(pid)) + '.md'
        intro = entry.get('intro') or ''
        method = entry.get('method') or ''
        (split_dir / fname).write_text(
            f"# {titles.get(pid) or pid}\n\n"
            f"paper_id: {pid}\ntier: {entry.get('tier')}\n"
            f"source_used: {entry.get('source_used')}\n"
            f"warning: {entry.get('warning') or 'none'}\n\n"
            f"## Intro\n\n{intro}\n\n## Method\n\n{method}\n")
        index[pid] = {'file': f'fulltext/{fname}', 'title': titles.get(pid, ''),
                      'tier': entry.get('tier'), 'source_used': entry.get('source_used'),
                      'intro_chars': len(intro), 'method_chars': len(method),
                      'warning': entry.get('warning')}
    (split_dir / 'index.json').write_text(json.dumps(index, indent=2, ensure_ascii=False))


def cmd_validate(args) -> int:
    """Run the contract validators on the phase outputs the user provides."""
    from scripts.validators import run_all_validators
    findings = run_all_validators(
        phase1_path=args.phase1, phase2_path=args.phase2,
        phase3_path=args.phase3, phase4_path=args.phase4,
        phase4_impl_path=args.phase4_impl,
    )
    if not findings:
        print('No validators ran — provide --phase1/2/3/4 paths to enable checks.', file=sys.stderr)
        return 0

    fails = [f for f in findings if f['severity'] == 'fail']
    warns = [f for f in findings if f['severity'] == 'warn']
    passes = [f for f in findings if f['severity'] == 'pass']

    for f in findings:
        sev_marker = {'fail': '✗', 'warn': '⚠', 'pass': '✓'}.get(f['severity'], '?')
        print(f'  {sev_marker} [{f["validator"]}] {f["message"]}')

    print(f'\n{len(passes)} pass, {len(warns)} warn, {len(fails)} fail', file=sys.stderr)
    return 1 if fails else 0


# --- main dispatch ----------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    p0 = sub.add_parser('phase0', help='Run Phase 0 literature grounding via in-skill connectors')
    p0.add_argument('--query', required=True, help='User research question (free text)')
    p0.add_argument('--queries', default='', help='Pipe-separated query strings (skip intent extraction if provided)')
    p0.add_argument('--out', default='outputs/phase0', help='Output dir (default outputs/phase0/)')
    p0.add_argument('--allow-webfallback', action='store_true',
                    help='If no connector works, emit webfallback sentinel (output is flagged as model-recall-grounded rather than connector-grounded). DEFAULT: hard-fail.')
    p0.add_argument('--as-of', default='',
                    help='YYYY-MM-DD: backdate all retrieval windows to reconstruct the literature state as of a past date (forward-prediction evals). Default = real clock.')
    p0.add_argument('--no-openalex-semantic', action='store_true',
                    help='Disable the OpenAlex semantic recall-booster (ON by default). The booster adds field-gated, '
                         'conceptually-adjacent papers BM25 misses by terminology; it is safe in Phase 0 because Phase 0 '
                         'queries are natural-language topical (the polysemy failure mode only hits short jargon signatures, '
                         'which Phase 0 does not use). Pass this only to skip it for speed / to avoid the 1 req/s semantic rate limit.')
    p0.set_defaults(func=cmd_phase0)

    p3 = sub.add_parser('phase3_collision', help='Run Phase 3 Step 3.1 collision check via in-skill connectors')
    p3.add_argument('--idea-json', required=True)
    p3.add_argument('--out', default='outputs/phase3_collision')
    p3.add_argument('--allow-webfallback', action='store_true')
    p3.add_argument('--as-of', default='',
                    help='YYYY-MM-DD: backdate collision-retrieval windows (match the same as-of used in phase0 for a consistent forward-prediction eval).')
    p3.set_defaults(func=cmd_phase3_collision)

    pc = sub.add_parser('check_connectors', help='Probe each connector and report availability')
    pc.set_defaults(func=cmd_check_connectors)

    pf = sub.add_parser('phase0_fulltext',
                        help='Fetch intro+method sections for the Phase 0 candidate pool '
                             '(U user-refs + T2 published-source on-topic + T3 top arxiv, '
                             'capped to the most relevant ~15 and fetched concurrently). '
                             'Run AFTER lit_table.md is written by the host LLM. '
                             'Produces outputs/<phase0>/fulltext_cache.json.')
    pf.add_argument('--out', default='outputs/phase0', help='Phase 0 output dir (must contain lit_results.json + lit_table.md + user_refs.json from prior `phase0` run)')
    pf.add_argument('--t3-top', type=int, default=15, help='Max arxiv (recent) papers into T3 (default 15; absorbs unused H/T2 slots up to --max-pool)')
    pf.add_argument('--t2-top', type=int, default=10, help='Max published-source papers into T2 (default 10)')
    pf.add_argument('--h-top', type=int, default=6, help='Max host-recall (retrieved_via host_*) papers into H (default 6)')
    pf.add_argument('--max-pool', type=int, default=25, help='Hard ceiling on total fetches excluding user refs (default 25)')
    pf.add_argument('--backfill', type=int, default=6, help='Reserve size: method-empty extractions are swapped for this many next-ranked core candidates (default 6; 0 disables)')
    def _cmd_phase0_fulltext(args):
        from scripts.fetch_sections import (select_candidate_pool, fetch_pool,
                                            fetch_sections, reconcile_lit_table_ids)
        out_dir = Path(args.out).resolve()
        lit_results_path = out_dir / 'lit_results.json'
        lit_table_path = out_dir / 'lit_table.md'
        user_refs_path = out_dir / 'user_refs.json'

        if not lit_results_path.exists():
            print(f'error: {lit_results_path} not found — run `phase0` first', file=sys.stderr)
            return 1
        if not lit_table_path.exists():
            print(f'warning: {lit_table_path} not found — on-topic filter will let everything through', file=sys.stderr)

        lit_results = json.loads(lit_results_path.read_text())
        if isinstance(lit_results, dict) and 'papers' in lit_results:
            lit_results = lit_results['papers']
        user_refs = json.loads(user_refs_path.read_text()) if user_refs_path.exists() else []

        # The LLM-written lit_table.md occasionally transcribes a paper_id onto the
        # wrong row; lit_results.json is authoritative, so re-derive ids by title
        # before the (id-keyed) on-topic filter and downstream phases consume them.
        if lit_table_path.exists():
            n_fixed = reconcile_lit_table_ids(lit_table_path, lit_results)
            if n_fixed:
                print(f'[phase0_fulltext] reconciled {n_fixed} lit_table paper_id(s) against lit_results', file=sys.stderr)

        pool = select_candidate_pool(lit_results, lit_table_path if lit_table_path.exists() else None,
                                     user_refs, t3_top_n=args.t3_top, t2_top_n=args.t2_top,
                                     max_pool=args.max_pool, h_top_n=args.h_top)
        n_u = sum(1 for p in pool if p['_tier'] == 'U')
        n_h = sum(1 for p in pool if p['_tier'] == 'H')
        n_t2 = sum(1 for p in pool if p['_tier'] == 'T2')
        n_t3 = sum(1 for p in pool if p['_tier'] == 'T3')
        print(f'[phase0_fulltext] candidate pool: {len(pool)} papers ({n_u} U + {n_h} H + {n_t2} T2 + {n_t3} T3)', file=sys.stderr)

        def _log(done, total, p, sections):
            pid = p.get('paper_id') or p.get('id') or 'unknown'
            title = (p.get('title') or '')[:80]
            status = sections['source_used']
            ok = 'OK' if status != 'failed' else 'FAIL'
            print(f'  [{done}/{total}] {p["_tier"]} {pid} {ok:5} {status:25} {title}', file=sys.stderr)

        cache = fetch_pool(pool, on_done=_log)

        # --- Backfill: swap method-empty extractions for next-ranked core reserves ---
        # A pooled paper that fetches to an empty method section (paywalled HTML,
        # non-arXiv landing page, extraction miss) wastes a deep-read slot without
        # informing the bottleneck. Reclaim it: pull the next-ranked core candidates
        # (a bigger select minus the papers already pooled) and fetch them in
        # priority order, swapping each method-bearing reserve in for one empty. U
        # (user refs) are never dropped. Final cache stays <= max_pool (one-out-one-in).
        def _has_method(v):
            return bool((v.get('method') or '').strip())
        empties = [pid for pid, v in cache.items() if v.get('tier') != 'U' and not _has_method(v)]
        if getattr(args, 'backfill', 0) > 0 and empties:
            pool_ids = {p.get('paper_id') or p.get('id') for p in pool}
            big = select_candidate_pool(lit_results, lit_table_path if lit_table_path.exists() else None,
                                        user_refs, t3_top_n=args.t3_top + args.backfill,
                                        t2_top_n=args.t2_top + args.backfill,
                                        max_pool=args.max_pool + args.backfill, h_top_n=args.h_top)
            reserve = [p for p in big if (p.get('paper_id') or p.get('id')) not in pool_ids]
            r_iter = iter(reserve)
            swapped = 0
            for empty_pid in empties:
                filled = False
                while not filled:
                    r = next(r_iter, None)
                    if r is None:
                        break
                    rpid = r.get('paper_id') or r.get('id') or ''
                    if rpid in cache:
                        continue
                    rsec = fetch_sections(r)
                    if _has_method(rsec):
                        del cache[empty_pid]
                        cache[rpid] = {'tier': r['_tier'], **rsec}
                        swapped += 1
                        filled = True
                        print(f'  [backfill] {r["_tier"]} swapped in for empty {empty_pid}: '
                              f'{(r.get("title") or "")[:70]}', file=sys.stderr)
                if not filled:
                    break  # reserve exhausted; keep remaining empties as-is
            if swapped:
                print(f'  [backfill] {swapped} empty extraction(s) replaced', file=sys.stderr)

        cache_path = out_dir / 'fulltext_cache.json'
        cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False))
        _write_fulltext_split(out_dir, cache, lit_results)
        n_ok = sum(1 for v in cache.values() if v['source_used'] != 'failed')
        print(f'\n  wrote {cache_path} ({n_ok}/{len(cache)} succeeded)', file=sys.stderr)
        print(f'  wrote per-paper read view: {out_dir / "fulltext"}/ ({len(cache)} .md + index.json)', file=sys.stderr)
        return 0
    pf.set_defaults(func=_cmd_phase0_fulltext)

    pt = sub.add_parser('phase1_fulltext_topup',
                        help='On-demand fulltext re-grounding for the #1 (anchor) closest_adjacent paper. '
                             'Phase 0 picks its ~15-paper fulltext pool by a relevance heuristic BEFORE Phase 1 '
                             'knows which paper is actually #1 closest_adjacent — so the load-bearing paper can '
                             'fall outside the cache (or land there as source_used=failed) and get an abstract-only '
                             'residue. After Phase 1 selects closest_adjacent[], call this for the anchor paper: it '
                             'fetches that one paper\'s intro+method and merges it into fulltext_cache.json so the '
                             'residue is method-grounded, not abstract-guessed. No-op if already grounded.')
    pt.add_argument('--out', default='outputs/phase0', help='Phase 0 output dir (must contain lit_results.json + fulltext_cache.json)')
    pt.add_argument('--paper-id', required=True,
                    help='Anchor paper identifier: paper_id (e.g. openalex:W..., arxiv:2401.12345), '
                         'or a bare arxiv_id / openreview_id / doi. Resolved against lit_results.json.')
    def _cmd_phase1_fulltext_topup(args):
        from scripts.fetch_sections import fetch_sections, _extract_arxiv_id, _extract_openreview_id
        out_dir = Path(args.out).resolve()
        lit_results_path = out_dir / 'lit_results.json'
        cache_path = out_dir / 'fulltext_cache.json'
        if not lit_results_path.exists():
            print(f'error: {lit_results_path} not found — run `phase0` first', file=sys.stderr)
            return 1

        lit_results = json.loads(lit_results_path.read_text())
        if isinstance(lit_results, dict) and 'papers' in lit_results:
            lit_results = lit_results['papers']
        cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

        key = args.paper_id.strip()
        bare = key.split(':', 1)[1] if ':' in key else key

        def _matches(p):
            pid = p.get('paper_id') or p.get('id') or ''
            if pid == key:
                return True
            ax = _extract_arxiv_id(p)
            if ax and ax.split('v')[0] == bare.split('v')[0]:
                return True
            if _extract_openreview_id(p) == bare:
                return True
            pdoi = p.get('doi') or (p.get('externalIds') or {}).get('DOI')
            if pdoi and pdoi == bare:
                return True
            return False

        match = next((p for p in lit_results if _matches(p)), None)
        if match is None:
            print(f'error: no lit_results paper matches "{key}" — pass the anchor\'s paper_id from closest_adjacent', file=sys.stderr)
            return 1
        pid = match.get('paper_id') or match.get('id') or key

        existing = cache.get(pid)
        if existing and existing.get('source_used') not in (None, 'failed'):
            print(f'[topup] {pid} already method-grounded ({existing["source_used"]}) — no-op', file=sys.stderr)
            return 0

        print(f'[topup] fetching intro+method for anchor {pid} ({(match.get("title") or "")[:70]})', file=sys.stderr)
        sections = fetch_sections(match)
        cache[pid] = {'tier': 'A', **sections}
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False))
        _write_fulltext_split(out_dir, cache, lit_results)
        status = sections['source_used']
        if status == 'failed':
            print(f'[topup] WARN anchor {pid} still failed across all paths — residue stays abstract-level; flag it', file=sys.stderr)
            return 0
        print(f'[topup] wrote {cache_path} — anchor {pid} now grounded via {status}', file=sys.stderr)
        return 0
    pt.set_defaults(func=_cmd_phase1_fulltext_topup)

    p2p = sub.add_parser('phase2_prepare',
                         help='Materialize phase2_generate/closest_abstracts.json — the closest_adjacent-only '
                              'slice of lit_results.json that ideate_generate.txt already instructs Phase 2.2 '
                              'to read. Deterministic: enforces the existing read contract instead of relying '
                              'on the sub-agent to self-filter (the non-closest ~30-40 papers are noise there '
                              'and cost ~15k tokens when read whole).')
    p2p.add_argument('--dir', required=True, help='Run directory (must contain phase1/phase1_output.json + phase0/lit_results.json)')
    def _cmd_phase2_prepare(args):
        d = Path(args.dir).resolve()
        p1_path = d / 'phase1' / 'phase1_output.json'
        lit_path = d / 'phase0' / 'lit_results.json'
        for pth in (p1_path, lit_path):
            if not pth.exists():
                print(f'error: {pth} not found', file=sys.stderr)
                return 1
        p1 = json.loads(p1_path.read_text())
        lit = json.loads(lit_path.read_text())
        if isinstance(lit, dict) and 'papers' in lit:
            lit = lit['papers']
        ca_ids = [e.get('paper_id') for e in (p1.get('closest_adjacent') or []) if e.get('paper_id')]
        matched = [p for p in lit if (p.get('paper_id') or p.get('id')) in set(ca_ids)]
        out_dir = d / 'phase2_generate'
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / 'closest_abstracts.json'
        out.write_text(json.dumps(matched, indent=2, ensure_ascii=False))
        missing = sorted(set(ca_ids) - {(p.get('paper_id') or p.get('id')) for p in matched})
        print(f'[phase2_prepare] wrote {out} ({len(matched)}/{len(ca_ids)} closest_adjacent papers)', file=sys.stderr)
        if missing:
            # Slice must never silently narrow the contract: surface the gap so the
            # 2.2 sub-agent knows where to pull these ids from. Split the advice —
            # a `user_ref:` id is a SYNTHETIC record that never entered lit_results,
            # so telling the agent to look there sends it somewhere the paper is not.
            # It lives only in the deep-read view, and it is typically the ANCHOR the
            # user explicitly named, i.e. the worst possible one to lose.
            _uref = [m for m in missing if str(m).startswith('user_ref:')]
            _other = [m for m in missing if not str(m).startswith('user_ref:')]
            if _other:
                print(f'[phase2_prepare] WARN {len(_other)} closest_adjacent id(s) not found in '
                      f'lit_results.json: {", ".join(_other)} — the Phase 2.2 agent must look these '
                      f'up in lit_results.json directly', file=sys.stderr)
            if _uref:
                print(f'[phase2_prepare] NOTE {len(_uref)} closest_adjacent id(s) are USER REFS and are '
                      f'not lit_results records by design: {", ".join(_uref)} — the Phase 2.2 agent must '
                      f'read them from the deep-read view instead ({d}/phase0/fulltext/index.json, then '
                      f'the entry\'s .md file). A user ref is usually the anchor, so do not skip it.',
                      file=sys.stderr)
        return 0
    p2p.set_defaults(func=_cmd_phase2_prepare)

    ltm = sub.add_parser('lit_table_merge',
                         help='Assemble lit_table.md from sharded pattern-tagging row files '
                              '(deterministic). Validates every row has exactly 9 cells, total '
                              'row count == lit_results paper count, and paper_id coverage — '
                              'the manual checks a host otherwise does by hand after parallel '
                              'fast-tier tagging.')
    ltm.add_argument('--out', required=True, help='phase0 output dir (contains lit_results.json; lit_table.md is written here)')
    ltm.add_argument('--shards', required=True, nargs='+',
                     help='Shard row files IN INPUT ORDER (rows only, with or without leading pipes; no header)')
    def _cmd_lit_table_merge(args):
        out_dir = Path(args.out).resolve()
        lit_path = out_dir / 'lit_results.json'
        if not lit_path.exists():
            print(f'error: {lit_path} not found', file=sys.stderr)
            return 1
        lit = json.loads(lit_path.read_text())
        papers = lit['papers'] if isinstance(lit, dict) and 'papers' in lit else lit
        expected_ids = [str(p.get('paper_id') or p.get('id') or '') for p in papers]
        cols = ['paper_id', 'year_month', 'venue', 'title', 'ideation pattern tags',
                'bottleneck this paper targets', 'open issue / unresolved gap',
                'resolves_problem', 'retrieved_via']
        rows, bad = [], []
        for fn in args.shards:
            fp = Path(fn).resolve()
            if not fp.exists():
                print(f'error: shard {fp} not found', file=sys.stderr)
                return 1
            for ln in fp.read_text(encoding='utf-8').splitlines():
                ln = ln.strip()
                if not ln or ln.startswith('|---') or 'paper_id | year_month' in ln:
                    continue
                cells = [c.strip() for c in ln.strip('|').split('|')]
                if len(cells) != len(cols):
                    bad.append((fp.name, len(cells), ln[:80]))
                    continue
                rows.append(cells)
        if bad:
            for b in bad:
                print(f'  MALFORMED ROW [{b[0]}] ({b[1]} cells): {b[2]}', file=sys.stderr)
            print(f'error: {len(bad)} malformed row(s) — fix the shard(s) and re-run; '
                  'nothing was written', file=sys.stderr)
            return 2
        if len(rows) != len(expected_ids):
            print(f'error: {len(rows)} rows != {len(expected_ids)} papers in lit_results.json — '
                  'a shard dropped or duplicated papers; nothing was written', file=sys.stderr)
            return 2
        got_ids = [r[0] for r in rows]
        missing = [i for i in expected_ids if i not in set(got_ids)]
        extra = [i for i in got_ids if i not in set(expected_ids)]
        if missing or extra:
            if missing:
                print(f'  missing paper_id(s): {", ".join(missing[:5])}'
                      + (f' … +{len(missing)-5}' if len(missing) > 5 else ''), file=sys.stderr)
            if extra:
                print(f'  unknown paper_id(s): {", ".join(extra[:5])}'
                      + (f' … +{len(extra)-5}' if len(extra) > 5 else ''), file=sys.stderr)
            print('error: paper_id coverage mismatch vs lit_results.json; nothing was written',
                  file=sys.stderr)
            return 2
        header = '| ' + ' | '.join(cols) + ' |'
        sep = '|' + '|'.join(['---'] * len(cols)) + '|'
        body = '\n'.join('| ' + ' | '.join(r) + ' |' for r in rows)
        (out_dir / 'lit_table.md').write_text(header + '\n' + sep + '\n' + body + '\n',
                                              encoding='utf-8')
        print(f'OK lit_table.md written: {out_dir / "lit_table.md"} '
              f'({len(rows)} rows from {len(args.shards)} shard(s); all 9-column, '
              'count + paper_id coverage verified)', file=sys.stderr)
        return 0
    ltm.set_defaults(func=_cmd_lit_table_merge)

    pr = sub.add_parser('phase4_render', help='Render the Phase 4 expansion JSON into the idea-card markdown + LaTeX (templating, no model call; compiles a PDF when xelatex/tectonic is on PATH, else skips with a hint)')
    pr.add_argument('--expansion', required=True, help='Phase 4 expansion JSON path')
    pr.add_argument('--out', default='outputs/phase4', help='Output dir (default outputs/phase4/)')
    pr.add_argument('--implementability', default=None,
                    help='Phase 4.1.5 implementability audit JSON (default: auto-detect sibling phase4_implementability.json)')
    def _cmd_phase4_render(args):
        from scripts.render_pdf import render_one, apply_implementability, _resolve_input
        out_dir = Path(args.out).resolve(); out_dir.mkdir(parents=True, exist_ok=True)
        expansion_path = _resolve_input(args.expansion)
        expansion = json.loads(expansion_path.read_text())
        apply_implementability(expansion, expansion_path,
                               _resolve_input(args.implementability) if args.implementability else None)
        md_path = render_one(expansion, out_dir)
        # Optional: generate a pipeline diagram via Azure OpenAI if available;
        # skipped gracefully if azure-identity / azure-openai are not installed.
        try:
            #from scripts.gen_pipeline import generate_pipeline
            #generate_pipeline(md_path)
            pass
        except (ImportError, ModuleNotFoundError) as e:
            print(f'  (skipped pipeline diagram: {e.name} not installed)', file=sys.stderr)
        return 0
    pr.set_defaults(func=_cmd_phase4_render)

    psk = sub.add_parser('phase4_skeleton',
                         help='Build the deterministic Phase 4 expansion skeleton. Every mechanical '
                              'field (kill-switch echo, venue-year lookup, group-by over lit_table, '
                              'candidate_uses from gap_closure x pattern_saturation, reviewer_concerns '
                              'lifted from the audit, differentiation_from_lit enriched with venue_year, '
                              'feasibility.compute verdict bucketed against intake.compute) is populated; '
                              'every prose field is a `<TODO[path]: hint>` placeholder. The host LLM then '
                              'authors a flat fill_map (path -> value) for the prose only, and '
                              '`phase4_assemble` merges it. LLM payload drops from ~30 fields to ~12 '
                              'prose-only fields.')
    psk.add_argument('--candidate', required=True,
                     help='Phase 3.3 final_candidate.json if revise ran, else Phase 2.2 '
                          'phase2_generate_output.json. Source of kill-switch + gap_closure + '
                          'differentiation_from_lit + almost_prior_paper_id + what_step_was_missed.')
    psk.add_argument('--phase1', required=True, help='phase1_output.json')
    psk.add_argument('--phase2-select', required=True, help='phase2_select_output.json')
    psk.add_argument('--phase3-critique', required=True, help='phase3_critique_output.json')
    psk.add_argument('--phase3-revise', default=None,
                     help='phase3_revise_output.json (optional; only when Phase 3.3 ran). '
                          'Used to populate reviewer_concerns_and_responses[].fields_changed_to_address.')
    psk.add_argument('--phase0-dir', required=True,
                     help='Phase 0 output dir containing lit_table.md + lit_results.json')
    psk.add_argument('--collision', default=None,
                     help='collision_hits.json from Phase 3.1 (optional; if absent the '
                          'literature_breakdown.phase3_collision list is empty).')
    psk.add_argument('--out', required=True,
                     help='Output dir for phase4_skeleton.json (typically $RUN_DIR/phase4/).')
    def _cmd_phase4_skeleton(args):
        from scripts.phase4_skeleton import build_skeleton, parse_lit_table
        out_dir = Path(args.out).resolve(); out_dir.mkdir(parents=True, exist_ok=True)
        candidate = json.loads(Path(args.candidate).resolve().read_text())
        if 'final_candidate' in candidate and isinstance(candidate['final_candidate'], dict):
            candidate = candidate['final_candidate']
        phase1 = json.loads(Path(args.phase1).resolve().read_text())
        phase2_select = json.loads(Path(args.phase2_select).resolve().read_text())
        phase3_critique = json.loads(Path(args.phase3_critique).resolve().read_text())
        phase3_revise = (json.loads(Path(args.phase3_revise).resolve().read_text())
                         if args.phase3_revise else None)
        phase0_dir = Path(args.phase0_dir).resolve()
        lit_table_rows = parse_lit_table(phase0_dir / 'lit_table.md')
        lit_results_path = phase0_dir / 'lit_results.json'
        lit_results = json.loads(lit_results_path.read_text()) if lit_results_path.exists() else []
        if isinstance(lit_results, dict) and 'papers' in lit_results:
            lit_results = lit_results['papers']
        collision_hits = (json.loads(Path(args.collision).resolve().read_text())
                          if args.collision and Path(args.collision).exists() else [])
        skeleton = build_skeleton(candidate, phase1, phase2_select, phase3_critique,
                                  phase3_revise, lit_table_rows, lit_results, collision_hits)
        out_path = out_dir / 'phase4_skeleton.json'
        out_path.write_text(json.dumps(skeleton, indent=2, ensure_ascii=False))
        n_todo = sum(1 for v in json.dumps(skeleton).split('"') if v.startswith('<TODO['))
        n_lit = skeleton['literature_breakdown']['summary']['n_phase0_on_topic']
        n_diff = len(skeleton['differentiation_from_lit'])
        n_rev = len(skeleton['reviewer_concerns_and_responses'])
        print(f'OK Phase 4 skeleton complete. Wrote {out_path}', file=sys.stderr)
        print(f'   {n_todo} TODO placeholders for the LLM to author', file=sys.stderr)
        print(f'   {n_lit} on-topic lit_table papers; {n_diff} differentiation entries; '
              f'{n_rev} reviewer concerns', file=sys.stderr)
        print(f'   compute verdict: {skeleton["feasibility_validation"]["compute"]["verdict"]}',
              file=sys.stderr)
        return 0
    psk.set_defaults(func=_cmd_phase4_skeleton)

    pas = sub.add_parser('phase4_assemble',
                         help='Apply the LLM-authored fill_map JSON to the Phase 4 skeleton, '
                              'producing phase4_expansion.json. Refuses to overwrite kill-switch '
                              'fields. Pure Python, no LLM.')
    pas.add_argument('--skeleton', required=True, help='Path to phase4_skeleton.json')
    pas.add_argument('--fill-map', required=True, action='append',
                     help='Path to a JSON file with {field_path: value} entries authored by the LLM. '
                          'Each path is the SAME path syntax used in the TODO placeholders. '
                          'Repeatable: pass once per map (e.g. the technical fill_map and the '
                          'derive_map) — maps are merged; overlapping paths are an error.')
    pas.add_argument('--out', required=True, help='Output dir for phase4_expansion.json.')
    def _cmd_phase4_assemble(args):
        from scripts.phase4_skeleton import assemble_expansion
        from scripts.json_repair import load_llm_json
        skeleton = json.loads(Path(args.skeleton).resolve().read_text())
        fill_map: dict = {}
        for fm_path in args.fill_map:
            # fill maps are LLM-written: a stray ASCII quote inside CJK prose
            # ("评级短语"重复毫无价值"有多准确") terminates the string early and
            # kills the assemble. Repair-on-read, reported on stderr.
            fm = load_llm_json(Path(fm_path).resolve())
            if not isinstance(fm, dict):
                print(f'ERROR: fill_map JSON must be an object {{path: value}}, got '
                      f'{type(fm).__name__} in {fm_path}', file=sys.stderr)
                return 1
            overlap = set(fill_map) & set(fm)
            if overlap:
                print(f'ERROR: fill maps overlap on {sorted(overlap)[:5]} — each TODO path must be '
                      f'owned by exactly one map', file=sys.stderr)
                return 1
            fill_map.update(fm)
        try:
            expansion = assemble_expansion(skeleton, fill_map)
        except ValueError as e:
            print(f'ERROR: {e}', file=sys.stderr)
            return 1
        out_dir = Path(args.out).resolve(); out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / 'phase4_expansion.json'
        out_path.write_text(json.dumps(expansion, indent=2, ensure_ascii=False))
        n_remaining = sum(1 for v in json.dumps(expansion).split('"') if v.startswith('<TODO['))
        if n_remaining:
            print(f'WARN {n_remaining} TODO placeholders remain in the expansion -- '
                  f'expansion_completeness validator will likely fail', file=sys.stderr)
        print(f'OK Phase 4 assembly complete. Wrote {out_path}', file=sys.stderr)
        return 0
    pas.set_defaults(func=_cmd_phase4_assemble)

    pmv = sub.add_parser('phase4_method_view',
                         help='Extract the method-only slice of phase4_expansion.json into '
                              'phase4/method_view.json — exactly the fields the 4.1.5 '
                              'implementability audit reads (method_flow, plain step renderings, '
                              'key_equations, claims). Cuts the audit\'s input roughly in half; '
                              'motivation prose, differentiation, landscape and kill-switch fields '
                              'are excluded by construction. Pure Python, no LLM.')
    pmv.add_argument('--expansion', required=True, help='Path to the COMPLETE phase4_expansion.json')
    pmv.add_argument('--out', required=True, help='Output dir for method_view.json')
    def _cmd_phase4_method_view(args):
        expansion = json.loads(Path(args.expansion).resolve().read_text())
        view_fields = ['title', 'method_name', 'abstract_draft', 'core_claim', 'sub_claims',
                       'key_equations', 'method_flow', 'plain_method_steps_en', 'plain_method_steps_zh']
        view = {k: expansion[k] for k in view_fields if k in expansion}
        missing = [k for k in ('method_flow', 'key_equations') if k not in view]
        if missing:
            print(f'ERROR: expansion lacks required field(s) {missing} — is this a complete expansion?',
                  file=sys.stderr)
            return 1
        leaked = '<TODO[' in json.dumps(view)
        if leaked:
            print('ERROR: view still contains TODO placeholders — run the final assemble '
                  '(all fill maps) before extracting the view', file=sys.stderr)
            return 1
        out_dir = Path(args.out).resolve(); out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / 'method_view.json'
        out_path.write_text(json.dumps(view, indent=2, ensure_ascii=False))
        full = len(json.dumps(expansion))
        print(f'OK method view written: {out_path} ({len(json.dumps(view)):,}B vs expansion {full:,}B)',
              file=sys.stderr)
        return 0
    pmv.set_defaults(func=_cmd_phase4_method_view)

    prb = sub.add_parser('phase3_revise_brief',
                         help='Extract the revision brief from the Phase 3.2 audit report — verdict, '
                              'rationale, revision_targets and the compact checks, dropping the '
                              'gap_closure_reject_check bulk (per-lesson quotations the audit already '
                              'distilled into revision_targets). The 3.3 reviser reads this instead of '
                              'the full report. Pure Python, no LLM.')
    prb.add_argument('--critique', required=True, help='Path to phase3_critique_output.json')
    prb.add_argument('--out', required=True, help='Output dir for revise_brief.json')
    def _cmd_phase3_revise_brief(args):
        critique_path = Path(args.critique).resolve()
        critique = json.loads(critique_path.read_text())
        if not critique.get('revision_targets'):
            print('WARN critique has no revision_targets — brief written anyway, but 3.3 should not '
                  'be running on this verdict', file=sys.stderr)
        brief = {k: v for k, v in critique.items() if k != 'gap_closure_reject_check'}
        brief['_brief_note'] = ('gap_closure_reject_check details omitted for context economy — '
                                f'full report at {critique_path}; read it ONLY if a revision_target\'s '
                                '`issue` cites a specific reject lesson you need verbatim.')
        out_dir = Path(args.out).resolve(); out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / 'revise_brief.json'
        out_path.write_text(json.dumps(brief, indent=2, ensure_ascii=False))
        print(f'OK revision brief written: {out_path} ({len(json.dumps(brief)):,}B vs '
              f'critique {len(json.dumps(critique)):,}B)', file=sys.stderr)
        return 0
    prb.set_defaults(func=_cmd_phase3_revise_brief)

    pfv = sub.add_parser('phase3_falsification_view',
                         help='Extract the falsification-re-audit slice of the merged candidate — '
                              'the rewritten falsification_prediction plus the mechanism fields '
                              'needed to judge non-tautology. The re-audit reads this instead of the '
                              'full candidate. Pure Python, no LLM.')
    pfv.add_argument('--candidate', required=True, help='Path to phase3_revise/final_candidate.json')
    pfv.add_argument('--out', required=True, help='Output dir for falsification_view.json')
    def _cmd_phase3_falsification_view(args):
        cand = json.loads(Path(args.candidate).resolve().read_text())
        fields = ['title', 'falsification_prediction', 'core_mechanism',
                  'core_mechanism_steps', 'core_mechanism_reasoning']
        view = {k: cand[k] for k in fields if k in cand}
        if 'falsification_prediction' not in view:
            print('ERROR: candidate lacks falsification_prediction — wrong file?', file=sys.stderr)
            return 1
        out_dir = Path(args.out).resolve(); out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / 'falsification_view.json'
        out_path.write_text(json.dumps(view, indent=2, ensure_ascii=False))
        print(f'OK falsification view written: {out_path} ({len(json.dumps(view)):,}B vs '
              f'candidate {len(json.dumps(cand)):,}B)', file=sys.stderr)
        return 0
    pfv.set_defaults(func=_cmd_phase3_falsification_view)

    pm = sub.add_parser('phase3_merge_revisions',
                        help='Apply the Phase 3.3 patch (applied_revisions[]) to the Phase 2.2 '
                             'candidate deterministically. Writes final_candidate.json next to '
                             'the patch file AND back-injects it into the patch file so the '
                             'legacy kill_switch_integrity validator keeps finding it under '
                             "phase3_revise_output.json['final_candidate']. Pure Python, no LLM. "
                             'This replaces the old Phase 3.3 contract where the LLM had to echo '
                             'the full ~25k-token candidate back; the new contract is patch-only.')
    pm.add_argument('--phase2', required=True,
                    help='Path to phase2_generate_output.json (the canonical Phase 2.2 candidate).')
    pm.add_argument('--revisions', required=True,
                    help='Path to phase3_revise_output.json containing applied_revisions[]. '
                         'The file is updated in place to add a `final_candidate` key.')
    pm.add_argument('--critique', default=None,
                    help='Path to phase3_critique_output.json. Required to authorize a '
                         '`rewrite_falsification` patch op (the merger verifies the audit '
                         'emitted a scope=falsification revision_target). Optional otherwise.')
    pm.add_argument('--out', required=True,
                    help='Output dir for final_candidate.json (typically the same dir as --revisions).')
    pm.add_argument('--out-name', dest='out_name', default='final_candidate.json',
                    help='Merged-candidate filename (default final_candidate.json). The Phase 2.3 '
                         'coherence gate reuses this merger with --out-name refined_candidate.json.')
    def _cmd_phase3_merge(args):
        from scripts.merge_revisions import merge_phase3_revisions
        try:
            final_path, revisions_path = merge_phase3_revisions(
                Path(args.phase2).resolve(),
                Path(args.revisions).resolve(),
                Path(args.out).resolve(),
                critique_path=Path(args.critique).resolve() if args.critique else None,
                out_name=args.out_name,
            )
        except ValueError as e:
            print(f'ERROR: {e}', file=sys.stderr)
            return 1
        # The same merger serves two phases; label the log by the actual out-name
        # so a 2.3 coherence merge doesn't masquerade as Phase 3.3 in run logs.
        stage = ('Phase 2.3 coherence' if (args.out_name or '') == 'refined_candidate.json'
                 else 'Phase 3.3')
        print(f'✅ {stage} merge complete. Wrote {final_path}', file=sys.stderr)
        print(f'   Back-injected `final_candidate` into {args.revisions} for legacy consumers.', file=sys.stderr)
        try:
            rev_doc = json.loads(Path(revisions_path).read_text())
            skipped = [r for r in (rev_doc.get('applied_revisions') or [])
                       if isinstance(r, dict) and r.get('outcome') == 'skipped_anti_substitution']
            if skipped:
                print('   ⚠️  DROPPED REVISION(S) — kill-switch protection refused these audit-requested '
                      'changes; they are NOT in the merged candidate:', file=sys.stderr)
                for r in skipped:
                    print(f'      - field={r.get("field")!r} issue={str(r.get("issue") or "")[:120]!r}',
                          file=sys.stderr)
                print('      The Phase 4 skeleton surfaces these as reviewer concerns; if the change '
                      'was a strengthen-only falsification edit, the audit should have authorized it '
                      'via a scope=falsification target (see critique.txt).', file=sys.stderr)
        except Exception:
            pass
        try:
            if json.loads(Path(revisions_path).read_text()).get('falsification_rewritten'):
                print('   ⚠️  falsification_prediction was REWRITTEN (audited exception). '
                      'Before Phase 4, run the falsification re-audit '
                      '(falsification_reaudit.txt — self-contained prompt) → '
                      'phase3_critique/falsification_reaudit.json with verdict=advance.',
                      file=sys.stderr)
        except Exception:
            pass
        return 0
    pm.set_defaults(func=_cmd_phase3_merge)

    pu = sub.add_parser('add_user_ref',
                        help='Merge a user-named paper reference into phase0/user_refs.json '
                             '(deterministic JSON merge, dedup on type:value; creates the file '
                             'if absent). Use this for TITLE-based references the phase0 regex '
                             'cannot extract ("based on the LoRA paper") — it avoids the host '
                             'Write-tool read-before-overwrite rule entirely. Run BEFORE '
                             'phase0_fulltext so the ref lands in the U fetch tier.')
    pu.add_argument('--out', required=True,
                    help='Phase 0 output dir containing user_refs.json (dir created if missing)')
    pu.add_argument('--title', action='append', default=[],
                    help='Paper title reference (repeatable for multiple papers)')
    pu.add_argument('--id', action='append', default=[], dest='ref_id',
                    help='arxiv id / DOI / OpenReview id / URL (repeatable); type auto-detected '
                         'via the same extractor phase0 uses on the query string')
    pu.add_argument('--raw-match', default='',
                    help='The user phrasing that named the paper (provenance; recorded when '
                         'exactly one --title is given)')
    def _cmd_add_user_ref(args):
        if not args.title and not args.ref_id:
            print('nothing to add: pass --title and/or --id', file=sys.stderr)
            return 2
        out_dir = Path(args.out).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / 'user_refs.json'
        try:
            existing = json.loads(path.read_text()) if path.exists() else []
        except Exception:
            existing = []
        if not isinstance(existing, list):
            existing = []
        new = []
        for t in args.title:
            entry = {'type': 'title', 'value': t}
            if args.raw_match and len(args.title) == 1:
                entry['raw_match'] = args.raw_match
            new.append(entry)
        if args.ref_id:
            from scripts.extract_user_refs import extract_refs_from_query
            for rid in args.ref_id:
                hits = extract_refs_from_query(rid)
                new.extend(hits if hits else [{'type': 'title', 'value': rid,
                                               'raw_match': 'unrecognized id format; stored as title'}])
        seen = {f"{r.get('type', '')}:{r.get('value', '')}" for r in existing if isinstance(r, dict)}
        added = [r for r in new if f"{r.get('type', '')}:{r.get('value', '')}" not in seen]
        path.write_text(json.dumps(existing + added, indent=2, ensure_ascii=False))
        print(f"added {len(added)} ref(s), skipped {len(new) - len(added)} duplicate(s) → {path}",
              file=sys.stderr)
        return 0
    pu.set_defaults(func=_cmd_add_user_ref)

    ph = sub.add_parser('add_host_refs',
                        help='Resolve host-nominated "missing" papers (Phase 0.5 coverage check) '
                             'into real records via the connectors and merge them into '
                             'lit_results.json with retrieved_via=host_recall|host_web. Each '
                             'nomination is VERIFIED by a connector lookup — an unresolvable '
                             'title (likely a hallucination) is NOT admitted, it is logged to '
                             'host_refs_unresolved.md. Deterministic; keeps lit_grounding_mode real.')
    ph.add_argument('--out', required=True, help='Phase 0 output dir (must contain lit_results.json)')
    ph.add_argument('--refs', required=True,
                    help='Path to a JSON file OR a JSON literal: a list of '
                         '{title, id_hint?, why?, source: parametric|websearch}')
    def _cmd_add_host_refs(args):
        import difflib
        out_dir = Path(args.out).resolve()
        lit_path = out_dir / 'lit_results.json'
        if not lit_path.exists():
            print(f'error: {lit_path} not found — run `phase0` first', file=sys.stderr)
            return 1
        try:
            refs = json.loads(Path(args.refs).read_text()) if Path(args.refs).exists() \
                else json.loads(args.refs)
        except Exception as e:
            print(f'error: could not parse --refs ({e})', file=sys.stderr)
            return 2
        if not isinstance(refs, list):
            print('error: --refs must be a JSON list', file=sys.stderr)
            return 2

        lit = json.loads(lit_path.read_text())
        papers = lit['papers'] if isinstance(lit, dict) and 'papers' in lit else lit

        def _tnorm(s):
            return ' '.join(''.join(c.lower() if c.isalnum() else ' ' for c in (s or '')).split())

        def _ax(s):  # version-stripped arxiv id
            s = re.sub(r'^arxiv:', '', (s or '').strip().lower())
            return re.sub(r'v\d+$', '', s)

        # Index existing corpus for the already-present check.
        have_titles = {_tnorm(p.get('title')) for p in papers}
        have_ax = {_ax(p.get('arxiv_id')) for p in papers if p.get('arxiv_id')}
        have_doi = {(p.get('doi') or '').lower() for p in papers if p.get('doi')}

        try:
            from scripts.search_semanticscholar import search as ss_search
        except Exception:
            ss_search = None
        try:
            from scripts.search_arxiv import search as ax_search
        except Exception:
            ax_search = None

        def _resolve(title):
            """Return a real connector record whose title matches `title` (>=0.9), or None."""
            tkey = _tnorm(title)
            candidates = []
            if ss_search:
                try:
                    candidates += ss_search(title, since_year=2000, max_results=5) or []
                except Exception as e:
                    print(f'  [ss lookup failed for {title!r}: {e}]', file=sys.stderr)
            if ax_search:
                try:
                    candidates += ax_search(title, max_results=5) or []
                except Exception as e:
                    print(f'  [arxiv lookup failed for {title!r}: {e}]', file=sys.stderr)
            best, best_r = None, 0.0
            for c in candidates:
                r = difflib.SequenceMatcher(None, tkey, _tnorm(c.get('title'))).ratio()
                if r > best_r:
                    best, best_r = c, r
            return best if best_r >= 0.9 else None

        added, already, unresolved = [], [], []
        for ref in refs:
            title = (ref.get('title') or '').strip()
            if not title:
                continue
            via = 'host_web' if ref.get('source') == 'websearch' else 'host_recall'
            rec = _resolve(title)
            if rec is None:
                unresolved.append({'title': title, 'why': ref.get('why', ''),
                                   'id_hint': ref.get('id_hint', '')})
                continue
            if (_tnorm(rec.get('title')) in have_titles
                    or (rec.get('arxiv_id') and _ax(rec.get('arxiv_id')) in have_ax)
                    or (rec.get('doi') and (rec.get('doi') or '').lower() in have_doi)):
                already.append(title)
                continue
            rec = dict(rec)
            rec['retrieved_via'] = via
            rec['host_why'] = ref.get('why', '')
            # Carry the nomination's own relevance verdict so the deep-read gate
            # can treat a host-nominated recent mechanism paper (core) differently
            # from a host-nominated foundational baseline (adjacent, cited but not
            # deep-read). Absent field defaults to core (deliberate load-bearing pick).
            rel = str(ref.get('relevance') or 'core').lower()
            rec['relevance'] = rel if rel in ('core', 'adjacent', 'off_topic') else 'core'
            # dedup_merge assigns paper_id during phase0, BEFORE these records exist.
            # SS records carry their own; arXiv-resolved ones do not, and a None id
            # keys the deep-read index `unknown_N` — unjoinable, so uncitable.
            if not rec.get('paper_id'):
                _src, _sid = rec.get('source'), rec.get('source_id')
                if _src and _sid:
                    rec['paper_id'] = f'{_src}:{_sid}'
                elif rec.get('arxiv_id'):
                    rec['paper_id'] = f'arxiv:{rec["arxiv_id"]}'
                elif rec.get('doi'):
                    rec['paper_id'] = f'doi:{rec["doi"]}'
            papers.append(rec)
            have_titles.add(_tnorm(rec.get('title')))
            if rec.get('arxiv_id'):
                have_ax.add(_ax(rec.get('arxiv_id')))
            added.append(rec)

        # Persist merged corpus (preserve the original list/dict envelope shape).
        if isinstance(lit, dict) and 'papers' in lit:
            lit['papers'] = papers
            lit_path.write_text(json.dumps(lit, ensure_ascii=False, indent=2))
        else:
            lit_path.write_text(json.dumps(papers, ensure_ascii=False, indent=2))

        # host_refs.json: ids of admitted refs (for downstream provenance/inspection).
        (out_dir / 'host_refs.json').write_text(json.dumps(
            [{'paper_id': r.get('paper_id'), 'title': r.get('title'),
              'retrieved_via': r.get('retrieved_via'), 'why': r.get('host_why', '')}
             for r in added], ensure_ascii=False, indent=2))

        if unresolved:
            lines = ['# Host-nominated papers that did NOT resolve to a real record',
                     '', 'These titles could not be verified via any connector and were NOT '
                     'admitted to the corpus (a likely hallucination or a title too garbled to '
                     'match). Review manually if any is genuinely important.', '']
            for u in unresolved:
                lines.append(f"- **{u['title']}**" + (f" (id_hint: {u['id_hint']})" if u['id_hint'] else ''))
                if u['why']:
                    lines.append(f"  - why nominated: {u['why']}")
            (out_dir / 'host_refs_unresolved.md').write_text('\n'.join(lines) + '\n')

        print(f'[add_host_refs] admitted {len(added)} (verified) · '
              f'{len(already)} already in corpus · {len(unresolved)} UNRESOLVED '
              f'(see host_refs_unresolved.md)', file=sys.stderr)
        for r in added:
            print(f'  + {r.get("retrieved_via")}: {r.get("title","")[:70]}', file=sys.stderr)
        for u in unresolved:
            print(f'  ✗ unresolved: {u["title"][:70]}', file=sys.stderr)
        return 0
    ph.set_defaults(func=_cmd_add_host_refs)

    pap = sub.add_parser('apply_partition',
                         help='Apply the host relevance-partition (Phase 0.4): stamp each '
                              'lit_results record with relevance=core|adjacent|off_topic from '
                              'relevance_partition.json, ARCHIVE off_topic records to off_topic.md '
                              'and drop them from the gap corpus, then write lit_results back. '
                              'Deterministic + idempotent (off_topic already removed on re-run).')
    pap.add_argument('--out', required=True, help='Phase 0 output dir (must contain lit_results.json)')
    pap.add_argument('--partition', required=True,
                     help='Path to relevance_partition.json: a list of '
                          '{paper_id, relevance: core|adjacent|off_topic, reason?}')
    def _cmd_apply_partition(args):
        out_dir = Path(args.out).resolve()
        lit_path = out_dir / 'lit_results.json'
        if not lit_path.exists():
            print(f'error: {lit_path} not found — run `phase0` first', file=sys.stderr)
            return 1
        try:
            part = json.loads(Path(args.partition).read_text())
        except Exception as e:
            print(f'error: could not parse --partition ({e})', file=sys.stderr)
            return 2
        if not isinstance(part, list):
            print('error: --partition must be a JSON list', file=sys.stderr)
            return 2
        # {paper_id -> relevance}. Unknown/blank labels default to core (never
        # silently drop a paper on a garbled label).
        rel_by_id, reason_by_id = {}, {}
        for e in part:
            pid = (e.get('paper_id') or e.get('id') or '').strip()
            if not pid:
                continue
            rel = str(e.get('relevance') or 'core').lower()
            rel_by_id[pid] = rel if rel in ('core', 'adjacent', 'off_topic') else 'core'
            reason_by_id[pid] = (e.get('reason') or '').strip()

        lit = json.loads(lit_path.read_text())
        papers = lit['papers'] if isinstance(lit, dict) and 'papers' in lit else lit
        kept, dropped = [], []
        for p in papers:
            pid = p.get('paper_id') or p.get('id') or ''
            # A paper the partition never labeled (e.g. host refs added later, or a
            # paper the host skipped) defaults to core so it is never lost here.
            rel = rel_by_id.get(pid, p.get('relevance') or 'core')
            p['relevance'] = rel
            if rel == 'off_topic':
                p['_off_topic_reason'] = reason_by_id.get(pid, '')
                dropped.append(p)
            else:
                kept.append(p)

        if isinstance(lit, dict) and 'papers' in lit:
            lit['papers'] = kept
            lit_path.write_text(json.dumps(lit, ensure_ascii=False, indent=2))
        else:
            lit_path.write_text(json.dumps(kept, ensure_ascii=False, indent=2))

        # Archive dropped off_topic papers (visible, not deleted) — append so a
        # re-run with a fresh partition never clobbers an earlier archive.
        if dropped:
            arch = out_dir / 'off_topic.md'
            lines = [] if arch.exists() else [
                '# Off-topic papers removed from the gap corpus (Phase 0.4 host partition)',
                '', 'These were retrieved by a connector but the host judged them outside the '
                'research direction (cross-domain "memory-augmented" false positives, surveys, '
                'unrelated fields). They are archived here for transparency but do NOT feed Phase '
                '1 or the deep-read pool.', '']
            for p in dropped:
                lines.append(f"- **{(p.get('title') or '')[:100]}** "
                             f"(`{p.get('paper_id') or p.get('id') or '?'}`)")
                r = p.get('_off_topic_reason')
                if r:
                    lines.append(f"  - {r}")
            with arch.open('a') as f:
                f.write('\n'.join(lines) + '\n')

        n_core = sum(1 for p in kept if p.get('relevance') == 'core')
        n_adj = sum(1 for p in kept if p.get('relevance') == 'adjacent')
        print(f'[apply_partition] {n_core} core + {n_adj} adjacent kept · '
              f'{len(dropped)} off_topic archived to off_topic.md', file=sys.stderr)

        # --- Per-query yield report ---
        # Join the relevance labels onto the connectors' `from_query` provenance — the
        # only place both halves exist. Turns "is this query worth its slot?" into a
        # per-run measurement instead of a judgement call.
        from collections import Counter as _C
        per_q: dict = {}
        for p in papers:                      # kept + dropped, i.e. everything retrieved
            for q in (p.get('from_query') or ['(unattributed)']):
                per_q.setdefault(q, _C())[p.get('relevance', 'core')] += 1
        if per_q and set(per_q) != {'(unattributed)'}:
            lines = ['# Per-query yield (Phase 0.4 labels joined onto retrieval provenance)',
                     '', 'A query whose share is mostly `off_topic` is spending guaranteed '
                     'round-robin slots on noise — drop or rephrase it next run (see the '
                     'VOCABULARY-OWNERSHIP TEST in references/intent-recognition.md). Papers '
                     'reachable from several queries are credited to each.', '',
                     '| query | core | adjacent | off_topic | on-topic share |',
                     '|---|---|---|---|---|']
            print('  per-query yield:', file=sys.stderr)
            for q, c in sorted(per_q.items(), key=lambda kv: -sum(kv[1].values())):
                tot = sum(c.values())
                share = (c['core'] + c['adjacent']) / tot if tot else 0
                lines.append(f"| {q} | {c['core']} | {c['adjacent']} | {c['off_topic']} | {share:.0%} |")
                flag = '   <-- mostly noise' if share < 0.5 else ''
                print(f"    {share:>4.0%} on-topic  ({c['core']}c/{c['adjacent']}a/"
                      f"{c['off_topic']}x)  {q[:52]}{flag}", file=sys.stderr)
            (out_dir / 'query_yield.md').write_text('\n'.join(lines) + '\n')
        return 0
    pap.set_defaults(func=_cmd_apply_partition)

    pn = sub.add_parser('next',
                        help='Run-state navigator: inspect the run dir\'s artifacts and print '
                             'EXACTLY the next step (a bash command, or an LLM sub-agent spec '
                             'with prompt/inputs/output paths). Read-only. The host loop is: '
                             '`next` → do what it says → `next` again, until a terminal state.')
    pn.add_argument('--dir', required=True, help='The run dir (the --out root all phases write under)')
    pn.add_argument('--query', default='', help='The user research question (only used to fill in the phase0 command hint)')
    def _cmd_next(args):
        from scripts.next_step import cmd_next
        return cmd_next(args)
    pn.set_defaults(func=_cmd_next)

    pv = sub.add_parser('validate', help='Run validators on phase outputs')
    pv.add_argument('--phase1', help='phase1_output.json path (required for V3 evidence-chain)')
    pv.add_argument('--phase2', help='phase2_output.json path (required for V2/V3/V4)')
    pv.add_argument('--phase3', help='phase3_critique_output.json path (required for V1)')
    pv.add_argument('--phase4', help='phase4_expansion_output.json path (required for V1)')
    pv.add_argument('--phase4-impl', dest='phase4_impl', help='phase4_implementability.json path (enables implementability_completeness)')
    pv.set_defaults(func=cmd_validate)

    args = ap.parse_args()
    # Guard every path-bearing arg against an unexpanded/empty run-dir variable
    # before any command runs — catches the #1 onboarding break up front with an
    # actionable message instead of a confusing FileNotFoundError mid-phase.
    for _attr in ('out', 'idea_json', 'expansion', 'implementability',
                  'phase1', 'phase2', 'phase3', 'phase4', 'phase4_impl',
                  'revisions', 'critique', 'candidate', 'phase2_select', 'phase3_critique',
                  'phase3_revise', 'phase0_dir', 'collision', 'partition',
                  'skeleton', 'fill_map', 'dir'):
        _val = getattr(args, _attr, None)
        if _val:
            _guard_project_path(_val, f'--{_attr.replace("_", "-")}')
    sys.exit(args.func(args))


if __name__ == '__main__':
    main()
