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
import shutil
import subprocess
import sys
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

# Per-connector role-based retrieval config for Phase 0 map mode.
# Each connector is used in the time window where it's most informative:
#   - arxiv = preprint pool (recent 0-6mo, where the field's active work is)
#   - openalex (published-only) = peer-reviewed proceedings + journals (6-24mo, broad academic graph; some drift)
#   - semanticscholar (published-only) = peer-reviewed CS-focused (6-24mo, low drift, plus TLDR auto-summary)
#   - openreview = current submission pool (0-6mo, in-review, forward-looking)
# Total target = ~40 papers (10 arxiv + 12+13 openalex/SS combined + 10 openreview).
# Falls back gracefully when a connector is unavailable.
PHASE0_CONNECTOR_CONFIG = {
    # arxiv 0-6mo: bump max_per_query because sortBy=relevance returns top-50 across all time;
    # only ~5-8% of relevance-ranked top-50 fall within 6 months for typical queries, so we cast
    # a wider net (200 per query) and filter to window. Total API calls per query is still 1.
    'arxiv':           {'window_min': 0, 'window_max': 6,  'max_results': 10, 'max_per_query': 200, 'extra_args': [], 'timeout': 300},
    'openalex':        {'window_min': 6, 'window_max': 24, 'max_results': 12, 'max_per_query': 25,  'extra_args': ['--published-only'], 'timeout': 300},
    'semanticscholar': {'window_min': 6, 'window_max': 24, 'max_results': 13, 'max_per_query': 25,  'extra_args': ['--published-only'], 'timeout': 300},
    # openreview iterates ~20k notes per venue × 3 venues; cannot early-stop on broad queries.
    # Per-query cost is 2-5 min; bumped to 600s to let multi-query batches finish.
    'openreview':      {'window_min': 0, 'window_max': 6,  'max_results': 10, 'max_per_query': 50,  'extra_args': [], 'timeout': 600},
}

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

