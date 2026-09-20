"""`next` subcommand — the run-state navigator.

Why this exists:
  Without it, the host LLM must hold the whole SKILL.md phase graph in context
  to know what to do after each artifact lands (which command, which system
  prompt, which inputs, where the output goes, which branch after a revise /
  abandon verdict). That is (a) ~17k tokens of standing context and (b) the
  main source of mis-runs (skipped fulltext gate, forgotten merger, missed
  re-audit). `next` inspects the artifacts on disk and prints EXACTLY one next
  step. The host's loop degenerates to: run `next` → do what it says → run
  `next` again.

  `next` is READ-ONLY: it never creates, moves, or deletes run artifacts (the
  one exception: it runs the deterministic in-process citation validator on the
  Phase 2.2 output, which is pure). All mutating steps are printed as commands
  for the host to run.

Usage:
  python3 "$SKILL_DIR/scripts/run.py" next --dir "$RUN_DIR" [--query "<user question>"]
"""
from __future__ import annotations
import json
import os
import re
import sys
from pathlib import Path

# Sub-agent boilerplate shared by every LLM step. Kept short: the phase prompt
# itself carries the full contract; this is just the context-discipline frame.
_SUBAGENT_FRAME = (
    'Run in a FRESH sub-agent (never the parent context): pass ONLY the file '
    'paths below, have it Write the output JSON to the exact output path '
    '(direct file-write tool — no heredoc, no inline JSON in the reply), and return <=250 '
    'words: output path + the routing signal named in NOTES.'
)


def _p(label: str, body: str) -> None:
    print(f'{label:7s}: {body}')


def _emit(state: str, step: str, kind: str, *, run: list[str] | None = None,
          prompt: str | None = None, inputs: list[str] | None = None,
          output: str | None = None, notes: str | None = None,
          then: bool = True, run_dir: Path | None = None) -> int:
    print('━' * 72)
    _p('STATE', state)
    _p('STEP', step)
    _p('TYPE', kind)
    if kind == 'llm_subagent':
        print(f'DO     : {_SUBAGENT_FRAME}')
        if prompt:
            _p('PROMPT', prompt)
        for i, item in enumerate(inputs or []):
            if i == 0:
                _p('INPUT', item)
            else:
                print(f'         {item}')
        if output:
            _p('OUTPUT', output)
    for i, cmd in enumerate(run or []):
        if i == 0:
            _p('RUN', cmd)
        else:
            print(f'         {cmd}')
    if notes:
        _p('NOTES', notes)
    if then and run_dir is not None:
        _p('THEN', f'python3 "{Path(__file__).resolve().parent.parent}/scripts/run.py" next --dir "{run_dir}"')
    print('━' * 72)
    return 0


def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None



def _attempt_dirs(d: Path) -> list:
    """Archived gauntlet attempts, ordered by index (attempt_1, attempt_2, ...)."""
    out = []
    for p in d.iterdir() if d.exists() else []:
        if p.is_dir() and p.name.startswith('attempt_') and p.name[8:].isdigit():
            out.append(p)
    return sorted(out, key=lambda p: int(p.name[8:]))


def _rejected_count(phase_dir: Path) -> int:
    """How many non-compliant reports this phase has already had archived.

    `next` is read-only, so a bounce cannot increment a counter itself: each
    bounce emit carries a RUN command that ARCHIVES the offending report into
    `rejected_<n>/`, and the count is read back off disk here. Archiving also
    keeps the rejected reports for forensics instead of overwriting them.
    """
    if not phase_dir.exists():
        return 0
    return len([x for x in phase_dir.iterdir()
                if x.is_dir() and x.name.startswith('rejected_')])


