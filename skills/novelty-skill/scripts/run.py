"""NoveltySkill orchestrator.

Why this script exists:
  Phase 0 (literature grounding) and Phase 3 Step 3.1 (collision check) must run
  via the sub-skill `novelty-lit-search`'s API connectors — NOT via WebSearch
  fallback or model-knowledge inline retrieval. This orchestrator is the
  canonical Bash entry point that subprocess-invokes the sub-skill's connector
  scripts directly, bypassing any Skill-tool indirection that could leave the
  model room to substitute WebSearch.

Design rationale (from the SKILL.md design doc):
  Skills are advisory — when SKILL.md says "use the sub-skill at Phase 0", the
  model still has multiple paths it can take (Skill tool, direct Bash, WebSearch
  simulation, fetch arxiv URL). Each is "satisfying the spirit" of Phase 0.
  Soft rules don't reliably prevent tool drift. The orchestrator collapses the
  choice space: SKILL.md Phase 0 says "run THIS Bash command" — model has only
  one path or must explicitly admit failure. Coupled with Phase 1's entry
  assertion (lens_probe.txt checks lit_grounding_mode + retrieved_via), bypass
  becomes mechanically detectable, not just discouraged.

CLI:
  # Phase 0 — literature grounding (map mode)
  python -m scripts.run phase0 --query "<research question>" --out outputs/phase0/

  # Phase 3 Step 3.1 — collision check
  python -m scripts.run phase3_collision --idea-json outputs/phase2_winner.json --out outputs/phase3_collision/

  # Optional: explicit web-fallback (for environments with no connectors)
  python -m scripts.run phase0 --query "..." --allow-webfallback

  # Sanity check connectors before running anything
  python -m scripts.run check_connectors

Outputs (Phase 0):
  outputs/phase0/lit_results.json         — ~30 deduped papers (role-based retrieval target)
  outputs/phase0/lit_table.md             — paper-level evidence table (methodology tags + bottleneck + open_issue)
  outputs/phase0/.lit_grounding_mode      — sentinel file: "real" | "webfallback" | "connector_failure"

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
SUB = ROOT.parent / 'novelty-lit-search'

# Connectors: (label, module_path_in_subskill, requires_env_keys, requires_pip_packages)
CONNECTORS = [
    ('arxiv',      'scripts.search_arxiv',      [],                                ['feedparser']),
    ('dblp',       'scripts.search_dblp',       [],                                []),
    ('openalex',   'scripts.search_openalex',   [],                                []),  # OPENALEX_API_KEY optional (polite pool works without)
    ('openreview', 'scripts.search_openreview', ['OPENREVIEW_USER', 'OPENREVIEW_PASS'], ['openreview']),
]

# Per-connector role-based retrieval config for Phase 0 map mode.
# Each connector is used in the time window where it's most informative:
#   - arxiv = preprint pool (recent 0-4mo, where the field's active work is)
#   - dblp + openalex (published-only) = peer-reviewed proceedings (4-24mo, venue-validated work)
#   - openreview = current submission pool (0-6mo, in-review, forward-looking)
# Total target = ~40 papers (10 arxiv + 20 dblp/openalex combined + 10 openreview).
# Falls back gracefully when a connector is unavailable (e.g., openreview has no creds → 30 papers total).
PHASE0_CONNECTOR_CONFIG = {
    # arxiv 0-4mo: bump max_per_query because sortBy=relevance returns top-50 across all time;
    # only ~5% of relevance-ranked top-50 fall within 4 months for typical queries, so we cast
    # a wider net (200 per query) and filter to window. Total API calls per query is still 1.
    'arxiv':      {'window_min': 0, 'window_max': 4,  'max_results': 10, 'max_per_query': 200, 'extra_args': []},
    'openalex':   {'window_min': 4, 'window_max': 24, 'max_results': 15, 'max_per_query': 25,  'extra_args': ['--published-only']},
    'dblp':       {'window_min': 4, 'window_max': 24, 'max_results': 15, 'max_per_query': 50,  'extra_args': []},
    'openreview': {'window_min': 0, 'window_max': 6,  'max_results': 10, 'max_per_query': 50,  'extra_args': []},
}

# Dedup priority when the same paper appears in multiple connectors.
# Higher priority means: keep this connector's record, drop the others.
# DBLP wins because it has the strongest venue-validation signal (and no abstract — combined records get the abstract from openalex anyway via merge).
# Then openalex (peer-reviewed metadata) > openreview (in-review) > arxiv (preprint).
DEDUP_PRIORITY = {'dblp': 4, 'openalex': 3, 'openreview': 2, 'arxiv': 1}


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
    if not any_available:
        print('\nERROR: no connector is available. Install at least one:')
        print('  pip install feedparser  # arxiv (always works without key)')
        print('  pip install openreview-py + export OPENREVIEW_USER / OPENREVIEW_PASS')
        return 1
    print(f'\nProceed with the available connectors above; missing ones will be skipped.')
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
            f'Set TZ correctly or run with --as-of YYYY-MM-DD to override.'
        )
    if now > ceiling:
        print(f'WARNING: system clock returns {now.isoformat()}; window arithmetic will use this. '
              f'Verify intentional.', file=sys.stderr)
    return now


# --- Phase 0 orchestrator --------------------------------------------------

def run_connector_subprocess(module_path: str, queries_json: str, window_max_months: int,
                             out_path: Path, label: str, timeout: int = 300,
                             window_min_months: int = 0, max_results: int = 0,
                             max_per_query: int = 0, extra_args: list[str] | None = None) -> bool:
    # Resolve out_path to absolute — subprocess runs with cwd=SUB (sub-skill dir),
    # so relative paths from the parent skill's invocation site would resolve against
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
    # Resolve out_dir to absolute so all downstream paths passed to subprocesses
    # (which run with cwd=SUB) resolve against the user's invocation site, not SUB.
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

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
                    'Read intent-recognition.md (Map mode). Produce 3-5 search queries '
                    'from user_query per rubric: query 1 broad-domain, query 2 method-signature, '
                    'query 3 most-similar-problem, optional query 4 application-angle, optional '
                    'query 5 venue-insider. Apply the OOD short-circuit: if user_query matches '
                    'intake-routing.md trigger #1 (Too broad) or #2 (No anchor), return '
                    '{"ood": true, "trigger_id": ..., "trigger_quote": ..., "match_evidence": ...} '
                    'instead of queries — Phase 1 will emit do_not_generate.'
                ),
                re_invocation=f'python -m scripts.run phase0 --query "{args.query}" --queries "q1|q2|q3|..." --out {out_dir}',
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
              'Install at least one connector (`python -m scripts.run check_connectors` for diagnostic).\n'
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
        ok = run_connector_subprocess(
            module_path, queries_json,
            window_max_months=cfg['window_max'],
            out_path=out_path,
            label=f'{label}_{cfg["window_min"]}-{cfg["window_max"]}mo',
            window_min_months=cfg['window_min'],
            max_results=cfg['max_results'],
            max_per_query=cfg.get('max_per_query', 0),
            extra_args=cfg.get('extra_args', []),
        )
        if ok:
            hits_files.append(out_path)
            successes.append(label)

    if not hits_files:
        print('\nERROR: connectors probed OK but all retrieval calls failed.\n'
              'Check API quotas, network, or per-connector errors above.', file=sys.stderr)
        return 3

    # Detect partial published-source coverage (informational, not blocking):
    # if both dblp + openalex failed but at least one of arxiv/openreview worked,
    # the published-window (4-24mo peer-reviewed) is empty. Currently informational;
    # downstream can decide whether to downgrade lit_grounding_mode.
    published_succeeded = any(s in successes for s in ('dblp', 'openalex'))
    if not published_succeeded:
        print(f'\nNOTE: no published-source connector succeeded (dblp + openalex both unavailable). '
              f'Phase 0 ran on preprint-only sources ({", ".join(successes)}); '
              f'4-24mo peer-reviewed window is empty. Phase 1 will see preprint-only evidence.',
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
                'lit_table_columns': ['paper_id', 'year_month', 'venue', 'title', 'methodology tags',
                                      'bottleneck this paper targets', 'open issue / unresolved gap',
                                      'resolves_problem', 'retrieved_via'],
            },
            expected_outputs=['lit_table.md'],
            instruction=(
                'Read pattern-summary-rubric.md, classify each paper from lit_results into 1-3 of '
                'the 13 methodologies, tag bottleneck_targeted / open_issue / resolves_problem per '
                'the rubric (resolves_problem is high-bar; ≤5% of papers — leave empty otherwise). '
                'Render lit_table.md only (columns per inputs). The methodology distribution and '
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
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    idea = json.loads(Path(args.idea_json).read_text())

    # Probe connectors (collision uses arxiv + openalex + openreview; skip dblp)
    available = []
    for label, module_path, env_keys, pkgs in CONNECTORS:
        if label == 'dblp':
            continue  # collision skips DBLP
        ok, reason = check_connector(label, module_path, env_keys, pkgs)
        if ok:
            available.append((label, module_path))
        else:
            print(f'  [skip] {label}: {reason}', file=sys.stderr)

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
                'Read intent-recognition.md (Collision mode). Produce 3-5 signature_terms from '
                'the idea (mechanism + claim + setting + 1-2 specific identifiers, each 3-7 words). '
                'Add a `signature_terms` field to idea_json and re-invoke. Long sentences '
                '(title / core_mechanism / novelty_claim verbatim) fail URL encoding at the '
                'connector — keep terms tight.'
            ),
            re_invocation=f'python -m scripts.run phase3_collision --idea-json {args.idea_json} --out {out_dir}',
            exit_code=11,
        )
    queries_json = json.dumps([s for s in sig if s])
    hits_files = []
    for label, module_path in available:
        out_path = out_dir / f'{label}_collision.json'
        ok = run_connector_subprocess(module_path, queries_json, 6, out_path, f'{label}_6mo')
        if ok:
            hits_files.append(out_path)

    if not hits_files:
        print('ERROR: all collision retrievals failed.', file=sys.stderr)
        return 3

    # Dedup-merge to a single collision_hits.json. NO 7-class classification step —
    # classification was removed because Phase 3.2 audit's paper-pointed threat search
    # already does the substantive subsumption judgment over lit_table ∪ collision_hits.
    # Pre-classifying hits with a separate LLM call duplicated that work and added a
    # second verdict layer (collision_report.verdict vs critique.verdict) that contributed
    # noise without signal. New 3.1 = retrieval + dedup only.
    merged_out = out_dir / 'collision_hits.json'
    dedup_cmd = [sys.executable, '-m', 'scripts.dedup_merge', '--inputs'] + [str(f) for f in hits_files] + ['--out', str(merged_out)]
    subprocess.run(dedup_cmd, cwd=str(SUB), check=True, capture_output=True, text=True, timeout=120)

    (out_dir / '.lit_grounding_mode').write_text('real')
    print(f'✅ Phase 3.1 collision retrieval complete. {merged_out.name} has {len(json.loads(merged_out.read_text()))} hits. retrieved at: {now.isoformat()}')
    return 0


# --- validators -------------------------------------------------------------

def cmd_validate(args) -> int:
    """Run V1-V4 validators on the phase outputs the user provides."""
    from scripts.validators import run_all_validators
    findings = run_all_validators(
        phase1_path=args.phase1, phase2_path=args.phase2,
        phase3_path=args.phase3, phase4_path=args.phase4,
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

    p0 = sub.add_parser('phase0', help='Run Phase 0 literature grounding via sub-skill connectors')
    p0.add_argument('--query', required=True, help='User research question (free text)')
    p0.add_argument('--queries', default='', help='Pipe-separated query strings (skip intent extraction if provided)')
    p0.add_argument('--out', default='outputs/phase0', help='Output dir (default outputs/phase0/)')
    p0.add_argument('--allow-webfallback', action='store_true',
                    help='If no connector works, emit webfallback sentinel (output is flagged as model-recall-grounded rather than connector-grounded). DEFAULT: hard-fail.')
    p0.set_defaults(func=cmd_phase0)

    p3 = sub.add_parser('phase3_collision', help='Run Phase 3 Step 3.1 collision check via sub-skill connectors')
    p3.add_argument('--idea-json', required=True)
    p3.add_argument('--out', default='outputs/phase3_collision')
    p3.add_argument('--allow-webfallback', action='store_true')
    p3.set_defaults(func=cmd_phase3_collision)

    pc = sub.add_parser('check_connectors', help='Probe each connector and report availability')
    pc.set_defaults(func=cmd_check_connectors)

    pr = sub.add_parser('phase4_render', help='Render the Phase 4 expansion JSON into the idea-card PDF (templating only, no model call)')
    pr.add_argument('--expansion', required=True, help='Phase 4 expansion JSON path')
    pr.add_argument('--out', default='outputs/phase4', help='Output dir (default outputs/phase4/)')
    def _cmd_phase4_render(args):
        from scripts.render_pdf import render_one
        out_dir = Path(args.out).resolve(); out_dir.mkdir(parents=True, exist_ok=True)
        expansion = json.loads(Path(args.expansion).read_text())
        render_one(expansion, out_dir)
        return 0
    pr.set_defaults(func=_cmd_phase4_render)

    pv = sub.add_parser('validate', help='Run validators on phase outputs')
    pv.add_argument('--phase1', help='phase1_output.json path (required for V3 evidence-chain)')
    pv.add_argument('--phase2', help='phase2_output.json path (required for V2/V3/V4)')
    pv.add_argument('--phase3', help='phase3_reviewer_output.json path (required for V1)')
    pv.add_argument('--phase4', help='phase4_expansion_output.json path (required for V1)')
    pv.set_defaults(func=cmd_validate)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == '__main__':
    main()