def run_connector_subprocess(module_path: str, queries_json: str, window_max_months: int,
                             out_path: Path, label: str, timeout: int = 300,
                             window_min_months: int = 0, max_results: int = 0,
                             max_per_query: int = 0, extra_args: list[str] | None = None,
                             as_of: str = '') -> bool:
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
                    '"the LoRA paper") and write them to `user_refs.json` in out_dir, appending '
                    'to whatever URL/ID-based refs the regex pass already populated. Each title '
                    'entry: {"type": "title", "value": "<full title>", "raw_match": "<user phrasing>"}. '
                    'Skip this step if no titles are mentioned (URL/ID refs are handled by regex). '
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

    # Step 3: run each available connector in its role-specific time window.
    # See PHASE0_CONNECTOR_CONFIG for the per-connector window + cap rationale.
    queries_json = json.dumps(queries)
    hits_files = []
    successes = []
    for label, module_path in available:
        cfg = PHASE0_CONNECTOR_CONFIG.get(label)
        if cfg is None:
            print(f'  [skip] {label}: no PHASE0_CONNECTOR_CONFIG entry', file=sys.stderr)
            continue
        out_path = out_dir / f'{label}_phase0.json'
        extra_args = list(cfg.get('extra_args', []))
        # Semantic recall booster for OpenAlex only (the one connector with a working semantic-search
        # endpoint). ON by default: it adds conceptually-adjacent papers BM25 misses, field-gated to
        # the BM25 pool's home field(s), and is safe in Phase 0 because Phase 0 queries are topical.
        # A CLI flag the host LLM would have to opt into is effectively dead (the LLM won't flip it),
        # so the useful behavior is the default; --no-openalex-semantic is a human escape hatch.
        # Bump the connector timeout because the semantic endpoint is rate-limited to 1 req/s.
        timeout = cfg.get('timeout', 300)
        if not getattr(args, 'no_openalex_semantic', False) and label == 'openalex':
            extra_args = extra_args + ['--with-semantic']
            timeout = max(timeout, 600)
        ok = run_connector_subprocess(
            module_path, queries_json,
            window_max_months=cfg['window_max'],
            out_path=out_path,
            label=f'{label}_{cfg["window_min"]}-{cfg["window_max"]}mo',
            window_min_months=cfg['window_min'],
            max_results=cfg['max_results'],
            max_per_query=cfg.get('max_per_query', 0),
            extra_args=extra_args,
            timeout=timeout,
            as_of=as_of,
        )
        if ok:
            hits_files.append(out_path)
            successes.append(label)

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

    # Step 4: dedup_merge with priority-aware ordering. We pass hits_files in priority order
    # (highest-priority connector first) so that dedup_merge's first-wins semantics keep
    # the highest-priority record for any cross-source duplicate.
    hits_files_sorted = sorted(hits_files, key=lambda p: -DEDUP_PRIORITY.get(p.stem.replace('_phase0', ''), 0))
    merged_out = out_dir / 'lit_results.json'
    dedup_cmd = [sys.executable, '-m', 'scripts.dedup_merge', '--inputs'] + [str(f) for f in hits_files_sorted] + ['--out', str(merged_out)]
    r = subprocess.run(dedup_cmd, cwd=str(SUB), capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print(f'dedup_merge failed: {r.stderr[:600]}', file=sys.stderr)
        return 4

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
                'separate summary file needed.'
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

    # Build collision query from signature_terms. If the idea.json is missing them,
    # emit a sentinel for the host LLM to fill in (same pattern as Phase 0 intent extraction).
    # Falling back to [title, core_mechanism, novelty_claim] is dangerous because those are
    # long sentences that fail URL encoding at the connector layer (recurring Bug A pattern).
    sig = idea.get('signature_terms')
    if not sig:
        return emit_host_llm_sentinel(
            out_dir, step_name='signature_extraction',
            rubric_file=SUB / 'references' / 'intent-recognition.md',
            inputs={'idea_json': args.idea_json, 'mode': 'collision'},
            expected_outputs=['edit idea_json to add signature_terms[]'],
            instruction=(
                'Read the rubric file whose absolute path is in this sentinel\'s `rubric_file` '
                'field (Collision mode). Produce 3-5 signature_terms from the idea (mechanism + '
                'claim + setting + 1-2 specific identifiers, each 3-7 words). Add a '
                '`signature_terms` field to idea_json and re-invoke. Long sentences (title / '
                'core_mechanism / novelty_claim verbatim) fail URL encoding at the connector — '
                'keep terms tight.'
            ),
            re_invocation=f'python3 -m scripts.run phase3_collision --idea-json {args.idea_json} --out {out_dir}',
            exit_code=11,
        )
    queries_json = json.dumps([s for s in sig if s])
    hits_files = []
    for label, module_path in available:
        out_path = out_dir / f'{label}_collision.json'
        # Inherit per-connector timeout from PHASE0_CONNECTOR_CONFIG (notably: openreview gets 600s,
        # not the function-default 300s, since iterate-notes cost is the same in collision retrieval).
        timeout = PHASE0_CONNECTOR_CONFIG.get(label, {}).get('timeout', 300)
        ok = run_connector_subprocess(module_path, queries_json, 6, out_path, f'{label}_6mo', timeout=timeout, as_of=as_of)
        if ok:
            hits_files.append(out_path)

    if not hits_files:
        print('ERROR: all collision retrievals failed.', file=sys.stderr)
        return 3

    # Dedup-merge to a single collision_hits.json. Phase 3.1 = retrieval + dedup only;
    # Phase 3.2 audit's paper-pointed threat search does subsumption judgment.
    merged_out = out_dir / 'collision_hits.json'
    dedup_cmd = [sys.executable, '-m', 'scripts.dedup_merge', '--inputs'] + [str(f) for f in hits_files] + ['--out', str(merged_out)]
    subprocess.run(dedup_cmd, cwd=str(SUB), check=True, capture_output=True, text=True, timeout=120)

    # Slim collision_hits.json for the LLM-facing reader (Phase 3.2 audit). Full
    # abstracts (~1.5k chars x ~275 papers) blow the audit prompt to ~200k tokens;
    # the paper-pointed-threat search only needs title + a truncated abstract + ids.
    _COLLISION_ABSTRACT_CHARS = 800   # 0 = keep the full abstract
    _COLLISION_MAX_HITS = 0           # 0 = keep all hits; else cap to top-N by semantic_recall
    try:
        _hits = json.loads(merged_out.read_text())
        if _COLLISION_MAX_HITS:
            _hits = sorted(_hits, key=lambda x: -(x.get('semantic_recall') or 0))[:_COLLISION_MAX_HITS]
        _keep = ('title', 'paper_id', 'venue', 'year', 'tldr', 'semantic_recall', 'source')
        def _slim(h):
            o = {k: h[k] for k in _keep if h.get(k) is not None}
            a = h.get('abstract') or ''
            if a:
                o['abstract'] = a[:_COLLISION_ABSTRACT_CHARS] if _COLLISION_ABSTRACT_CHARS else a
            return o
        merged_out.write_text(json.dumps([_slim(h) for h in _hits], ensure_ascii=False, indent=1))
    except Exception as _e:  # never fail the phase on a slim hiccup
        print(f'collision_hits slim skipped: {_e}', file=sys.stderr)

    (out_dir / '.lit_grounding_mode').write_text('real')
    print(f'✅ Phase 3.1 collision retrieval complete. {merged_out.name} has {len(json.loads(merged_out.read_text()))} hits. retrieved at: {now.isoformat()}')
    return 0


# --- validators -------------------------------------------------------------

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
    pf.add_argument('--t3-top', type=int, default=5, help='How many top arxiv papers go into T3 (default 5)')
    pf.add_argument('--t2-top', type=int, default=10, help='How many top published-source papers go into T2 (default 10)')
    pf.add_argument('--max-pool', type=int, default=15, help='Hard ceiling on total fetches excluding user refs (default 15)')
    def _cmd_phase0_fulltext(args):
        from scripts.fetch_sections import select_candidate_pool, fetch_pool, reconcile_lit_table_ids
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
                                     max_pool=args.max_pool)
        n_u = sum(1 for p in pool if p['_tier'] == 'U')
        n_t2 = sum(1 for p in pool if p['_tier'] == 'T2')
        n_t3 = sum(1 for p in pool if p['_tier'] == 'T3')
        print(f'[phase0_fulltext] candidate pool: {len(pool)} papers ({n_u} U + {n_t2} T2 + {n_t3} T3)', file=sys.stderr)

        def _log(done, total, p, sections):
            pid = p.get('paper_id') or p.get('id') or 'unknown'
            title = (p.get('title') or '')[:80]
            status = sections['source_used']
            ok = 'OK' if status != 'failed' else 'FAIL'
            print(f'  [{done}/{total}] {p["_tier"]} {pid} {ok:5} {status:25} {title}', file=sys.stderr)

        cache = fetch_pool(pool, on_done=_log)

        cache_path = out_dir / 'fulltext_cache.json'
        cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False))
        n_ok = sum(1 for v in cache.values() if v['source_used'] != 'failed')
        print(f'\n  wrote {cache_path} ({n_ok}/{len(cache)} succeeded)', file=sys.stderr)
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
        status = sections['source_used']
        if status == 'failed':
            print(f'[topup] WARN anchor {pid} still failed across all paths — residue stays abstract-level; flag it', file=sys.stderr)
            return 0
        print(f'[topup] wrote {cache_path} — anchor {pid} now grounded via {status}', file=sys.stderr)
        return 0
    pt.set_defaults(func=_cmd_phase1_fulltext_topup)

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
    pas.add_argument('--fill-map', required=True,
                     help='Path to a JSON file with {field_path: value} entries authored by the LLM. '
                          'Each path is the SAME path syntax used in the TODO placeholders.')
    pas.add_argument('--out', required=True, help='Output dir for phase4_expansion.json.')
    def _cmd_phase4_assemble(args):
        from scripts.phase4_skeleton import assemble_expansion
        skeleton = json.loads(Path(args.skeleton).resolve().read_text())
        fill_map = json.loads(Path(args.fill_map).resolve().read_text())
        if not isinstance(fill_map, dict):
            print(f'ERROR: fill_map JSON must be an object {{path: value}}, got {type(fill_map).__name__}',
                  file=sys.stderr)
            return 1
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
    pm.add_argument('--out', required=True,
                    help='Output dir for final_candidate.json (typically the same dir as --revisions).')
    def _cmd_phase3_merge(args):
        from scripts.merge_revisions import merge_phase3_revisions
        try:
            final_path, _ = merge_phase3_revisions(
                Path(args.phase2).resolve(),
                Path(args.revisions).resolve(),
                Path(args.out).resolve(),
            )
        except ValueError as e:
            print(f'ERROR: {e}', file=sys.stderr)
            return 1
        print(f'✅ Phase 3.3 merge complete. Wrote {final_path}', file=sys.stderr)
        print(f'   Back-injected `final_candidate` into {args.revisions} for legacy consumers.', file=sys.stderr)
        return 0
    pm.set_defaults(func=_cmd_phase3_merge)

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
                  'revisions', 'candidate', 'phase2_select', 'phase3_critique',
                  'phase3_revise', 'phase0_dir', 'collision',
                  'skeleton', 'fill_map'):
        _val = getattr(args, _attr, None)
        if _val:
            _guard_project_path(_val, f'--{_attr.replace("_", "-")}')
    sys.exit(args.func(args))


if __name__ == '__main__':
    main()