def _lessons(doc: dict) -> set:
    """Extract the LESSON SET of one audit report: every binding piece of
    information a failed attempt produced, as (kind, normalized-id) pairs.
    Retry routing is information-gain over these sets — a retry is justified
    only by lessons the previous generation did not have. Kinds:
      finding — upheld executed blocking finding (mechanism-level directive)
      threat  — unaddressable subsuming paper (mechanism-family negative anchor;
                REPEATED across attempts it binds at the framing level instead)
      reject / anti / recipe — generation-quality lessons (negative constraints)
    """
    ls = set()
    for dd in doc.get('blocking_findings_disposition') or []:
        if isinstance(dd, dict) and dd.get('status') == 'upheld':
            ls.add(('finding', str(dd.get('finding_ref', ''))[:40]))
    t = doc.get('paper_pointed_threat') or {}
    if t.get('addressable_via') == 'unaddressable':
        ls.add(('threat', str(t.get('threat_paper_id')
                              or t.get('subsumption_argument') or '')[:60]))
    for e in (doc.get('gap_closure_reject_check') or {}).get('entries') or []:
        for l in (e.get('reject_lessons_evaluated') or []):
            if str(l.get('candidate_match', '')).lower() in ('yes', 'true'):
                ls.add(('reject', str(l.get('lesson_quoted', ''))[:60]))
    ap = doc.get('anti_pattern_check') or {}
    mp = ap.get('matched_pattern_id')
    if mp and str(mp).lower() not in ('none', 'null') and             str(ap.get('mitigation_substantively_delivered', '')).lower() not in ('yes', 'true'):
        ls.add(('anti', str(mp)[:40]))
    rc = doc.get('recipe_application_check') or {}
    if rc.get('verdict') == 'bypassed':
        tagged = False
        for e in rc.get('entries') or []:
            if str(e.get('verdict', '')).lower() == 'bypassed':
                ls.add(('recipe', str(e.get('sub_pattern', ''))[:40])); tagged = True
        if not tagged:
            ls.add(('recipe', 'bypassed'))
    return ls


