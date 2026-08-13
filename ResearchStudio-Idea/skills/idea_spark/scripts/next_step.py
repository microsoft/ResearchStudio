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


def next_step(run_dir: Path, root: Path, query: str | None = None) -> int:
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

    # ---- Phase 2 (2.1 + 2.2 in ONE sub-agent) --------------------------------
    p2s = d / 'phase2_select' / 'phase2_select_output.json'
    p2g = d / 'phase2_generate' / 'phase2_generate_output.json'
    retry_note = ''
    _atts = _attempt_dirs(d)
    if _atts:
        _att_crits = ' and '.join(
            str(_a / 'phase3_critique' / 'phase3_critique_output.json') for _a in _atts
            if (_a / 'phase3_critique' / 'phase3_critique_output.json').exists())
        if (d / '.bottleneck_retry_used').exists():
            # Post bottleneck re-diagnosis: the archived SELECTIONS belong to
            # retired bottleneck(s) (different gaps — context only, not binding),
            # but every attempt's threat papers stay hard negative constraints.
            retry_note = (' RETRY MODE (new bottleneck, ONE candidate attempt): also pass '
                          + _att_crits
                          + ' as negative constraints — their paper_pointed_threat papers must not '
                            'be re-collided with. The archived phase2 selections belong to the '
                            'RETIRED bottleneck: context only, not binding.')
        else:
            _parts = []
            for _a in _atts:
                for _rel in ('phase3_critique/phase3_critique_output.json',
                             'phase2_select/phase2_select_output.json'):
                    if (_a / _rel).exists():
                        _parts.append(str(_a / _rel))
            retry_note = (' RETRY MODE: also pass ' + ' and '.join(_parts) +
                          ' as negative constraints (see the OPTIONAL retry input in '
                          'ideate_select.txt); upheld blocking findings in ANY archived audit '
                          'are POSITIVE directives the new mechanism must confront.')
    # Cross-run mechanism dedup (soft): sibling run dirs under the same parent are
    # scanned for their canonical candidates, whose titles + signature terms ride
    # along as SOFT negative anchors — adjacent-direction runs otherwise silently
    # re-invent the same mechanism family (observed live: two runs converged on the
    # same held-out-Shapley family). Read-only, capped at the 5 most recent, and
    # soft by design (a direction may legitimately demand a related mechanism —
    # then the delta must be explicit). Disable with IDEASPARK_CROSS_RUN_DEDUP=off.
    crossrun_line = None
    if os.environ.get('IDEASPARK_CROSS_RUN_DEDUP', '').lower() not in ('off', '0', 'false'):
        try:
            sib_entries = []
            sibs = [s for s in d.parent.iterdir()
                    if s.is_dir() and s != d and (s / 'phase0').exists()]
            for sib in sorted(sibs, key=lambda p: -p.stat().st_mtime):
                cand = None
                for rel in ('phase3_revise/final_candidate.json',
                            'phase2_coherence/refined_candidate.json',
                            'phase2_generate/phase2_generate_output.json'):
                    if (sib / rel).exists():
                        cand = _read_json(sib / rel) or {}
                        break
                if not cand or not cand.get('title'):
                    continue
                terms = ', '.join(str(t) for t in (cand.get('signature_terms') or [])[:4])
                sib_entries.append(f'[{sib.name}] "{cand.get("title")}"'
                                   + (f' ({terms})' if terms else ''))
                if len(sib_entries) >= 5:
                    break
            if sib_entries:
                crossrun_line = ('CROSS-RUN DEDUP (soft negative anchors — see the OPTIONAL '
                                 'cross-run input in ideate_select.txt): recent sibling runs '
                                 'already produced these mechanisms; do NOT re-propose the same '
                                 'mechanism family unless this direction demands it AND the '
                                 'delta is stated explicitly: ' + ' | '.join(sib_entries))
        except Exception:
            pass
    if not p2s.exists() or not p2g.exists():
        # Slim view: ideate_generate.txt already forbids reading the full lit_results
        # dump (closest_adjacent entries only) — materializing the slice up front turns
        # that instruction into a physical guarantee instead of sub-agent discipline.
        prep_cmd = skill_cd + f'phase2_prepare --dir "{d}"'
        slim = d / 'phase2_generate' / 'closest_abstracts.json'
        slim_line = (str(slim) + ' (pre-filtered closest_adjacent slice, materialized by the RUN '
                     'command; if it is missing or phase2_prepare WARNed about unmatched ids, fall '
                     'back to filtering ' + str(p0 / 'lit_results.json') + ' yourself)')
        # Thin-anchor sentinel: a crowded lane with very few closest_adjacent entries
        # usually means Phase 1 under-anchored — warn, never auto-pad (forcing a count
        # band would dilute residues with noise anchors or truncate real ones).
        sentinel = ''
        try:
            ca_n = len((p1_doc.get('closest_adjacent') or []))
            rows = [ln for ln in (p0 / 'lit_table.md').read_text().splitlines()
                    if ln.strip().startswith('|') and 'paper_id' not in ln and '---' not in ln]
            on_topic = sum(1 for ln in rows if 'outside_taxonomy' not in ln)
            if on_topic >= 20 and ca_n < 3:
                sentinel = (f' WARNING: only {ca_n} closest_adjacent entries against ~{on_topic} '
                            'on-topic papers — thin anchor grounding in a crowded lane; consider '
                            're-examining Phase 1 anchor choices before generating.')
        except Exception:
            pass
        if p2s.exists():  # only 2.2 left
            return _emit('Phase 2.1 selection done; candidate not yet generated.',
                         'Phase 2.2 — sub-pattern picking + candidate generation', 'llm_subagent',
                         prompt=str(prompts / 'ideate_generate.txt'),
                         run=[prep_cmd],
                         inputs=[str(p2s), str(p1), slim_line,
                                 str(ref / 'ideation-sub-patterns') + '/<picked C##>.md']
                                + ([crossrun_line] if crossrun_line else []),
                         output=str(p2g),
                         notes='Run the RUN command first (deterministic, materializes the slim '
                               'input), then the sub-agent. Immediately after: `next` runs the '
                               'citation gate for you.' + sentinel + retry_note,
                         run_dir=d)
        return _emit('Phase 1 complete (state=proceed).',
                     'Phase 2.1 + 2.2 — ONE sub-agent, TWO output files', 'llm_subagent',
                     prompt=str(prompts / 'ideate_select.txt') + ' THEN ' + str(prompts / 'ideate_generate.txt'),
                     run=[prep_cmd],
                     inputs=[str(p0 / 'user_query.txt') + ' (the user question, verbatim — '
                             'phase1_output.json.intake is a summary of it, not a substitute)',
                             str(p1),
                             str(ref / 'ideation-patterns' / 'overview.md'),
                             str(ref / 'ideation-patterns' / 'companion-combos.md'),
                             str(p0 / 'lit_table.md'),
                             slim_line,
                             str(ref / 'ideation-sub-patterns' / 'overview.md') + ' (+ picked C##.md cards)']
                            + ([crossrun_line] if crossrun_line else []),
                     output=f'{p2s} then {p2g}',
                     notes='Run the RUN command first (deterministic, materializes the slim input '
                           'for 2.2), then the sub-agent. Both phases are generation-side (no '
                           'adversarial separation needed between them — that separation is for '
                           '3.2/3.3 and 4.fill/4.1.5), so one sub-agent runs 2.1, Writes its '
                           'output, then continues into 2.2 and Writes the candidate. Saves a '
                           'sub-agent spin-up + duplicate input reads. Routing signal: none.'
                           + sentinel + retry_note,
                     run_dir=d)

    # ---- deterministic citation gate (run inline — pure) ----------------------
    #
    # Two checks share this gate because both must clear BEFORE 3.1 collision is
    # launched: collision consumes `alias_terms[]` verbatim, so an alias set that
    # skipped Phase 1's collateral families spends the whole multi-year retrieval
    # budget on the wrong vocabulary and the miss is invisible afterwards.
    gate_fails, gate_warns = [], []
    try:
        from scripts.validators import (validate_subpattern_citation_consistency,
                                        validate_alias_collateral_coverage)
        gate = validate_subpattern_citation_consistency(str(p2g))
        p1_for_alias = d / 'phase1' / 'phase1_output.json'
        if p1_for_alias.exists():
            gate += validate_alias_collateral_coverage(str(p2g), str(p1_for_alias))
        gate_fails = [f for f in gate if f.get('severity') == 'fail']
        gate_warns = [f for f in gate if f.get('severity') == 'warn']
    except Exception as e:  # never block `next` on a validator crash
        print(f'(citation gate could not run: {e})', file=sys.stderr)
    if gate_fails:
        msgs = '; '.join(f.get('message', '').rstrip('. ') for f in gate_fails[:3])
        alias_hit = any(f.get('validator') == 'alias_collateral_coverage' for f in gate_fails)
        fix = ('Add one alias_terms[] entry per collateral node, phrased in that field\'s '
               'vocabulary (see ideate_generate.txt\'s alias_terms clause (a)), then re-run '
               '`next`. Collision has not run yet — fixing now costs nothing.'
               if alias_hit else
               'Fix the citation to a real C## cluster row (or regenerate 2.2 with the card '
               'actually open).')
        return _emit('Phase 2.2 candidate FAILS the deterministic citation gate.',
                     'Fix the candidate before any Phase 3 work', 'llm_subagent',
                     prompt=str(ref / 'ideation-sub-patterns' / 'overview.md'),
                     inputs=[str(p2g)] + ([str(d / 'phase1' / 'phase1_output.json')]
                                          if alias_hit else []),
                     output=str(p2g) + ' (edited in place)',
                     notes=f'Validator findings: {msgs}. {fix} Do NOT proceed '
                           'to Phase 3 until `next` stops reporting this step.',
                     run_dir=d)
    # Warnings do not block, but they must not be silent either: partial collateral
    # coverage is how a run loses the one family that names its cause of death.
    for f in gate_warns:
        print(f'⚠️  [{f.get("validator")}] {f.get("message")}', file=sys.stderr)

    # ---- Phase 2.3 coherence gate (dry-run trace) -------------------------------
    p2c_dir = d / 'phase2_coherence'
    p2c = p2c_dir / 'phase2_coherence_output.json'
    refined = p2c_dir / 'refined_candidate.json'
    # Grandfather clause: a run whose AUDIT already consumed a candidate predates
    # the coherence gate (or deliberately skipped it) — do NOT demand 2.3
    # retroactively; a refined candidate appearing AFTER the audit consumed the
    # raw one would corrupt the chain. Collision hits alone do NOT trigger this:
    # collision reads only signature/alias terms, so it legitimately runs in
    # PARALLEL with 2.3 (the .collision_terms.json sidecar + the mismatch check
    # below make that safe). Legacy runs continue with canonical = 2.2.
    legacy_past_gate = (d / 'phase3_critique' / 'phase3_critique_output.json').exists()
    if not p2c.exists() and not legacy_past_gate:
        # Collision (3.1) reads ONLY signature/alias terms, which 2.3 patches
        # almost never touch — so it can start NOW, in parallel with the gate.
        # If a patch does change the terms, the sidecar mismatch check below
        # re-issues collision; nothing is silently stale.
        par_pending = not (d / 'phase3_collision' / 'collision_hits.json').exists()
        par_run = ([skill_cd + f'phase3_collision --idea-json "{p2g}" '
                    f'--out "{d / "phase3_collision"}/"'] if par_pending else None)
        return _emit('Citation gate passed; coherence gate not yet run.',
                     'Phase 2.3 — coherence gate (dry-run trace)'
                     + (' — AND launch 3.1 collision in parallel' if par_pending else ''),
                     'llm_subagent',
                     prompt=str(prompts / 'coherence_trace.txt'),
                     inputs=[str(p2g), str(p2s)],
                     output=str(p2c),
                     run=par_run,
                     notes=(('TWO independent actions: (1) launch the RUN command in the '
                             'BACKGROUND first — deterministic retrieval, no LLM, reads only '
                             'signature/alias terms (if a 2.3 patch changes them, `next` '
                             'detects the mismatch and re-issues collision); (2) run the 2.3 '
                             'sub-agent. ') if par_pending else '')
                           + 'MUST be a FRESH context — never the Phase 2.1+2.2 agent (the context '
                           'that wrote a logic bug rubber-stamps it). Routing signal to return: '
                           '`verdict` (pass | patched) + any `unrepaired[]` blocking findings.',
                     run_dir=d)
    p2c_doc = _read_json(p2c) or {}
    p2c_verdict = p2c_doc.get('verdict')
    if p2c.exists() and p2c_verdict not in ('pass', 'patched'):
        # Malformed / truncated 2.3 output must not silently bypass the gate —
        # but the redo is BOUNDED: a gate that cannot emit a valid verdict in
        # three tries is an environment failure, not a candidate to keep
        # rerolling, and an unbounded redo would spend the run in a livelock.
        _rej2 = _rejected_count(p2c_dir)
        if _rej2 >= 2:
            return _emit(f'Coherence gate produced an invalid verdict {_rej2 + 1} times '
                         f'(latest: {p2c_verdict!r}) — the gate cannot complete, and it is '
                         'MANDATORY, so the run cannot proceed past it.',
                         'Write phase_3_failed.md (coherence gate could not complete)',
                         'llm_subagent',
                         inputs=[str(p2c) + ' (the latest malformed output)',
                                 str(p2c_dir) + '/rejected_* (the earlier ones)'],
                         output=str(d / 'phase_3_failed.md'),
                         notes='Record that the blocker is the GATE, not the candidate: state '
                               'the invalid verdict values seen, that Phase 2.3 is mandatory and '
                               'cannot be bypassed, and the user-side options (re-run the gate '
                               'manually against coherence_trace.txt, check the sub-agent/context '
                               'setup, or restart the direction). Do NOT present the candidate as '
                               'having failed on its merits.',
                         run_dir=d)
        _arch2 = p2c_dir / f'rejected_{_rej2 + 1}'
        return _emit('Coherence output exists but its verdict is invalid '
                     f'({p2c_verdict!r}) — the gate did not complete.',
                     'Redo Phase 2.3 — coherence gate (dry-run trace)', 'llm_subagent',
                     prompt=str(prompts / 'coherence_trace.txt'),
                     inputs=[str(p2g), str(p2s)],
                     output=str(p2c),
                     run=[f'mkdir -p "{_arch2}" && mv "{p2c}" "{_arch2}/"'],
                     notes='Run the RUN command FIRST — it archives the malformed file (which is '
                           f'also how the redo stays bounded; this is redo {_rej2 + 1} of 3). '
                           'Then run the gate in a FRESH context. Valid verdicts: pass | patched.',
                     run_dir=d)
    if p2c_verdict == 'patched' and not refined.exists():
        return _emit('Coherence gate emitted repairs; merger not yet run.',
                     'Phase 2.3 merger (deterministic)', 'bash',
                     run=[skill_cd + 'phase3_merge_revisions '
                          f'--phase2 "{p2g}" --revisions "{p2c}" '
                          f'--out "{p2c_dir}/" --out-name refined_candidate.json'],
                     run_dir=d)
    # Canonical candidate for every later phase: the coherence-repaired file when
    # THIS gate run patched (verdict-bound, so a stale refined file from an
    # earlier round can never shadow a later pass verdict), else the 2.2 output.
    canonical = refined if (p2c_verdict == 'patched' and refined.exists()) else p2g

    # ---- Phase 3.1 collision ---------------------------------------------------
    p3c_dir = d / 'phase3_collision'
    # Parallel-collision consistency: hits retrieved (possibly alongside 2.3)
    # with terms a coherence patch has since changed are stale — re-run on the
    # canonical candidate. Skipped for legacy runs (audit already consumed the
    # chain) and for pre-sidecar runs (nothing to compare against).
    terms_sidecar = p3c_dir / '.collision_terms.json'
    if ((p3c_dir / 'collision_hits.json').exists() and terms_sidecar.exists()
            and not legacy_past_gate):
        _used = _read_json(terms_sidecar) or {}
        _cand = _read_json(canonical) or {}
        def _tset(v):
            return sorted(t for t in (v or []) if t)
        if (_tset(_used.get('signature_terms')) != _tset(_cand.get('signature_terms'))
                or _tset(_used.get('alias_terms')) != _tset(_cand.get('alias_terms'))):
            return _emit('Collision hits were retrieved with terms a 2.3 patch has since changed.',
                         'Re-run Phase 3.1 collision with the repaired terms', 'bash',
                         run=[skill_cd + f'phase3_collision --idea-json "{canonical}" '
                              f'--out "{p3c_dir}/"'],
                         notes='The parallel collision launch used pre-repair terms; the '
                               'coherence patch changed signature/alias terms, so the hits '
                               'are stale. Re-running overwrites collision_hits.json and '
                               'its sidecar.',
                         run_dir=d)
    if (p3c_dir / '.signature_extraction_pending').exists() and not (p3c_dir / 'collision_hits.json').exists():
        return _emit('Phase 3.1 stalled: candidate lacks signature_terms[].',
                     'Fill signature_terms and re-invoke collision', 'llm_subagent',
                     prompt=str(ref / 'intent-recognition.md') + ' (Collision mode)',
                     inputs=[str(canonical)],
                     output=str(canonical) + ' (add signature_terms[] — 3-5 tight terms)',
                     run=[skill_cd + f'phase3_collision --idea-json "{canonical}" '
                          f'--out "{p3c_dir}/"'],
                     run_dir=d)
    if not (p3c_dir / 'collision_hits.json').exists():
        return _emit('Candidate passed the citation gate.',
                     'Phase 3.1 — dual-channel collision retrieval (signature@10mo + alias@48mo)', 'bash',
                     run=[skill_cd + f'phase3_collision --idea-json "{canonical}" '
                          f'--out "{p3c_dir}/"'],
                     notes='Takes minutes (openreview budgets 600s) — Bash timeout >= 600s or '
                           'background. If the command WARNs that alias_terms[] is missing, add '
                           'the field to the candidate JSON (2-4 cross-community names for the '
                           'mechanism; rubric: intent-recognition.md Collision mode) and re-run — '
                           'skipping it leaves the renamed-ancestor blind spot open.',
                     run_dir=d)

    # ---- Phase 3.2 audit --------------------------------------------------------
    p3q = d / 'phase3_critique' / 'phase3_critique_output.json'
    # Blocking unrepaired findings from the coherence gate reach the audit as
    # executed evidence (critique.txt input rules). Preferred transport: the
    # self-contained blocking_findings.json the 2.3 gate writes; inline text is
    # the degraded fallback for pre-handoff runs.
    blocking = [u for u in (p2c_doc.get('unrepaired') or [])
                if isinstance(u, dict) and u.get('severity') == 'blocking']
    bf_file = d / 'phase2_coherence' / 'blocking_findings.json'
    if not p3q.exists():
        audit_inputs = [str(canonical), str(p2s), str(p0 / 'lit_table.md')]
        disposition_note = (' The report MUST contain blocking_findings_disposition[] with one '
                            'entry per blocking finding (refute only via a concrete '
                            'modeling/arithmetic flaw); while any entry is upheld, advance is '
                            'forbidden.')
        if blocking and bf_file.exists():
            audit_inputs.append(str(bf_file) + ' (2.3 blocking findings — self-contained executed-'
                                'evidence slice; disposition each per critique.txt)')
        elif blocking:
            audit_inputs.append('2.3 unrepaired BLOCKING findings (verbatim, inline fallback — '
                                'blocking_findings.json absent): '
                                + ' | '.join(str(u.get('finding', ''))[:400] for u in blocking))
        return _emit('Collision hits retrieved.', 'Phase 3.2 — audit-and-verdict (5 checks)', 'llm_subagent',
                     prompt=str(prompts / 'critique.txt'),
                     inputs=audit_inputs + [
                             str(p3c_dir / 'collision_hits.json'),
                             str(ref / 'anti-patterns.md'),
                             str(ref / 'ideation-sub-patterns') + '/<each cited C##>.md'],
                     output=str(p3q),
                     notes='Routing signal to return: `verdict` (advance | revise | abandon) + '
                           'verdict_rationale.' + (disposition_note if blocking else ''),
                     run_dir=d)
    p3q_doc = _read_json(p3q) or {}
    verdict = p3q_doc.get('verdict')

    # ---- deterministic guard: executed blocking evidence must be dispositioned ----
    # An audit that never saw (or silently ignored) the 2.3 gate's blocking
    # findings can emit a false advance — this exact failure occurred in a live
    # run (host truncated the emit; audit judged without the evidence and said
    # advance against an executed refutation). The guard is deterministic: it
    # checks presence/coverage of blocking_findings_disposition[], not quality.
    audit_noncompliant = False
    _p3q_dir = d / 'phase3_critique'
    _rej3 = _rejected_count(_p3q_dir)
    if blocking and verdict in ('advance', 'revise') and _rej3 >= 2:
        # BOUNDED GUARD. The three checks below each demand the audit REWRITE its
        # report; an audit that keeps re-asserting the same non-compliant verdict
        # would otherwise livelock: the same emit forever, one full audit call
        # burned per turn, with nothing to stop it. After two archived rejections the executed
        # blocking findings stand un-cleared by any compliant audit, which is
        # exactly what `abandon` means here — so routing falls through to the
        # information-gain retry, whose own budget bounds what follows.
        audit_noncompliant = True
        verdict = 'abandon'
    if blocking and verdict in ('advance', 'revise'):
        dispositions = [dd for dd in (p3q_doc.get('blocking_findings_disposition') or [])
                        if isinstance(dd, dict)]
        upheld = [dd for dd in dispositions if dd.get('status') == 'upheld']
        refuted = [dd for dd in dispositions if dd.get('status') == 'refuted']
        recheck_p = d / 'phase3_critique' / 'refutation_recheck.json'
        recheck_doc = _read_json(recheck_p) or {}
        # A recheck verdict only counts against the CURRENT report's refuted
        # dispositions (prefix-match on finding_ref) — otherwise a stale
        # recheck file from a superseded report would bounce a clean re-audit
        # forever (or a fresh refutation would coast on an old validation).
        _refuted_refs = [str(dd.get('finding_ref', ''))[:40] for dd in refuted]
        invalid_refutations = [
            r for r in (recheck_doc.get('rechecks') or [])
            if isinstance(r, dict) and r.get('refutation_valid') is False
            and any(ref and (str(r.get('finding_ref', ''))[:40].startswith(ref[:20])
                             or ref.startswith(str(r.get('finding_ref', ''))[:20]))
                    for ref in _refuted_refs)]
        # Quality backstop on the ONE path where the presence-only guard is
        # gameable: a `refuted` disposition dismisses executed evidence, so it
        # gets a bounded second opinion (fresh call, judges ONLY whether the
        # stated basis names a concrete modeling/arithmetic flaw). Upheld
        # dispositions need no recheck — they already concede the evidence.
        # Ordering: coverage first (an incomplete report is regenerated whole,
        # rechecking it would be wasted), then recheck, then verdict consistency.
        if len(dispositions) >= len(blocking) and refuted and not recheck_p.exists():
            return _emit(f'Phase 3.2 verdict = {verdict} with {len(refuted)} blocking finding(s) '
                         'marked REFUTED — a refutation of executed evidence requires a bounded '
                         're-check before the verdict is trusted.',
                         'Refutation re-check (single bounded call)', 'llm_subagent',
                         prompt=str(prompts / 'refutation_recheck.txt'),
                         inputs=[(str(bf_file) if bf_file.exists() else
                                  '2.3 blocking findings (verbatim): '
                                  + ' | '.join(str(u.get('finding', ''))[:400] for u in blocking)),
                                 str(p3q) + ' (read ONLY blocking_findings_disposition[])',
                                 str(canonical) + ' (ONLY to verify quoted step text)'],
                         output=str(recheck_p),
                         notes='Routing signal: per-finding `refutation_valid` (true|false). '
                               'When in doubt, the executed finding stands (refutation_valid='
                               'false). This call judges the refutation, not the candidate.',
                         run_dir=d)
        if refuted and invalid_refutations:
            return _emit(f'Phase 3.2 verdict = {verdict}, but the refutation re-check judged '
                         f'{len(invalid_refutations)} refutation(s) INVALID — the underlying '
                         'blocking finding(s) stand un-confronted. The verdict is NOT trusted.',
                         'Re-run Phase 3.2 (overwrite the report) — invalidly-refuted findings '
                         'must be treated as upheld', 'llm_subagent',
                         prompt=str(prompts / 'critique.txt'),
                         inputs=[str(canonical), str(p2s), str(p0 / 'lit_table.md'),
                                 (str(bf_file) if bf_file.exists() else
                                  '2.3 blocking findings (verbatim): '
                                  + ' | '.join(str(u.get('finding', ''))[:400] for u in blocking)),
                                 str(recheck_p) + ' (the re-check verdicts — these refutations '
                                 'are invalid and must not be repeated)',
                                 str(p3c_dir / 'collision_hits.json'),
                                 str(ref / 'anti-patterns.md'),
                                 str(ref / 'ideation-sub-patterns') + '/<each cited C##>.md'],
                         run=[f'mkdir -p "{_p3q_dir}/rejected_{_rej3 + 1}" && mv "{p3q}" "{_p3q_dir}/rejected_{_rej3 + 1}/" && {{ mv "{recheck_p}" "{_p3q_dir}/rejected_{_rej3 + 1}/" 2>/dev/null || true; }}'],
                         output=str(p3q),
                         notes='Run the RUN command FIRST — it archives the rejected report, which is how '
                               f'this bounce stays bounded (rejection {_rej3 + 1} of 2; after that the '
                               'un-cleared findings route to abandon). Regenerate the FULL audit. '
                               'The re-checked findings count as '
                               'UPHELD: verdict is capped at revise (targets confronting each) '
                               'or abandon (redesign → internal retry). Delete/overwrite the '
                               'stale refutation_recheck.json only if new dispositions differ.',
                         run_dir=d)
        if len(dispositions) < len(blocking):
            return _emit(f'Phase 3.2 verdict = {verdict}, but the 2.3 coherence gate holds '
                         f'{len(blocking)} BLOCKING executed finding(s) and the audit report '
                         f'dispositioned only {len(dispositions)} — the evidence was not weighed. '
                         'The verdict is NOT trusted.',
                         'Re-run Phase 3.2 WITH the blocking findings (overwrite the report)',
                         'llm_subagent',
                         prompt=str(prompts / 'critique.txt'),
                         inputs=[str(canonical), str(p2s), str(p0 / 'lit_table.md'),
                                 (str(bf_file) if bf_file.exists() else
                                  '2.3 blocking findings (verbatim): '
                                  + ' | '.join(str(u.get('finding', ''))[:400] for u in blocking)),
                                 str(p3c_dir / 'collision_hits.json'),
                                 str(ref / 'anti-patterns.md'),
                                 str(ref / 'ideation-sub-patterns') + '/<each cited C##>.md'],
                         run=[f'mkdir -p "{_p3q_dir}/rejected_{_rej3 + 1}" && mv "{p3q}" "{_p3q_dir}/rejected_{_rej3 + 1}/" && {{ mv "{recheck_p}" "{_p3q_dir}/rejected_{_rej3 + 1}/" 2>/dev/null || true; }}'],
                         output=str(p3q),
                         notes='Run the RUN command FIRST — it archives the rejected report, which is how '
                               f'this bounce stays bounded (rejection {_rej3 + 1} of 2; after that the '
                               'un-cleared findings route to abandon). Regenerate the FULL audit '
                               'including blocking_findings_disposition[] '
                               '(one entry per finding; refute only via a concrete modeling/'
                               'arithmetic flaw — executed evidence outranks unexecuted reasoning). '
                               'While any finding is upheld, advance is forbidden: route revise '
                               '(tactical confrontation) or abandon (redesign → internal retry).',
                         run_dir=d)
        if verdict == 'advance' and upheld:
            return _emit('Phase 3.2 verdict = advance, but the audit itself UPHELD '
                         f'{len(upheld)} blocking executed finding(s) — advance is forbidden by '
                         'critique.txt while an upheld blocking finding stands. Inconsistent report.',
                         'Re-run Phase 3.2 (overwrite the report) — verdict must be revise or abandon',
                         'llm_subagent',
                         prompt=str(prompts / 'critique.txt'),
                         inputs=[str(canonical), str(p2s), str(p0 / 'lit_table.md'),
                                 (str(bf_file) if bf_file.exists() else
                                  '2.3 blocking findings (verbatim): '
                                  + ' | '.join(str(u.get('finding', ''))[:400] for u in blocking)),
                                 str(p3c_dir / 'collision_hits.json'),
                                 str(ref / 'anti-patterns.md'),
                                 str(ref / 'ideation-sub-patterns') + '/<each cited C##>.md'],
                         run=[f'mkdir -p "{_p3q_dir}/rejected_{_rej3 + 1}" && mv "{p3q}" "{_p3q_dir}/rejected_{_rej3 + 1}/" && {{ mv "{recheck_p}" "{_p3q_dir}/rejected_{_rej3 + 1}/" 2>/dev/null || true; }}'],
                         output=str(p3q),
                         notes='Run the RUN command FIRST — it archives the rejected report, which is how '
                               f'this bounce stays bounded (rejection {_rej3 + 1} of 2; after that the '
                               'un-cleared findings route to abandon). Keep the five checks; '
                               'fix the verdict layer: upheld blocking '
                               'findings cap the verdict at revise (fix_direction confronts the '
                               'obstacle) or abandon (redesign → internal retry).',
                         run_dir=d)

    # ---- abandon → information-gain retry rule -------------------------------
    # ONE rule replaces the former death-type taxonomy (single retry + the
    # both-subsumption bottleneck branch): a retry must carry NEW binding
    # information the previous generation did not have; termination happens on
    # information exhaustion or the global budget, never on death-shape alone.
    #   lesson sets    L_new (this attempt) vs L_seen (union of archived attempts)
    #   fresh lessons  L_new - L_seen
    #   framing indict repeated threat-kind across attempts (the lesson "this
    #                  space is occupied" binds at the FRAMING level, so a
    #                  re-diagnosis, not another candidate roll, is the answer)
    #   budget         candidate cycles <= 3 under one framing; bottleneck
    #                  re-diagnosis <= 1, granting exactly ONE further attempt
    #                  (worst case 4 gauntlet cycles per run).
    # First abandon always retries: generation ran with no audit information at
    # all, so the first report is new information by construction.
    if verdict == 'abandon':
        attempts = _attempt_dirs(d)
        next_idx = (int(attempts[-1].name[8:]) + 1) if attempts else 1
        arch = d / f'attempt_{next_idx}'
        cand_mv = ' '.join(f'"{d / n}"' for n in
                           ('phase2_select', 'phase2_generate', 'phase2_coherence',
                            'phase3_collision', 'phase3_critique', 'phase3_revise')
                           if (d / n).exists())
        L_new = _lessons(p3q_doc)
        if audit_noncompliant:
            # No compliant audit ever dispositioned these, so they stand as
            # lessons on their own executed evidence — otherwise a bounced-out
            # audit would hand the retry an empty lesson set and terminate it.
            L_new |= {('finding', str(u.get('finding', ''))[:40]) for u in blocking}
        seen_sets = [_lessons(_read_json(a / 'phase3_critique' /
                                         'phase3_critique_output.json') or {})
                     for a in attempts]
        L_seen = set().union(*seen_sets) if seen_sets else set()
        fresh = L_new - L_seen
        cycles_used = len(attempts) + 1
        framing_indicted = (any(k == 'threat' for k, _ in L_new)
                            and any(k == 'threat' for k, _ in L_seen))
        fail_inputs = [str(p3q)] + [
            str(a / 'phase3_critique' / 'phase3_critique_output.json') for a in attempts]

        if (d / '.bottleneck_retry_used').exists():
            # The re-diagnosed framing had its one granted attempt.
            return _emit('Phase 3.2 verdict = abandon — retry budget exhausted '
                         '(bottleneck retry already used; its one candidate attempt failed).',
                         'Write phase_3_failed.md', 'llm_subagent',
                         inputs=fail_inputs,
                         output=str(d / 'phase_3_failed.md'),
                         notes='Include EVERY attempt\'s verdict_rationale + triggering checks + the '
                               'user-side options (drop direction / change framing / re-run with a '
                               'different direction). That file is the run\'s final output.',
                         run_dir=d)
        _nc = (' (routed here because the audit could not produce a compliant report in 3 '
               'tries — the executed blocking findings stand un-cleared)' if audit_noncompliant else '')
        if not attempts:
            return _emit(f'Phase 3.2 verdict = abandon{_nc} — internal retry available '
                         '(no user re-invocation; the one-shot guarantee constrains asking the '
                         'user, not internal regeneration).',
                         'Archive attempt 1 and regenerate Phase 2.1+2.2 under negative constraints',
                         'bash',
                         run=[f'mkdir -p "{arch}" && mv {cand_mv} "{arch}/" && touch "{d}/.retry_used"'],
                         notes='Then re-run `next` — it will route to Phase 2.1+2.2 in retry mode '
                               '(the archived audit + selection become negative constraints, and any '
                               'blocking obstacle findings become POSITIVE directives — the new '
                               'mechanism must confront them — per ideate_select.txt\'s OPTIONAL '
                               'retry input). Phase 0/1 artifacts are reused as-is.',
                         run_dir=d)
        if framing_indicted:
            mv_b = ' '.join(f'"{d / n}"' for n in
                            ('phase1', 'phase2_select', 'phase2_generate', 'phase2_coherence',
                             'phase3_collision', 'phase3_critique', 'phase3_revise')
                            if (d / n).exists())
            return _emit('Abandon with a REPEATED unaddressable-subsumption lesson across attempts '
                         '— the occupied space binds at the framing level, so another candidate '
                         'roll cannot help. ONE bottleneck-level retry available.',
                         f'Archive attempt {next_idx} (incl. phase1) and re-diagnose the bottleneck',
                         'bash',
                         run=[f'mkdir -p "{arch}" && mv {mv_b} "{arch}/" && '
                              f'touch "{d}/.bottleneck_retry_used"'],
                         notes='Then re-run `next` — it routes to Phase 1 in BOTTLENECK-RETRY MODE '
                               '(the retired bottleneck_statement + every attempt\'s threat papers '
                               'become negative anchors per bottleneck_identify.txt\'s OPTIONAL '
                               'retry input; do_not_generate remains a legitimate, preferred '
                               'outcome over a blander re-framing). The new bottleneck gets ONE '
                               'candidate attempt. Phase 0 artifacts are reused as-is.',
                         run_dir=d)
        if fresh and cycles_used < 3:
            fresh_desc = '; '.join(f'{k}: {v}' for k, v in sorted(fresh))[:400]
            return _emit(f'Phase 3.2 verdict = abandon, but this attempt produced NEW binding '
                         f'directive(s) the previous generation did not have ({len(fresh)} new '
                         f'lesson(s)) — a directed retry is justified by information gain.',
                         f'Archive attempt {next_idx} and regenerate Phase 2.1+2.2 under the '
                         'accumulated lessons', 'bash',
                         run=[f'mkdir -p "{arch}" && mv {cand_mv} "{arch}/" && touch "{d}/.retry_used"'],
                         notes='NEW lessons this attempt added (become POSITIVE directives / negative '
                               f'anchors for the regeneration): {fresh_desc}. Then re-run `next` — '
                               'retry mode carries ALL archived audits + selections as constraints. '
                               'Phase 0/1 artifacts are reused as-is.',
                         run_dir=d)
        if fresh:
            why = f'candidate-cycle cap (3) reached under this framing'
        else:
            why = ('no NEW binding information — this attempt\'s lessons repeat what the '
                   'generation already had, so another roll is not justified')
        return _emit(f'Phase 3.2 verdict = abandon — retry budget exhausted ({why}).',
                     'Write phase_3_failed.md', 'llm_subagent',
                     inputs=fail_inputs,
                     output=str(d / 'phase_3_failed.md'),
                     notes='Include EVERY attempt\'s verdict_rationale + triggering checks + the '
                           'user-side options (drop direction / change framing / re-run with a '
                           'different direction). That file is the run\'s final output.',
                     run_dir=d)

    # ---- revise path --------------------------------------------------------------
    p3r_dir = d / 'phase3_revise'
    p3r = p3r_dir / 'phase3_revise_output.json'
    final_candidate = p3r_dir / 'final_candidate.json'
    # Legacy runs back-inject final_candidate INTO the patch file without a
    # sibling final_candidate.json; treat that as merged (kill_switch_integrity
    # reads the inline key too).
    merged = final_candidate.exists() or bool((_read_json(p3r) or {}).get('final_candidate'))
    if verdict == 'revise':
        if not p3r.exists():
            has_fals = any(isinstance(t, dict) and t.get('scope') == 'falsification'
                           for t in (p3q_doc.get('revision_targets') or []))
            fals_note = (' One revision_target has scope=falsification — emit ONE '
                         'rewrite_falsification entry for it (same experiment/metric/claim, '
                         'structure repaired).' if has_fals else '')
            brief = p3r_dir / 'revise_brief.json'
            return _emit('Phase 3.2 verdict = revise.', 'Phase 3.3 — emit the revision patch', 'llm_subagent',
                         prompt=str(prompts / 'revise.txt'),
                         run=[skill_cd + f'phase3_revise_brief --critique "{p3q}" --out "{p3r_dir}/"'],
                         inputs=[str(canonical), str(p2s),
                                 str(brief) + ' (revision brief, materialized by the RUN command; '
                                 'falls back to ' + str(p3q) + ' if missing — the brief\'s _brief_note '
                                 'says when to consult the full report)'],
                         output=str(p3r),
                         notes='Run the RUN command first (deterministic). Patch-only: '
                               'applied_revisions[] — never echo the candidate.' + fals_note,
                         run_dir=d)
        if not merged:
            return _emit('Revision patch written; merger not yet run.',
                         'Phase 3.3 merger (deterministic)', 'bash',
                         run=[skill_cd + 'phase3_merge_revisions '
                              f'--phase2 "{canonical}" --revisions "{p3r}" --critique "{p3q}" '
                              f'--out "{p3r_dir}/"'],
                         run_dir=d)
        p3r_doc = _read_json(p3r) or {}
        reaudit = d / 'phase3_critique' / 'falsification_reaudit.json'
        if p3r_doc.get('falsification_rewritten'):
            if not reaudit.exists():
                fview = d / 'phase3_critique' / 'falsification_view.json'
                return _emit('falsification_prediction was rewritten (audited exception) — '
                             're-audit REQUIRED before Phase 4.',
                             'Falsification re-audit (single-check)', 'llm_subagent',
                             prompt=str(prompts / 'falsification_reaudit.txt'),
                             run=[skill_cd + 'phase3_falsification_view '
                                  f'--candidate "{final_candidate}" --out "{d / "phase3_critique"}/"'],
                             inputs=[str(fview) + ' (falsification slice, materialized by the RUN '
                                     'command; falls back to ' + str(final_candidate) +
                                     ' if missing — then read ONLY the fields the prompt names)'],
                             output=str(reaudit),
                             notes='Run the RUN command first (deterministic). Routing signal: '
                                   '`verdict` (advance | abandon). Exactly one rewrite attempt '
                                   'per run — deficient again means abandon.',
                             run_dir=d)
            re_doc = _read_json(reaudit) or {}
            if re_doc.get('verdict') == 'abandon':
                return _emit('Falsification re-audit verdict = abandon (rewrite still deficient).',
                             'Write phase_3_failed.md', 'llm_subagent',
                             inputs=[str(p3q), str(reaudit)],
                             output=str(d / 'phase_3_failed.md'),
                             notes='Name the original structural deficiency AND why the one '
                                   'permitted rewrite still fails. That file is the run\'s final output.',
                             then=True, run_dir=d)

    # ---- Phase 4 -------------------------------------------------------------------
    p4_dir = d / 'phase4'
    on_revise_path = verdict == 'revise' and merged
    # Legacy runs without the sibling file fall back to the patch file (the
    # skeleton unwraps an inline `final_candidate` key itself).
    candidate_path = ((final_candidate if final_candidate.exists() else p3r)
                      if on_revise_path else canonical)
    expansion_done = (p4_dir / 'phase4_expansion.json').exists()
    # Skeleton/fill are only prerequisites while the expansion doesn't exist yet
    # (pre-skeleton-era runs have an expansion but no skeleton/fill_map — don't
    # send those back to rebuild artifacts the pipeline no longer needs).
    if not expansion_done and not (p4_dir / 'phase4_skeleton.json').exists():
        cmd = (skill_cd + 'phase4_skeleton '
               f'--candidate "{candidate_path}" --phase1 "{p1}" --phase2-select "{p2s}" '
               f'--phase3-critique "{p3q}" ')
        if on_revise_path:
            cmd += f'--phase3-revise "{p3r}" '
        cmd += (f'--phase0-dir "{p0}/" --collision "{p3c_dir / "collision_hits.json"}" '
                f'--out "{p4_dir}/"')
        return _emit(f'Gauntlet cleared ({verdict} path).', 'Phase 4 skeleton (deterministic)', 'bash',
                     run=[cmd], run_dir=d)
    if not expansion_done and not (p4_dir / 'fill_map.json').exists():
        return _emit('Skeleton built.', 'Phase 4.fill — author the TECHNICAL prose TODOs', 'llm_subagent',
                     prompt=str(prompts / 'expand.txt'),
                     inputs=[str(p4_dir / 'phase4_skeleton.json')],
                     output=str(p4_dir / 'fill_map.json'),
                     notes='Flat {TODO-path: prose} map ONLY — the assembler refuses kill-switch '
                           'roots. SKIP the derive-owned paths (title_zh + all plain_* — see the '
                           'exclusion list in expand.txt): a separate fast-tier derive step authors '
                           'them from your finished prose. This is the most timeout-prone call: '
                           'NEVER run it in the parent context.',
                     run_dir=d)
    if not expansion_done:
        return _emit('fill_map written.', 'Phase 4 assemble — partial (deterministic)', 'bash',
                     run=[skill_cd + 'phase4_assemble '
                          f'--skeleton "{p4_dir / "phase4_skeleton.json"}" '
                          f'--fill-map "{p4_dir / "fill_map.json"}" --out "{p4_dir}/"'],
                     notes='The WARN about remaining TODO placeholders is EXPECTED here — the '
                           'derive-owned plain fields are still placeholders; the derive step '
                           'fills them next and a final assemble merges both maps.',
                     run_dir=d)
    # ---- derive stage (plain-register fields; fast-tier) -----------------------------
    expansion_path = p4_dir / 'phase4_expansion.json'
    remaining_todos = re.findall(r'<TODO\[([^\]]+)\]', expansion_path.read_text())
    if remaining_todos:
        derive_map = p4_dir / 'derive_map.json'
        fill_keys = set((_read_json(p4_dir / 'fill_map.json') or {}).keys())
        derive_keys = set((_read_json(derive_map) or {}).keys()) if derive_map.exists() else set()
        missing = [p for p in remaining_todos if p not in fill_keys | derive_keys]
        # A missing TECHNICAL path is a fill gap, never derive's to author — route it back
        # to the fill contract instead of asking the derive step to invent technical prose.
        missing_tech = [p for p in missing if p != 'title_zh' and not p.startswith('plain_')]
        if missing_tech:
            return _emit('fill_map is missing technical TODO paths.',
                         'Fix fill_map — author the missing technical paths', 'llm_subagent',
                         prompt=str(prompts / 'expand.txt'),
                         inputs=[str(p4_dir / 'phase4_skeleton.json'),
                                 str(p4_dir / 'fill_map.json')],
                         output=str(p4_dir / 'fill_map.json') + ' (edited in place — add the missing keys)',
                         notes='Missing: ' + ', '.join(missing_tech[:8]) +
                               '. Add ONLY these keys to the existing fill_map (derive-owned '
                               'paths stay excluded), then re-run `next` — it will re-assemble.',
                         run_dir=d)
        missing = [p for p in missing if p not in missing_tech]
        if not derive_map.exists() or missing:
            miss_note = ''
            if derive_map.exists() and missing:
                miss_note = (' REGENERATION: the existing derive_map does not cover ' +
                             ', '.join(missing[:6]) + ' — rewrite the FULL map including them.')
            return _emit('Partial expansion assembled; plain-register fields pending.',
                         'Phase 4.derive — plain-register derivation (fast-tier)', 'llm_subagent',
                         prompt=str(prompts / 'derive_plain.txt'),
                         inputs=[str(expansion_path)],
                         output=str(derive_map),
                         notes='Mechanical register derivation + translation, NO new facts — '
                               'route to a cheaper/faster model tier BY DEFAULT (the '
                               'NOVELTY_LLM_CLASSIFY_FAST_CMD tier); fall back to the host model '
                               'in an isolated context only when no cheaper tier exists (the small '
                               'input still keeps it cheap). Routing signal: none (just the file).'
                               + miss_note,
                         run_dir=d)
        return _emit('derive_map written; expansion still partial.',
                     'Phase 4 assemble — final merge + method view (deterministic)', 'bash',
                     run=[skill_cd + 'phase4_assemble '
                          f'--skeleton "{p4_dir / "phase4_skeleton.json"}" '
                          f'--fill-map "{p4_dir / "fill_map.json"}" '
                          f'--fill-map "{derive_map}" --out "{p4_dir}/"',
                          skill_cd + 'phase4_method_view '
                          f'--expansion "{expansion_path}" --out "{p4_dir}/"'],
                     run_dir=d)
    if not (p4_dir / 'phase4_implementability.json').exists():
        view_path = p4_dir / 'method_view.json'
        if (not view_path.exists()
                or view_path.stat().st_mtime < expansion_path.stat().st_mtime):
            return _emit('Expansion complete; method view missing or stale.',
                         'Phase 4 method-view extract (deterministic)', 'bash',
                         run=[skill_cd + 'phase4_method_view '
                              f'--expansion "{expansion_path}" --out "{p4_dir}/"'],
                         run_dir=d)
        return _emit('Expansion assembled.', 'Phase 4.1.5 — implementability audit', 'llm_subagent',
                     prompt=str(prompts / 'implementability_audit.txt'),
                     inputs=[str(view_path) + ' (method-only slice; fall back to '
                             + str(expansion_path) + ' only if the view is missing)'],
                     output=str(p4_dir / 'phase4_implementability.json'),
                     notes='Fresh skeptical-engineer persona (separate call from 4.fill). '
                           'Compute-agnostic by design.',
                     run_dir=d)

    # ---- validate + render -----------------------------------------------------------
    phase3_for_validate = p3r if on_revise_path else p3q
    return _emit('All Phase 4 JSONs present; cards not yet rendered.',
                 'Validate, then render the idea cards', 'bash',
                 run=[skill_cd + 'validate '
                      f'--phase1 "{p1}" --phase2 "{canonical}" '
                      f'--phase2-select "{p2s}" --phase3 "{phase3_for_validate}" '
                      f'--phase4 "{p4_dir / "phase4_expansion.json"}" '
                      f'--phase4-impl "{p4_dir / "phase4_implementability.json"}"',
                      skill_cd + 'phase4_render '
                      f'--expansion "{p4_dir / "phase4_expansion.json"}" --out "{p4_dir}/"'],
                 notes='On a validate `fail`: fix only the named contract and re-validate — cap '
                       '2 retries, then render as-is with a caveat note (never edit '
                       'kill_switch/citation-guarded fields to silence a validator).',
                 run_dir=d)


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
