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
                     output='4-6 search queries (incl. one ESCAPE-MECHANISM query in solution vocabulary)',
                     run=[skill_cd + f'phase0 --query "{q}" '
                          f'--queries "q1|q2|q3|q4" --out "{d}/phase0/"'],
                     notes='Passing --queries up front skips a full sentinel round-trip (rc=10). '
                           'Retrieval takes 3-10 min (openreview alone budgets 600s) — set your '
                           'Bash timeout >= 600s or run in background. If the user query names '
                           'papers by TITLE (e.g. "based on the LoRA paper"), register each via: '
                           + skill_cd + f'add_user_ref --out "{p0}/" --title "<full title>" '
                           '--raw-match "<user phrasing>"  (deterministic merge; do NOT hand-edit '
                           'user_refs.json — some harnesses refuse to overwrite files never '
                           'read). OOD short-circuit: if the query matches intake-routing.md '
                           'trigger #1/#2, skip retrieval and go straight to Phase 1 with a '
                           'do_not_generate routing.',
                     run_dir=d)
    if not (p0 / 'lit_table.md').exists():
        return _emit('Papers retrieved; lit_table.md not yet written.',
                     'Phase 0 pattern_summary (host-LLM step)', 'llm_subagent',
                     prompt=str(ref / 'pattern-summary-rubric.md'),
                     inputs=[str(p0 / 'lit_results.json')],
                     output=str(p0 / 'lit_table.md'),
                     notes='Pure classification — no large reasoning model needed: route the '
                           'isolated context to a cheaper/faster tier or lower effort if your '
                           'harness supports it (the NOVELTY_LLM_CLASSIFY_FAST_CMD tier); '
                           'otherwise run it isolated on the host model. Tag each paper with '
                           '1-3 of the 15 patterns + bottleneck + open_issue + retrieved_via '
                           'per the rubric. Routing signal: none (just the file).',
                     run_dir=d)
    if not (p0 / 'fulltext_cache.json').exists():
        return _emit('lit_table.md written; full-text cache missing (Phase 1 hard-gates on it).',
                     'Phase 0+ full-text fetch', 'bash',
                     run=[skill_cd + f'phase0_fulltext --out "{d}/phase0/"'],
                     notes='LAST CALL for user refs: title-named papers must be registered '
                           '(add_user_ref) BEFORE this step — the fetch pool\'s U tier reads '
                           'user_refs.json now.',
                     run_dir=d)

    # ---- Phase 1 -------------------------------------------------------------
    p1 = d / 'phase1' / 'phase1_output.json'
    if not p1.exists():
        # Standing user compute default (.env is auto-loaded by run.py): surfaced
        # here so the Phase 1 sub-agent receives it as intake context. Precedence
        # inside Phase 1: user query > this value > factory default.
        user_compute = os.environ.get('IDEASPARK_DEFAULT_COMPUTE', '').strip()
        p1_inputs = ['the user query + intake context',
                     str(p0 / 'lit_table.md'),
                     str(p0 / 'fulltext_cache.json'),
                     str(p0 / 'lit_results.json')]
        if user_compute:
            p1_inputs.insert(1, f'standing user compute default (IDEASPARK_DEFAULT_COMPUTE, '
                                f'overrides factory default; user query still wins): "{user_compute}"')
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
    if (d / '.retry_used').exists() and (d / 'attempt_1').exists():
        retry_note = (' RETRY MODE: also pass ' + str(d / 'attempt_1/phase3_critique/phase3_critique_output.json') +
                      ' and ' + str(d / 'attempt_1/phase2_select/phase2_select_output.json') +
                      ' as negative constraints (see the OPTIONAL retry input in ideate_select.txt).')
    if not p2s.exists() or not p2g.exists():
        if p2s.exists():  # only 2.2 left
            return _emit('Phase 2.1 selection done; candidate not yet generated.',
                         'Phase 2.2 — sub-pattern picking + candidate generation', 'llm_subagent',
                         prompt=str(prompts / 'ideate_generate.txt'),
                         inputs=[str(p2s), str(p1), str(p0 / 'lit_results.json'),
                                 str(ref / 'ideation-sub-patterns') + '/<picked C##>.md'],
                         output=str(p2g),
                         notes='Immediately after: `next` runs the citation gate for you.' + retry_note,
                         run_dir=d)
        return _emit('Phase 1 complete (state=proceed).',
                     'Phase 2.1 + 2.2 — ONE sub-agent, TWO output files', 'llm_subagent',
                     prompt=str(prompts / 'ideate_select.txt') + ' THEN ' + str(prompts / 'ideate_generate.txt'),
                     inputs=[str(p1),
                             str(ref / 'ideation-patterns' / 'overview.md'),
                             str(ref / 'ideation-patterns' / 'companion-combos.md'),
                             str(p0 / 'lit_table.md'),
                             str(p0 / 'lit_results.json'),
                             str(ref / 'ideation-sub-patterns' / 'overview.md') + ' (+ picked C##.md cards)'],
                     output=f'{p2s} then {p2g}',
                     notes='Both phases are generation-side (no adversarial separation needed '
                           'between them — that separation is for 3.2/3.3 and 4.fill/4.1.5), so '
                           'one sub-agent runs 2.1, Writes its output, then continues into 2.2 '
                           'and Writes the candidate. Saves a sub-agent spin-up + duplicate '
                           'input reads. Routing signal: none.' + retry_note,
                     run_dir=d)

    # ---- deterministic citation gate (run inline — pure) ----------------------
    try:
        from scripts.validators import validate_subpattern_citation_consistency
        gate = validate_subpattern_citation_consistency(str(p2g))
        gate_fails = [f for f in gate if f.get('severity') == 'fail']
    except Exception as e:  # never block `next` on a validator crash
        print(f'(citation gate could not run: {e})', file=sys.stderr)
        gate_fails = []
    if gate_fails:
        msgs = '; '.join(f.get('message', '') for f in gate_fails[:3])
        return _emit('Phase 2.2 candidate FAILS the deterministic citation gate.',
                     'Fix gap_closure[] sub_pattern citations before any Phase 3 work', 'llm_subagent',
                     prompt=str(ref / 'ideation-sub-patterns' / 'overview.md'),
                     inputs=[str(p2g)],
                     output=str(p2g) + ' (edited in place)',
                     notes=f'Validator findings: {msgs}. Fix the citation to a real C## cluster '
                           'row (or regenerate 2.2 with the card actually open). Do NOT proceed '
                           'to Phase 3 until `next` stops reporting this step.',
                     run_dir=d)

    # ---- Phase 2.3 coherence gate (dry-run trace) -------------------------------
    p2c_dir = d / 'phase2_coherence'
    p2c = p2c_dir / 'phase2_coherence_output.json'
    refined = p2c_dir / 'refined_candidate.json'
    # Grandfather clause: a run that already has collision results predates the
    # coherence gate (or deliberately skipped it) — do NOT demand 2.3
    # retroactively; a refined candidate appearing AFTER the audit consumed the
    # raw one would corrupt the chain. Legacy runs continue with canonical = 2.2.
    legacy_past_gate = (d / 'phase3_collision' / 'collision_hits.json').exists()
    if not p2c.exists() and not legacy_past_gate:
        return _emit('Citation gate passed; coherence gate not yet run.',
                     'Phase 2.3 — coherence gate (dry-run trace of the algorithm)', 'llm_subagent',
                     prompt=str(prompts / 'coherence_trace.txt'),
                     inputs=[str(p2g), str(p2s)],
                     output=str(p2c),
                     notes='MUST be a FRESH context — never the Phase 2.1+2.2 agent (the context '
                           'that wrote a logic bug rubber-stamps it). Routing signal to return: '
                           '`verdict` (pass | patched) + any `unrepaired[]` blocking findings.',
                     run_dir=d)
    p2c_doc = _read_json(p2c) or {}
    p2c_verdict = p2c_doc.get('verdict')
    if p2c.exists() and p2c_verdict not in ('pass', 'patched'):
        # Malformed / truncated 2.3 output must not silently bypass the gate.
        return _emit('Coherence output exists but its verdict is invalid '
                     f'({p2c_verdict!r}) — the gate did not complete.',
                     'Redo Phase 2.3 — coherence gate (dry-run trace)', 'llm_subagent',
                     prompt=str(prompts / 'coherence_trace.txt'),
                     inputs=[str(p2g), str(p2s)],
                     output=str(p2c) + ' (overwrite the malformed file)',
                     notes='MUST be a FRESH context. Valid verdicts: pass | patched.',
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
    if not p3q.exists():
        audit_inputs = [str(canonical), str(p2s), str(p0 / 'lit_table.md')]
        # Per critique.txt: blocking unrepaired findings from the coherence gate are
        # listed as an extra input (the audit stays blind to the full 2.3 report).
        blocking = [u for u in (p2c_doc.get('unrepaired') or [])
                    if isinstance(u, dict) and u.get('severity') == 'blocking']
        if blocking:
            audit_inputs.append('2.3 unrepaired BLOCKING findings (verbatim): '
                                + ' | '.join(str(u.get('finding', ''))[:200] for u in blocking))
        return _emit('Collision hits retrieved.', 'Phase 3.2 — audit-and-verdict (5 checks)', 'llm_subagent',
                     prompt=str(prompts / 'critique.txt'),
                     inputs=audit_inputs + [
                             str(p3c_dir / 'collision_hits.json'),
                             str(ref / 'anti-patterns.md'),
                             str(ref / 'ideation-sub-patterns') + '/<each cited C##>.md'],
                     output=str(p3q),
                     notes='Routing signal to return: `verdict` (advance | revise | abandon) + '
                           'verdict_rationale.',
                     run_dir=d)
    p3q_doc = _read_json(p3q) or {}
    verdict = p3q_doc.get('verdict')

    # ---- abandon → bounded internal retry ---------------------------------------
    if verdict == 'abandon':
        if not (d / '.retry_used').exists():
            arch = d / 'attempt_1'
            mv_dirs = ' '.join(f'"{d / n}"' for n in
                               ('phase2_select', 'phase2_generate', 'phase2_coherence',
                                'phase3_collision', 'phase3_critique', 'phase3_revise') if (d / n).exists())
            return _emit('Phase 3.2 verdict = abandon — ONE internal retry available '
                         '(no user re-invocation; the one-shot guarantee constrains asking the '
                         'user, not internal regeneration).',
                         'Archive attempt 1 and regenerate Phase 2.1+2.2 under negative constraints',
                         'bash',
                         run=[f'mkdir -p "{arch}" && mv {mv_dirs} "{arch}/" && touch "{d}/.retry_used"'],
                         notes='Then re-run `next` — it will route to Phase 2.1+2.2 in retry mode '
                               '(the archived audit + selection become negative constraints per '
                               'ideate_select.txt\'s OPTIONAL retry input). Phase 0/1 artifacts are '
                               'reused as-is.',
                         run_dir=d)
        return _emit('Phase 3.2 verdict = abandon on the RETRY attempt — retry budget (1) exhausted.',
                     'Write phase_3_failed.md', 'llm_subagent',
                     inputs=[str(p3q),
                             str(d / 'attempt_1' / 'phase3_critique' / 'phase3_critique_output.json')],
                     output=str(d / 'phase_3_failed.md'),
                     notes='Include BOTH attempts\' verdict_rationale + triggering checks + the '
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
            return _emit('Phase 3.2 verdict = revise.', 'Phase 3.3 — emit the revision patch', 'llm_subagent',
                         prompt=str(prompts / 'revise.txt'),
                         inputs=[str(canonical), str(p2s), str(p3q)],
                         output=str(p3r),
                         notes='Patch-only: applied_revisions[] — never echo the candidate.' + fals_note,
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
                return _emit('falsification_prediction was rewritten (audited exception) — '
                             're-audit REQUIRED before Phase 4.',
                             'Falsification re-audit (single-check)', 'llm_subagent',
                             prompt=str(prompts / 'critique.txt') + ' — section "Falsification re-audit mode" ONLY',
                             inputs=[str(final_candidate)],
                             output=str(reaudit),
                             notes='Routing signal: `verdict` (advance | abandon). Exactly one '
                                   'rewrite attempt per run — deficient again means abandon.',
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
        return _emit('Skeleton built.', 'Phase 4.fill — author the prose TODOs', 'llm_subagent',
                     prompt=str(prompts / 'expand.txt'),
                     inputs=[str(p4_dir / 'phase4_skeleton.json')],
                     output=str(p4_dir / 'fill_map.json'),
                     notes='Flat {TODO-path: prose} map ONLY — the assembler refuses kill-switch '
                           'roots. This is the most timeout-prone call: NEVER run it in the '
                           'parent context.',
                     run_dir=d)
    if not expansion_done:
        return _emit('fill_map written.', 'Phase 4 assemble (deterministic)', 'bash',
                     run=[skill_cd + 'phase4_assemble '
                          f'--skeleton "{p4_dir / "phase4_skeleton.json"}" '
                          f'--fill-map "{p4_dir / "fill_map.json"}" --out "{p4_dir}/"'],
                     run_dir=d)
    if not (p4_dir / 'phase4_implementability.json').exists():
        return _emit('Expansion assembled.', 'Phase 4.1.5 — implementability audit', 'llm_subagent',
                     prompt=str(prompts / 'implementability_audit.txt'),
                     inputs=[str(p4_dir / 'phase4_expansion.json')],
                     output=str(p4_dir / 'phase4_implementability.json'),
                     notes='Fresh skeptical-engineer persona (separate call from 4.fill). '
                           'Compute-agnostic by design.',
                     run_dir=d)

    # ---- validate + render -----------------------------------------------------------
    phase3_for_validate = p3r if on_revise_path else p3q
    return _emit('All Phase 4 JSONs present; cards not yet rendered.',
                 'Validate, then render the idea cards', 'bash',
                 run=[skill_cd + 'validate '
                      f'--phase2 "{canonical}" --phase3 "{phase3_for_validate}" '
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
    if not run_dir.exists():
        print(f'ERROR: run dir {run_dir} does not exist. Create it first '
              f'(mkdir -p) — it is the --out root every phase writes under. '
              f'Convention: $PWD/ideaspark_run/<topic-slug> (one run = one dir; '
              f'never reuse a dir that already has a phase0/).', file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parent.parent
    return next_step(run_dir, root, getattr(args, 'query', None) or None)