def _retrieval_next_step(run_dir: Path, root: Path, query: str | None = None, emit=None) -> int:
    _emit = emit or globals()['_emit']
    """Inspect run_dir artifacts and print the single next step. Returns 0."""
    d = run_dir
    ref = root / 'references'
    prompts = ref / 'system-prompts'
    # Host-agnostic invocation: run.py self-locates its skill root, so the
    # absolute-script-path form works from ANY working directory.
    skill_cd = f'python3 "{root}/scripts/run.py" '
    q = query or '<user research question>'

    # ---- terminal states -----------------------------------------------------
    if (d / 'do_not_generate.md').exists():
        return _emit('TERMINAL — Phase 1 routed to do_not_generate.',
                     'Surface do_not_generate.md to the user', 'terminal',
                     notes=f'Return {d}/do_not_generate.md contents as the final response. '
                           'No further phases run.', then=False)
    if (d / 'phase_3_failed.md').exists():
        return _emit('TERMINAL — Phase 3 audit abandoned (retry budget exhausted).',
                     'Surface phase_3_failed.md to the user', 'terminal',
                     notes=f'Return {d}/phase_3_failed.md contents as the final response.',
                     then=False)
    cards = [d / 'phase4' / n for n in ('idea.std.zh.md', 'idea.std.en.md', 'idea.detail.en.md')]
    if all(c.exists() for c in cards):
        return _emit('DONE — all three idea cards rendered.',
                     'Return the cards inline', 'terminal',
                     notes='Read all three files and return them as the final response under '
                           'headings 中文版 / English / Reviewer version: '
                           + ', '.join(str(c) for c in cards), then=False)

    p0 = d / 'phase0'

    # ---- Phase 0 -------------------------------------------------------------
    if (p0 / '.intent_extraction_pending').exists() and not (p0 / 'lit_results.json').exists():
        sent = _read_json(p0 / '.intent_extraction_pending') or {}
        return _emit('Phase 0 stalled on the intent-extraction sentinel.',
                     'Produce queries and re-invoke phase0', 'llm_subagent',
                     prompt=str(sent.get('rubric_file', ref / 'intent-recognition.md')) + ' (Map mode)',
                     inputs=[str(p0 / '.intent_extraction_pending')],
                     output='re-invoke: ' + str(sent.get('re_invocation', 'phase0 --queries "q1|q2|q3"')),
                     notes='This sentinel path only appears when phase0 was launched without '
                           '--queries. The DEFAULT flow avoids it (see the phase0 step).',
                     run_dir=d)
    if not (p0 / 'lit_results.json').exists():
        return _emit('Fresh run — no literature retrieved yet.',
                     'Phase 0: produce queries FIRST, then run retrieval', 'llm_subagent',
                     prompt=str(ref / 'intent-recognition.md') + ' (Map mode — read it yourself, no sub-agent needed for query writing)',
                     inputs=['the user query'],
                     output='(a) 4 search queries (3-5 only with a stated reason) — incl. one ESCAPE-MECHANISM '
                            'query in the vocabulary THIS FIELD itself uses for that solution; caps saturate and '
                            'the merge is round-robin, so an extra low-yield query spends slots instead of adding '
                            'coverage. (b) named_papers: every paper/system the user NAMED but gave no link for '
                            '— you are already reading the query, so list them in the same pass',
                     run=[skill_cd + f'phase0 --query "{q}" '
                          f'--queries "q1|q2|q3|q4" '
                          f'--named-papers "Title A|Title B" --out "{d}/phase0/"'],
                     notes='Passing --queries up front skips a full sentinel round-trip (rc=10). '
                           'Retrieval takes 3-10 min (openreview alone budgets 600s) — set your '
                           'Bash timeout >= 600s or run in background. `--named-papers` is how a '
                           'name-dropped system reaches the U fetch tier: the URL/ID regex only sees '
                           'links, so a paper the user named in prose is otherwise invisible to every '
                           'later phase and never becomes an anchor. Drop the flag when the query names '
                           'none. To add one AFTER this step, use add_user_ref (entry-point table) — do '
                           'NOT hand-edit user_refs.json, some harnesses refuse to overwrite files never '
                           'read. OOD short-circuit: if the query matches intake-routing.md '
                           'trigger #1/#2, skip retrieval and go straight to Phase 1 with a '
                           'do_not_generate routing.',
                     run_dir=d)
    # ---- Phase 0.4 host relevance-partition (precision gate before tagging) ----
    # Retrieval casts a wide net, so the host first partitions the raw pool into
    # core|adjacent|off_topic on title+abstract. off_topic is archived and dropped
    # from the gap corpus; only `core` feeds the deep-read pool; adjacent stays a
    # citeable baseline. Runs BEFORE tagging so the per-paper pass only sees
    # survivors. Disable with IDEASPARK_RELEVANCE_PARTITION=off.
    partition_on = os.environ.get('IDEASPARK_RELEVANCE_PARTITION', '').lower() not in ('off', '0', 'false')
    part_file = p0 / 'relevance_partition.json'
    part_done = (p0 / '.partition_applied').exists()
    if partition_on and not part_done and not (p0 / 'lit_table.md').exists():
        if not part_file.exists():
            return _emit('Papers retrieved; running the relevance partition before tagging.',
                         'Phase 0.4 — relevance partition (core / adjacent / off_topic)',
                         'llm_subagent',
                         prompt=str(ref / 'relevance-partition-rubric.md'),
                         inputs=[str(p0 / 'user_query.txt') + " (the USER'S ORIGINAL research question, verbatim)",
                                 str(p0 / 'lit_results.json')],
                         output=str(part_file),
                         notes='Use YOUR OWN model (open-ended relevance judgment — do NOT '
                               'downgrade). Read every record\'s title+abstract and label each '
                               'paper_id core|adjacent|off_topic (+ one-line reason). BE '
                               'CONSERVATIVE: when unsure between core and adjacent pick core; '
                               'hard-label off_topic ONLY when the paper is clearly outside the '
                               'research direction (cross-domain "memory-augmented" false '
                               'positives — wireless / recommendation / NLP — pure surveys, '
                               'unrelated fields). Write a JSON list [{paper_id, relevance, '
                               'reason}]; every record appears exactly once. This is the one '
                               'precision pass — off_topic is dropped from the corpus next.',
                         run_dir=d)
        return _emit('Relevance partition written; applying it (archive off_topic, stamp relevance).',
                     'Phase 0.4 — apply partition (deterministic)', 'bash',
                     run=[skill_cd + f'apply_partition --out "{p0}/" --partition "{part_file}"'
                          + f'  &&  touch "{p0 / ".partition_applied"}"'],
                     notes='off_topic records are archived to off_topic.md and removed from '
                           'lit_results.json; core/adjacent get a relevance stamp. Tagging then '
                           'runs only on the survivors. Marker guards re-runs.',
                     run_dir=d)
    if not (p0 / 'lit_table.md').exists():
        return _emit('Papers retrieved; lit_table.md not yet written.',
                     'Phase 0 pattern_summary (host-LLM step)', 'llm_subagent',
                     prompt=str(ref / 'pattern-summary-rubric.md'),
                     inputs=[str(p0 / 'lit_results.json')],
                     output=str(p0 / 'lit_table.md'),
                     notes='Pure classification — no large reasoning model needed: DEFAULT to '
                           'a cheaper/faster model tier or lower reasoning effort for this '
                           'step (the NOVELTY_LLM_CLASSIFY_FAST_CMD tier); fall back to the '
                           'host model isolated only when no cheaper tier exists. Tag each paper with '
                           '1-3 of the 15 patterns + bottleneck + open_issue + retrieved_via '
                           'per the rubric. Rows are per-paper independent, so for 40+ papers '
                           'you MAY shard across 2-3 parallel fast-tier sub-agents (contiguous '
                           'slices, mechanically concatenated in input order; verify total row '
                           'count == paper count before accepting). Routing signal: none (just the file).',
                     run_dir=d)
    # ---- Phase 0.5 coverage check (host-recall补充通道) --------------------------
    # After tagging and before fulltext: the host, having read the whole table,
    # names load-bearing work the retrieval pool obviously missed; add_host_refs
    # VERIFIES each via a connector (hallucinations rejected) and merges the real
    # records into lit_results with retrieved_via=host_*. Three sub-states, one
    # marker (.coverage_check_done). Disable with IDEASPARK_COVERAGE_CHECK=off.
    coverage_on = os.environ.get('IDEASPARK_COVERAGE_CHECK', '').lower() not in ('off', '0', 'false')
    cov_done = (p0 / '.coverage_check_done').exists()
    noms = p0 / 'host_refs_nominations.json'
    host_refs = p0 / 'host_refs.json'
    if coverage_on and not cov_done and not (p0 / 'fulltext_cache.json').exists():
        if not noms.exists():
            return _emit('lit_table.md written; running the coverage check before fulltext.',
                         'Phase 0.5 — coverage check (name load-bearing work the pool missed)',
                         'llm_subagent',
                         inputs=[str(p0 / 'user_query.txt') + " (the USER'S ORIGINAL research question, verbatim)",
                                 str(p0 / 'lit_table.md')],
                         output=str(noms),
                         notes='Use YOUR OWN model (open-ended judgment, do NOT downgrade). Read the '
                               'whole table against the user\'s direction and list up to 8 clearly '
                               'load-bearing works that are ABSENT. PRIORITIZE the last ~12 months: '
                               'recent/frontier work the dated retrieval windows likely under-sampled '
                               'is the primary target — recovering it is why this channel exists, and '
                               'it is what keeps the diagnosed gap current. Older foundational papers '
                               '(canonical base policies, >12-month landmarks) are mostly Phase 1 '
                               'lineage\'s job, not the corpus: nominate one ONLY when it is a '
                               'load-bearing backbone/baseline the candidate will literally build on '
                               'or be measured against, and keep such older picks to a small minority '
                               'of the list. WebSearch is allowed HERE ONLY, and only to find TITLES '
                               '— never to fabricate a record. Write a JSON list [{title, '
                               'id_hint?(arxiv/DOI/URL), why(one line — state the recency, or the '
                               'load-bearing-baseline reason if older), relevance(core|adjacent: '
                               'core = a recent mechanism paper worth deep-reading; adjacent = a '
                               'foundational backbone/baseline to cite but NOT deep-read), '
                               'source: parametric|websearch}]. '
                               'An empty list [] is a valid, honest output (the pool was already '
                               'complete). Every nomination is verified by a connector next — '
                               'unresolvable titles are rejected, not trusted.',
                         run_dir=d)
        if not host_refs.exists():
            return _emit('Coverage nominations written; resolving them via the connectors.',
                         'Phase 0.5 — resolve + merge host refs (deterministic)', 'bash',
                         run=[skill_cd + f'add_host_refs --out "{p0}/" --refs "{noms}"'],
                         notes='Each nomination is looked up via Semantic Scholar / arXiv; only '
                               'title-verified records (>=0.9 match) enter lit_results with '
                               'retrieved_via=host_recall|host_web. Unresolved titles land in '
                               'host_refs_unresolved.md and are NOT admitted.',
                         run_dir=d)
        # host refs resolved: tag any newly-admitted rows into lit_table, else finalize.
        admitted = _read_json(host_refs) or []
        lit_txt = (p0 / 'lit_table.md').read_text() if (p0 / 'lit_table.md').exists() else ''
        new_ids = [r.get('paper_id') for r in admitted
                   if r.get('paper_id') and r.get('paper_id') not in lit_txt]
        if new_ids:
            return _emit(f'{len(new_ids)} host-recall paper(s) admitted; tag them into lit_table.',
                         'Phase 0.5 — tag the admitted host refs', 'llm_subagent',
                         prompt=str(ref / 'pattern-summary-rubric.md'),
                         inputs=[str(p0 / 'lit_results.json') + f' (tag ONLY these newly-admitted '
                                 f'paper_ids: {", ".join(new_ids)})'],
                         output=str(p0 / '_host_rows.md') + ' (the new rows only, 9-column format)',
                         run=None,
                         notes='Fast tier. Produce one lit_table row per newly-admitted paper_id '
                               '(same 9 columns), then merge + mark done: '
                               + skill_cd + f'lit_table_merge --out "{p0}/" --shards '
                               f'"{p0 / "lit_table.md"}" "{p0 / "_host_rows.md"}"  &&  '
                               f'touch "{p0 / ".coverage_check_done"}"',
                         run_dir=d)
        return _emit('Coverage check complete (no new admissions); marking done.',
                     'Phase 0.5 — finalize coverage check', 'bash',
                     run=[f'touch "{p0 / ".coverage_check_done"}"'],
                     notes='No host refs were admitted (empty nomination, all unresolved, or all '
                           'already present). Marker prevents re-running on resume.',
                     run_dir=d)

    if not (p0 / 'fulltext_cache.json').exists():
        return _emit('lit_table.md written; full-text cache missing (Phase 1 hard-gates on it).',
                     'Phase 0+ full-text fetch', 'bash',
                     run=[skill_cd + f'phase0_fulltext --out "{d}/phase0/"'],
                     notes='LAST CALL for user refs: title-named papers must be registered '
                           '(add_user_ref) BEFORE this step — the fetch pool\'s U/H tiers read '
                           'user_refs.json / host_refs.json now.',
                     run_dir=d)

    # ---- Phase 1 -------------------------------------------------------------
    p1 = d / 'phase1' / 'phase1_output.json'
    if not p1.exists():
        # Standing user compute default (.env is auto-loaded by run.py): surfaced
        # here so the Phase 1 sub-agent receives it as intake context. Precedence
        # inside Phase 1: user query > this value > factory default.
        user_compute = os.environ.get('IDEASPARK_DEFAULT_COMPUTE', '').strip()
        ft_cache_line = str(p0 / 'fulltext_cache.json')
        if (p0 / 'fulltext' / 'index.json').exists():
            ft_cache_line += (' — cheaper access: read ' + str(p0 / 'fulltext' / 'index.json') +
                              ' first (per-paper split view with tier/source_used/warning), then open '
                              'only the candidate-pool papers\' .md files; the .json blob stays canonical')
        p1_inputs = [str(p0 / 'user_query.txt') + ' (the user question, verbatim) + intake context',
                     str(p0 / 'lit_table.md'),
                     ft_cache_line,
                     str(p0 / 'lit_results.json')]
        if user_compute:
            p1_inputs.insert(1, f'standing user compute default (IDEASPARK_DEFAULT_COMPUTE, '
                                f'overrides factory default; user query still wins): "{user_compute}"')
        _ph1_arch = None
        if (d / '.bottleneck_retry_used').exists():
            for _a in reversed(_attempt_dirs(d)):
                if (_a / 'phase1' / 'phase1_output.json').exists():
                    _ph1_arch = _a
                    break
        if _ph1_arch is not None:
            _crits = ' and '.join(
                str(_a / 'phase3_critique' / 'phase3_critique_output.json')
                for _a in _attempt_dirs(d)
                if (_a / 'phase3_critique' / 'phase3_critique_output.json').exists())
            p1_inputs.append(
                'BOTTLENECK-RETRY MODE (see the OPTIONAL bottleneck-retry input in '
                'bottleneck_identify.txt) — negative anchors: '
                + str(_ph1_arch / 'phase1' / 'phase1_output.json')
                + ' (the RETIRED bottleneck_statement + anchor; do not re-frame it), plus '
                + _crits
                + ' (read ONLY paper_pointed_threat from each — the papers that killed the '
                  'archived attempts define occupied ground)')
        return _emit('Phase 0 complete.', 'Phase 1 — bottleneck identification', 'llm_subagent',
                     prompt=str(prompts / 'bottleneck_identify.txt'),
                     inputs=p1_inputs,
                     output=str(p1),
                     notes='Routing signal to return: `state` (proceed | do_not_generate). '
                           'If do_not_generate: write ' + str(d / 'do_not_generate.md') +
                           ' with the remedial steps and stop.',
                     run_dir=d)
    p1_doc = _read_json(p1) or {}
    if p1_doc.get('state') == 'do_not_generate':
        return _emit('Phase 1 routed to do_not_generate but do_not_generate.md is missing.',
                     'Write do_not_generate.md', 'llm_subagent',
                     inputs=[str(p1)],
                     output=str(d / 'do_not_generate.md'),
                     notes='Render the Phase 1 OOD rationale + remedial_steps as markdown; '
                           'that file is the run\'s final output.',
                     run_dir=d)

    # Phase 1 says proceed: everything from candidate generation on belongs to the quality flow
    # (scripts/quality_flow.py), which `next` enters through the run contract.
    return _emit('Phase 1 complete (state=proceed).', 'Run `next` again: the quality flow takes over', 'terminal',
                 notes='Retrieval and bottleneck identification are done for this directory.', then=False, run_dir=d)


def next_step(run_dir: Path, root: Path, query: str | None = None) -> int:
    from scripts.quality_flow import navigate
    return navigate(run_dir, root, query, _emit, _retrieval_next_step)


def cmd_next(args) -> int:
    run_dir = Path(args.dir).resolve()
    # A missing run dir is NOT an error: `next` is read-only, and nothing on disk
    # means nothing has run — exactly the Phase 0 emit below. Returning rc=2 here
    # made a normal first call fatal for any host that inspects before creating the
    # directory. `phase0` mkdir -p's its own --out, so none is needed before step 1;
    # malformed/unexpanded --dir is still caught by _guard_project_path.
    if not run_dir.exists():
        print(f'note: run dir {run_dir} does not exist yet — treating this as a fresh '
              f'run. The Phase 0 command below creates it (`--out` is mkdir -p\'d). '
              f'Convention: $PWD/ideaspark_run/<topic-slug>, one run per dir; never '
              f'reuse a dir that already has a phase0/.', file=sys.stderr)
    root = Path(__file__).resolve().parent.parent
    return next_step(run_dir, root, getattr(args, 'query', None) or None)
