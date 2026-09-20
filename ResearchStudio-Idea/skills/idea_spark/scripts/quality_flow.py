"""Versioned phase-2+ navigation. Existing retrieval and bounded retry machinery is reused.

Model work is emitted, never invoked here. Every emitted model result is an
envelope committed by quality_record, so existence alone cannot skip a gate.
"""
from __future__ import annotations
import json
import os
import shlex
from pathlib import Path
from scripts.quality_contract import (CARDS, VERSION, read, digest, fingerprint, object_level_survivors, run_depth,
    input_hashes, has_contract, receipt_valid, stage_dir, change_scope, selection_findings,
    review_findings, implementability_findings, cost_findings, coherence_findings, critique_findings, candidate_findings, finding,
    implementation_points, prune_findings, disposition_findings, resolve_finding_ref, repair_findings, claim_texts)

P1 = 'phase1/phase1_output.json'
SEL = 'phase2_select/phase2_select_output.json'
GEN = 'phase2_generate/phase2_generate_output.json'
COH = 'phase2_coherence/phase2_coherence_output.json'
REFINED = 'phase2_coherence/refined_candidate.json'
CRIT = 'phase3_critique/phase3_critique_output.json'
REV = 'phase3_revise/phase3_revise_output.json'
FINAL = 'phase3_revise/final_candidate.json'
POST = 'phase3_revise/post_revision_audit.json'
SKEL = 'phase4/work/phase4_skeleton.json'
TECH = 'phase4/work/technical_expansion.json'
IMPL = 'phase4/work/phase4_implementability.json'
REPAIRED = 'phase4/work/repaired_technical.json'
TECH_REVIEW = 'phase4/work/technical_review.json'
COST = 'phase4/work/cost_assessment.json'
COST_REVISED = 'phase4/work/cost_assessment_revised.json'


def cost_path(run):
    """The cost figures the card and the publish gate use: the repair's re-figured ones when a review checked them."""
    return COST_REVISED if (Path(run) / COST_REVISED).exists() and receipt_valid(run, 'technical_review') else COST
EXP = 'phase4/work/phase4_expansion.json'
FIDELITY = 'phase4/work/fidelity_review.json'
REPAIRED_CAND = 'phase2_coherence/repaired_candidate.json'
REPAIR = 'phase2_coherence/formula_repair.json'
ROUNDS = 'phase2_coherence/repair_rounds.json'
BLOCKING = 'phase2_coherence/blocking_findings.json'
FAILED_CARD = 'phase4/work/failed_card.json'
P4_FINDINGS = 'phase3_revise/post_revision_findings.json'
REVISION_BASE = 'phase3_revise/revision_base.json'      # the last accepted text; a re-revision patches THIS


def terms_of(c):
    """The two retrieval term lists of a candidate (or query), order-insensitive."""
    return {k: sorted(map(str, (c or {}).get(k) or [])) for k in ('signature_terms', 'alias_terms')}


def failed_card_enabled():
    """A run whose validation ends in failure still prints its last candidate as a card that says so
    (the user's rule). IDEASPARK_FAILED_CARD=off restores the refusal."""
    return os.environ.get('IDEASPARK_FAILED_CARD', 'on').lower() not in ('off', '0', 'false')


def coherence_base(run):
    """The candidate the coherence trace runs on: the latest formula-repaired candidate, else Phase 2.2."""
    return REPAIRED_CAND if (Path(run) / REPAIRED_CAND).exists() else GEN


def command(root, name, **kwargs):
    parts = ['python3', str(root / 'scripts/run.py'), name]
    for k, v in kwargs.items():
        if v is not None:
            parts.extend(['--' + k.replace('_', '-'), str(v)])
    return shlex.join(parts)


AUTHOR_STAGES = ('generation', 'formula_repair', 'revision', 'technical_fill', 'technical_repair')
AUDIT_STAGES = ('coherence', 'critique', 'refutation', 'post_revision', 'post_novelty', 'technical_review')
IDEA_NOTES = {
    'author': ' DEPTH=idea: state everything over named VARIABLES (symbol + selection rule or admissible range). '
              'Give a number only when the mechanism\'s definition fixes it or a cited paper measured it; no sample '
              'sizes, windows, thresholds, grid cells or budget arithmetic — those belong to an experiment not yet designed.',
    'audit': ' DEPTH=idea: the candidate declares variables, not constants. Instantiate them with your OWN illustrative '
             'values and say which. A finding that holds only for particular values, while some admissible assignment lets '
             'the rule compute and the claim hold, is tag=parameter: a note, never blocking, never a revision target on its '
             'own. Never fault a missing number, window, sample size or threshold.',
    'implementability': ' DEPTH=idea: list, step by step, what an implementer would still have to decide or what is missing '
                        '(status instantiated | stopped with the reason). Executing is optional: dry_run.execution.mode may be '
                        '"unexecuted" with reason "idea depth". Cost is an order-of-magnitude judgement against the ceiling, with '
                        'the driver named. Nothing here gates the card; it informs the reader.'}


def spec(run, root, stage, inputs, outputs, prompts, notes=''):
    if run_depth(run) == 'idea':          # experiment-depth specs are unchanged, so earlier runs keep their receipts
        notes += IDEA_NOTES['implementability'] if stage == 'implementability' else (
            IDEA_NOTES['author'] if stage in AUTHOR_STAGES else IDEA_NOTES['audit'] if stage in AUDIT_STAGES else '')
    return {'stage': stage,
        'inputs': [str(run / p) for p in inputs] + [str(run / 'run_contract.json')],
        'outputs': outputs,
        'prompts': [str(root / 'references/system-prompts' / p) for p in prompts],
        'notes': notes}


def pending(run, root, sp):
    """Return a next action, or None when this exact stage has a current receipt."""
    if receipt_valid(run, sp['stage'], sp):
        return None
    sd = stage_dir(run, sp['stage']); req = read(sd / 'request.json', {})
    try:
        current = input_hashes(sp['inputs'] + sp['prompts'])
    except ValueError as e:
        return action('needs_work', 'Required stage input missing', 'terminal', notes=str(e), then=False)
    valid_request = req.get('inputs_sha256') == current and all(req.get(k) == v for k, v in sp.items())
    prior_receipt = read(sd / 'receipt.json', {})
    if prior_receipt.get('request_id') == req.get('request_id') and prior_receipt:
        valid_request = False  # committed but invalid output cannot simply be re-sealed
    if not valid_request:
        return action('REVIEW_REQUIRED', 'Prepare version-bound ' + sp['stage'], 'bash',
            run=[command(root, 'quality_prepare', dir=run, spec_json=json.dumps(sp, ensure_ascii=False))])
    result = read(sd / 'result.json', {})
    rej = read(sd / 'rejection.json', {})
    rejected = (rej.get('request_id') == req.get('request_id') and not rej.get('accepted')
                and rej.get('result_sha256') == fingerprint(sd / 'result.json'))
    parts = sorted((sd / 'result.parts').glob('*.json')) if (sd / 'result.parts').is_dir() else []
    if (result.get('request_id') == req.get('request_id') and not rejected) or (parts and not result):
        return action('RESULT_READY', 'Commit version-bound ' + sp['stage'], 'bash',
                      run=[command(root, 'quality_record', dir=run, stage=sp['stage'])])
    back = ('' if not rejected else
            ' YOUR PREVIOUS RESULT WAS REJECTED (attempt ' + str(rej.get('attempts')) + '); fix exactly these in '
            'result.json and leave the rest as it is: ' + ' | '.join(f.get('message', '')[:400] for f in rej.get('findings', [])))
    return action('REVIEW_REQUIRED', sp['stage'], 'llm_subagent',
        prompt=sp['prompts'][0] if sp['prompts'] else None,
        inputs=[str(sd / 'request.json')] + sp['inputs'] + sp['prompts'][1:],
        output=str(sd / 'result.json'),
        notes=('Execute in a fresh context. Read request.json FIRST. Do not write the requested '
               'artifact paths directly. Write ONE JSON envelope {"request_id": "' + req['request_id'] +
               '", "artifacts": {"relative/output/path": <the JSON requested by its prompt>}}. '
               'Exactly the outputs listed in the request. Source artifacts remain unchanged until '
               'quality_record checks their versions. A large artifact may be written in parts instead: '
               + str(sd / 'result.parts') + '/NN.json, each {"artifacts": {"relative/output/path": {some top-level '
               'fields}}}; quality_record merges them in name order (keep each part under ~25 KB). ' + sp['notes'] + back))


def action(state, step, kind, **kwargs):
    return dict(state=state, step=step, kind=kind, **kwargs)


def problem(run, root, findings):
    fs = [f for f in findings if f['severity'] == 'fail']
    if not fs:
        return None
    return action('needs_work', 'Preserve draft and report blocking findings', 'bash',
        run=[command(root, 'quality_needs_work', dir=run,
                     findings_json=json.dumps(fs, ensure_ascii=False))], then=True,
        notes='No render-as-success override. These are contract/review findings, not an experimental verdict.')


def authoritative_candidate(run):
    if read(run / CRIT, {}).get('verdict') == 'revise' and receipt_valid(run, 'revision_materialize'):
        return FINAL
    if receipt_valid(run, 'wording_materialize'):
        return REFINED                      # the author's wording round on the traced candidate
    return coherence_base(run)


def repair_loop(d, root, canonical):
    """Executed blocking findings no longer decide the run at first sight. They go to the author for
    bounded FORMULA repair rounds (definitions, normalisations, indices, initial conditions), and a
    fresh coherence trace re-executes each repaired candidate. Wording suggestions (W#) alone never
    buy a call: they ride to the revision stage as advisory input. The loop stops when the findings clear,
    when a round yields no information gain (the executed finding count did not fall), when the author
    declares that the only fix changes the intervention object, or at IDEASPARK_REPAIR_ROUNDS (3).
    Whatever survives goes to the audit as before. Observed: 20 of 21 candidate cycles across two
    skills died at this gate on their first execution; most of those defects were formula-shaped."""
    bf = read(d / BLOCKING, {}); blocking = bf.get('findings', []); suggested = bf.get('suggested_repairs', [])
    if (d / '.formula_repair_stop').exists() or receipt_valid(d, 'wording_materialize'):
        return None                                   # the author's round on this trace is done
    if not blocking:
        return None                                   # W#-only: no repair call; the reviser gets the W# list
    rounds = read(d / ROUNDS, {}).get('rounds', [])
    if blocking and len(rounds) >= int(os.environ.get('IDEASPARK_REPAIR_ROUNDS', '3')):
        return None
    if blocking and rounds:
        status = [s for s in (read(d / COH).get('previous_findings_status') or []) if isinstance(s, dict)]
        if status:
            if any(s.get('status') != 'resolved' for s in status):
                return None                           # a repaired finding persists: the repair did not repair
        elif len(blocking) >= rounds[-1]['blocking']:
            return None                               # no per-finding status reported: fall back to the count rule
    inputs = [canonical, COH, BLOCKING, SEL] + ([ROUNDS] if (d / ROUNDS).exists() else [])
    if (d / 'phase2_coherence/repair_findings.json').exists():
        inputs.append('phase2_coherence/repair_findings.json')
    rp = spec(d, root, 'formula_repair', inputs, [REPAIR], ['formula_repair.txt'],
              'Author-side. Repair the FORMULA each executed blocking finding (B#) names (definition, normalisation, '
              'index, initial condition); re-run the tracer\'s script against the repaired rule and paste script '
              'and output in rerun. Apply or keep (skipped_author_keeps, premise stated) each suggested wording '
              'repair (W#). Never change the intervention object: declare changes_object=true instead. '
              'base_candidate_sha256 from request candidate_digests; target_id = B# / W#.')
    a = pending(d, root, rp)
    if a: return a
    fs = repair_findings(read(d / REPAIR), read(d / canonical), blocking, suggested)
    if any(f['severity'] == 'fail' for f in fs) and not (d / '.repair_retry_used').exists():
        return action('REREPAIR', 'Re-issue the repair patch against the contract findings (once)', 'bash',
                      run=[command(root, 'quality_materialize', dir=d, operation='repair_retry',
                                   findings_json=json.dumps([f for f in fs if f['severity'] == 'fail'], ensure_ascii=False))])
    a = problem(d, root, fs)
    if a: return a
    return action('REPAIR', 'Apply the formula repair; the coherence trace re-executes the repaired candidate', 'bash',
                  run=[command(root, 'quality_materialize', dir=d, operation='formula_repair')])


def late_flow(d, root, failed=False):
    """Return an action after Phase 1 has completed, without mutating any file.

    `failed`: the run's validation already ended in failure (phase4/work/failed_card.json holds the
    record); every gate that would stop the run is a no-op and the last candidate goes through the
    card stages it has not run yet, then publishes as a card marked FAILED VALIDATION."""
    def gate(fs):
        return None if failed else problem(d, root, fs)
    retry_inputs = [str(p.relative_to(d)) for p in sorted(d.glob('attempt_*/*/*.json'))
                    if p.name in ('phase3_critique_output.json', 'post_revision_audit.json',
                                  'blocking_findings.json', 'phase2_select_output.json')]
    # Phase 2 first materialises a slim closest_adjacent slice (phase2_prepare);
    # handing the sub-agent the whole fulltext cache instead is the timeout anti-pattern the
    # host runbook's context discipline exists to prevent. Same deterministic step here.
    if not (d / 'phase2_generate/closest_abstracts.json').exists():
        return action('PREPARE', 'Materialise the slim Phase 2 input slice (deterministic)', 'bash',
                      run=[command(root, 'phase2_prepare', dir=d)])
    gen_inputs = [P1, 'phase0/user_query.txt', 'phase0/lit_table.md', 'phase2_generate/closest_abstracts.json']
    if (d / 'phase2_generate/selection_findings.json').exists():
        gen_inputs.append('phase2_generate/selection_findings.json')
    p2 = spec(d, root, 'generation', gen_inputs + retry_inputs,
              [SEL, GEN], ['ideate_select.txt', 'ideate_generate.txt'],
              'Perform selection then generation in the SAME context. Include contract_version=2 in both. '
              'Pattern/reference files listed as inputs are evidence, not a composition quota.' +
              (' phase2_generate/selection_findings.json is the deterministic gate\'s verdict on your previous '
               'selection; it names the exact rule that failed. Resolve it — do not relabel it.'
               if len(gen_inputs) == 5 else ''))
    p2['inputs'] += [str(root / 'references/ideation-patterns'), str(root / 'references/ideation-sub-patterns')]
    if (d / 'context/cross_run.json').exists():
        p2['inputs'].append(str(d / 'context/cross_run.json'))
    a = pending(d, root, p2)
    if a: return a
    from scripts.validators import validate_subpattern_citation_consistency, validate_alias_collateral_coverage
    sel = read(d / SEL); phase1 = read(d / P1); raw = read(d / GEN)
    fs = selection_findings(sel, phase1.get('intake', {}).get('contribution_type'))
    archived = [read(p, {}) for p in sorted(d.glob('attempt_*/phase2_generate/phase2_generate_output.json'))]
    fs += candidate_findings(raw, sel, archived)
    fs += validate_subpattern_citation_consistency(str(d / GEN))
    fs += validate_alias_collateral_coverage(str(d / GEN), str(d / P1))
    if any(f['severity'] == 'fail' for f in fs) and not (d / '.generation_retry_used').exists():
        # A selection the deterministic gate rejects is regenerated once with the findings as input.
        # The second rejection is terminal — no open-ended loop.
        return action('REGENERATE', 'Re-run selection + generation against the gate findings (once)', 'bash',
                      run=[command(root, 'quality_materialize', dir=d, operation='generation_retry',
                                   findings_json=json.dumps([f for f in fs if f['severity'] == 'fail'],
                                                            ensure_ascii=False))])
    a = gate(fs)
    if a: return a

    co_inputs = [coherence_base(d), SEL] + (['phase2_coherence/previous_findings.json'] if (d / 'phase2_coherence/previous_findings.json').exists() else [])
    co = spec(d, root, 'coherence', co_inputs, [COH], ['coherence_trace.txt'],
              'Write the coherence report only; blocking_findings and any refined candidate are '
              'deterministic derivatives. Patches need contract_version=2 and base_candidate_sha256 '
              'equal to the canonical JSON digest in request candidate_digests. No novelty redesign. '
              'Execute the candidate\'s own rules on synthetic inputs; never simulate a learned component. '
              'A blocking finding needs tag=structural and a derivation; untagged ones become notes.')
    a = pending(d, root, co)
    if a: return a
    coherence = read(d / COH)
    a = gate(coherence_findings(coherence))
    if a: return a
    if coherence.get('verdict') not in ('pass', 'findings'):
        a = gate([finding('coherence', 'Invalid coherence verdict')])
        if a: return a
    if not receipt_valid(d, 'coherence_materialize'):
        return action('DERIVE', 'Materialize canonical candidate and blocking evidence', 'bash',
                      run=[command(root, 'quality_materialize', dir=d, operation='coherence')])
    canonical = REFINED if receipt_valid(d, 'wording_materialize') else coherence_base(d)
    a = repair_loop(d, root, canonical)
    if a: return a

    # Every surviving executed blocking finding was declared object-level by the author and persisted in
    # the re-trace: the audit's hard floor is already decided on the record, so the abandon is written
    # deterministically (facts + salvage) and the audit call is not spent. Observed twice (dllm cycle 1,
    # self-evolution cycle 1): the audit restated the ledger and abandoned.
    if not failed and object_level_survivors(read(d / ROUNDS, {}).get('rounds', []), read(d / COH), read(d / BLOCKING, {}).get('findings', [])):
        if not (read(d / CRIT, {}).get('source') == 'object_abandon' and receipt_valid(d, 'critique')):
            return action('ABANDON_OBJECT', 'Every surviving blocking finding is author-declared object-level: '
                          'write the abandon on the record (no audit call)', 'bash',
                          run=[command(root, 'quality_materialize', dir=d, operation='object_abandon')])
        return action('ABANDON', 'Apply existing bounded information-gain retry', 'bash',
                      run=[command(root, 'quality_retry', dir=d)])
    if not receipt_valid(d, 'collision'):
        return action('RETRIEVAL_REQUIRED', 'Run existing dual-channel collision retrieval', 'bash',
                      run=[command(root, 'quality_collision', dir=d, candidate=canonical)])
    cr = spec(d, root, 'critique', [canonical, SEL, P1, 'phase0/lit_table.md',
              'phase3_collision/collision_hits.json', 'phase2_coherence/blocking_findings.json'],
              [CRIT], ['critique.txt'],
              'Every revision target has target_id R1, R2, ... . Disposition every blocking '
              'finding using its exact finding_id B1, B2, ... as finding_ref. A pattern mismatch '
              'alone cannot create a scientific defect. No fabricated theory to fit a C##.')
    if (d / 'phase3_critique/critique_findings.json').exists():
        cr['inputs'].append(str(d / 'phase3_critique/critique_findings.json'))
        cr['notes'] += (' phase3_critique/critique_findings.json is the deterministic validator\'s verdict on your '
                        'previous report (a contract violation, not a scientific point); produce the report again '
                        'with exactly that fixed.')
    if (d / ROUNDS).exists(): cr['inputs'].append(str(d / ROUNDS))   # what the repair rounds tried and how it went
    a = pending(d, root, cr)
    if a: return a
    critique = read(d / CRIT)
    from scripts.validators import validate_threat_grounding
    bf = read(d / 'phase2_coherence/blocking_findings.json', {}).get('findings', [])
    fs = critique_findings(critique) + disposition_findings(critique, bf) + validate_threat_grounding(d / CRIT)
    if any(f['severity'] == 'fail' for f in fs) and not (d / '.critique_retry_used').exists():
        # Same bounded pattern as REGENERATE: a report that breaks the audit contract is re-run once
        # with the validator's findings as input; the second violation is terminal.
        return action('REAUDIT', 'Re-run the audit against the validator findings (once)', 'bash',
                      run=[command(root, 'quality_materialize', dir=d, operation='critique_retry',
                                   findings_json=json.dumps([f for f in fs if f['severity'] == 'fail'],
                                                            ensure_ascii=False))])
    a = gate(fs)
    if a: return a
    verdict = critique.get('verdict')
    if verdict == 'abandon' and not failed:
        return action('ABANDON', 'Apply existing bounded information-gain retry', 'bash',
                      run=[command(root, 'quality_retry', dir=d)])
    if verdict not in ('advance', 'revise', 'abandon'):
        a = gate([finding('critique', 'Invalid audit verdict')])
        if a: return a
    ids = [b['finding_id'] for b in bf]
    dispositions = [dict(x, finding_ref=resolve_finding_ref(x.get('finding_ref'), ids))
                    for x in critique.get('blocking_findings_disposition', [])]
    refuted = [x for x in dispositions if x.get('status') == 'refuted']
    if refuted:
        rr = spec(d, root, 'refutation', [canonical, CRIT, 'phase2_coherence/blocking_findings.json'],
                  ['phase3_critique/refutation_recheck.json'], ['refutation_recheck.txt'])
        a = pending(d, root, rr)
        if a: return a
        rechecks = read(d / rr['outputs'][0]).get('rechecks', [])
        valid = {r.get('finding_ref') for r in rechecks if r.get('refutation_valid') is True}
        if not {r['finding_ref'] for r in refuted} <= valid:
            a = gate([finding('invalid_refutation', 'Executed evidence remains unrefuted')])
            if a: return a
    if verdict == 'advance' and any(x.get('status') == 'upheld' for x in dispositions):
        a = gate([finding('blocking_disposition', 'Cannot advance over upheld evidence')])
        if a: return a

    selected = canonical
    # A falsification revision requested from Phase 4 (technical review found the declared experiment
    # infeasible under corrected arithmetic) re-enters the same bounded revision transaction.
    p4rev = read(d / P4_FINDINGS, {}).get('source') == 'technical_review'
    if verdict == 'revise' or p4rev:
        rebase = (d / REVISION_BASE).exists() and (d / P4_FINDINGS).exists()
        rv_inputs = [REVISION_BASE if rebase else canonical, CRIT, SEL]
        if (d / BLOCKING).exists() and read(d / BLOCKING, {}).get('suggested_repairs') and not rebase:
            rv_inputs.append(BLOCKING)       # W# wording suggestions the trace made: apply or state why not
        if (d / P4_FINDINGS).exists():
            rv_inputs.append(P4_FINDINGS)
        rv = spec(d, root, 'revision', rv_inputs, [REV], ['revise.txt'],
                  'Use contract_version=2, target_id on every operation, and base_candidate_sha256 '
                  'from request candidate_digests. Multiple operations per target are allowed. '
                  'Flag invalid repair requests with evidence instead of inventing a method.' +
                  (' phase2_coherence/blocking_findings.json suggested_repairs (W#) are the trace\'s wording '
                   'suggestions: apply each or state the premise that keeps it.' if BLOCKING in rv_inputs else '') +
                  (' RE-REVISION: the patch applies to phase3_revise/revision_base.json, the last accepted text, which '
                   'already contains every earlier target; base_candidate_sha256 is ITS digest (candidate_digests). Issue '
                   'operations ONLY for the targets in phase3_revise/post_revision_findings.json; do not re-issue earlier '
                   'R#/W# ops.' if rebase else '') +
                  (' The technical review names a falsification target: rewrite_falsification keeping the SAME minimal '
                   'experiment, metric and load-bearing variable, changing only what it names infeasible.' if p4rev else
                   ' phase3_revise/post_revision_findings.json is the independent review of your previous '
                   'patch; resolve exactly what it names.' if P4_FINDINGS in rv_inputs else ''))
        a = pending(d, root, rv)
        if a: return a
        if not receipt_valid(d, 'revision_materialize') and not receipt_valid(d, 'consistency_patch'):
            return action('MERGE', 'Merge the whole revision transaction', 'bash',
                          run=[command(root, 'quality_materialize', dir=d, operation='revision')])
        selected = FINAL
        a = gate(validate_subpattern_citation_consistency(d / FINAL) +
                 validate_alias_collateral_coverage(d / FINAL, d / P1))
        if a: return a
        delta = change_scope(read(d / canonical), read(d / FINAL))
        delta['required_checks'].append('target_resolution')
        # The reviser may have changed the retrieval terms (an audit-demanded alias, say). The pool is
        # refreshed BEFORE the review, so the reviewer's novelty check sees the terms the text now carries
        # and no separate novelty call follows. Observed: every post-novelty call so far passed on a pool
        # the reviewer could have read in the same sitting.
        pool = 'phase3_collision/collision_hits.json'
        reviewed = receipt_valid(d, 'post_revision') or receipt_valid(d, 'consistency_patch')
        if terms_of(read(d / FINAL)) != terms_of(read(d / canonical)):
            if not reviewed and not (receipt_valid(d, 'post_collision') and terms_of(read(d / 'phase3_revise/collision_query.json', {})) == terms_of(read(d / FINAL))):
                return action('RETRIEVAL_REQUIRED', 'Refresh collision for the revised retrieval terms', 'bash',
                              run=[command(root, 'quality_collision', dir=d, candidate=FINAL, post='yes')])
            pool = 'phase3_revise/collision/collision_hits.json'
        pr = spec(d, root, 'post_revision', [canonical, FINAL, REV, CRIT, SEL,
                  'phase2_coherence/blocking_findings.json', pool] +
                  ([REVISION_BASE] if (d / REVISION_BASE).exists() else []) + ([P4_FINDINGS] if (d / P4_FINDINGS).exists() else []),
                  [POST], ['post_revision_audit.txt'],
                  'Required checks: ' + ', '.join(delta['required_checks']) +
                  '. Reviewer is separate from reviser. Check the changed method even if retrieval '
                  'terms are unchanged. Report confirmed_terms={signature_terms:[],alias_terms:[]}.' +
                  (' The collision pool was refreshed for the revised terms; novelty is checked against it here.'
                   if pool != 'phase3_collision/collision_hits.json' else '') +
                  ' Field-level inconsistencies alone (a stale number, name or clause in another field) do not '
                  'need another revision: fix them in consistency_patch and pass.')
        if not receipt_valid(d, 'consistency_patch'):
            a = pending(d, root, pr)
            if a: return a
        post = read(d / POST)
        # The reviewer's own bounded consistency fixes (exact-substring replacements in mechanism prose)
        # are applied deterministically; a re-revision and a second review are not spent on them.
        if post.get('verdict') == 'pass' and post.get('consistency_patch') and not receipt_valid(d, 'consistency_patch'):
            return action('CONSISTENCY_PATCH', 'Apply the reviewer\'s bounded field-level consistency fixes (deterministic)', 'bash',
                          run=[command(root, 'quality_materialize', dir=d, operation='consistency_patch')])
        if post.get('verdict') == 'redesign':
            return action('REDESIGN', 'Apply bounded retry; do not append another repair', 'bash',
                          run=[command(root, 'quality_retry', dir=d)])
        fs = review_findings(post, delta['required_checks']) + prune_findings(post, read(d / FINAL))
        prunable = [f for f in fs if f['validator'] == 'prune_component']
        if prunable and not (d / '.revision_retry_used').exists():
            # A component the removal test shows to be decorative is deleted by the same bounded
            # re-revision that fixes a defect; if that round is spent the finding stays a warn.
            return action('REREVISE', 'Re-run the revision to prune non-load-bearing components (once)', 'bash',
                          run=[command(root, 'quality_materialize', dir=d, operation='revision_retry')])
        if any(f['severity'] == 'fail' for f in fs) and post.get('verdict') == 'needs_work' and not (d / '.revision_retry_used').exists() and not failed:
            # One more revision pass with the reviewer's findings as input; the second
            # needs_work is terminal. Not a free-form loop: exactly one extra transaction.
            return action('REREVISE', 'Re-run the revision transaction against the review findings (once)',
                          'bash', run=[command(root, 'quality_materialize', dir=d, operation='revision_retry')])
        a = gate(fs)
        if a: return a
        if delta['novelty']:
            terms = post.get('confirmed_terms', {})
            if not terms.get('signature_terms') or not terms.get('alias_terms'):
                a = gate([finding('novelty_reaudit', 'Changed method needs confirmed retrieval terms')])
                if a: return a
                terms = {'signature_terms': [], 'alias_terms': []}
            # The novelty call is spent only when the reviewer confirms terms the pool was NOT built on
            # (rare: the reviewer changed them); a reviewer confirming the text's own terms is done.
            pool_terms = terms_of(read(d / FINAL)) if pool != 'phase3_collision/collision_hits.json' else terms_of(read(d / canonical))
            changed_terms = terms_of(terms) != pool_terms
            if changed_terms:
                if not (receipt_valid(d, 'post_collision') and terms_of(read(d / 'phase3_revise/collision_query.json', {})) == terms_of(terms)):
                    return action('RETRIEVAL_REQUIRED', 'Refresh collision for reviewer-confirmed terms', 'bash',
                                  run=[command(root, 'quality_collision', dir=d, candidate=FINAL, post='confirmed')])
                nr = spec(d, root, 'post_novelty', [FINAL, POST, 'phase3_revise/collision/collision_hits.json'],
                          ['phase3_revise/novelty_reaudit.json'], ['post_revision_audit.txt'],
                          'Only required check: novelty. Use the refreshed retrieved evidence.')
                a = pending(d, root, nr)
                if a: return a
                a = gate(review_findings(read(d / nr['outputs'][0]), ['novelty']))
                if a: return a
        # An authorized falsification rewrite is checked inside post_revision (change_scope adds the
        # `falsification` check), not by a separate re-audit call: 2/2 standalone re-audits in one recorded comparison
        # advanced, each costing a reasoning-tier call.

    if not receipt_valid(d, 'skeleton'):
        return action('DERIVE', 'Build the technical skeleton and source mechanism record', 'bash',
                      run=[command(root, 'quality_materialize', dir=d, operation='skeleton')])
    prior = 'phase4/work/before_falsification_revision/repaired_technical.json'
    if not (d / prior).exists(): prior = 'phase4/work/before_falsification_revision/technical_expansion.json'
    fill = spec(d, root, 'technical_fill', [SKEL, selected, 'phase4/work/mechanism_record.json', P1, CRIT,
                'phase0/lit_table.md'] + ([prior] if (d / prior).exists() else []),
                ['phase4/work/fill_map.json'], ['expand.txt'],
                'Technical TODO fields only. Do not fill plain_* or title_zh. No new scientific facts.' +
                (' ' + prior + ' is the technical text written for this candidate BEFORE its falsification revision: '
                 'keep everything the revision did not touch; change only what the new falsification requires.'
                 if (d / prior).exists() else ''))
    a = pending(d, root, fill)
    if a: return a
    if not receipt_valid(d, 'technical_assemble'):
        return action('ASSEMBLE', 'Assemble technical prose before plain-language derivation', 'bash',
                      run=[command(root, 'quality_materialize', dir=d, operation='technical')])
    imp = spec(d, root, 'implementability', [TECH, selected, 'phase4/work/mechanism_record.json', P1],
               [IMPL, COST], ['implementability_audit.txt'],
               'Two artifacts: the audit-only report and cost_assessment.json bound to candidate_sha256 '
               'from request candidate_digests, keeping user budget and original estimate verbatim.')
    a = pending(d, root, imp)
    if a: return a
    impl = read(d / IMPL); technical = read(d / TECH)
    fs_impl = implementability_findings(impl, technical)
    fs_cost = cost_findings(read(d / COST), read(d / selected), phase1)
    a = gate([f for f in fs_cost if f['validator'] != 'cost_assessment' or 'exceeds' not in f['message']] +
             [f for f in fs_impl if f['validator'] == 'implementability_completeness'])
    if a: return a
    # An estimate over the ceiling is routed to the same bounded repair when it hinges on an unspecified
    # implementation choice (batching, grid size): the repair specifies the choice and re-figures the
    # cost; the technical review checks the arithmetic. Observed: '50 to 185 GPU-day, 185 if the grid
    # decodes at batch 1' against a 150-day ceiling — a choice, not a property of the idea.
    cost_over = [f for f in fs_cost if f['validator'] == 'cost_assessment' and 'exceeds' in f['message']]
    # One bounded technical repair for everything the trace stopped on or contradicted: a source
    # omission is transcribed from the candidate; an undefined operation a claim depends on is
    # SPECIFIED as a preregistered choice; a contradiction is reconciled with the candidate. The
    # repaired text then gets its own executed review, which decides. Observed: a missing
    # crop->concept assignment rule ended a run that one sentence would have specified.
    trace_fails = [f for f in fs_impl if f['severity'] == 'fail']
    repairable = [p for p in implementation_points(impl, technical) if p.get('kind') in ('source_omission', 'mechanism_blocking')]
    tech_input = TECH
    # In failed mode no new repair/review call is spent: the stages already recorded are used as they are.
    # idea depth: the trace's holes and contradictions go on the detail card; no repair, no review, no
    # falsification-revision route. Observed: both Phase 4 failures of one run were an experiment cell and a
    # label an experimenter fixes in minutes, at a cost of fifteen calls and a FAILED card.
    idea = run_depth(d) == 'idea'
    if (trace_fails or repairable or cost_over) and not idea and (not failed or receipt_valid(d, 'technical_repair')):
        repair = spec(d, root, 'technical_repair', [TECH, IMPL, selected, 'phase4/work/mechanism_record.json'] + ([COST, P1] if cost_over else []),
                      ['phase4/work/technical_repairs.json'], ['technical_repair.txt'],
                      'One bounded patch; the review of the repaired text decides. Resolve: ' +
                      ' | '.join(f"{p['step_id']} ({p['kind']}): {p['hole'][:140]}" for p in repairable) +
                      (' | ' + ' | '.join(f['message'][:140] for f in trace_fails) if trace_fails else '') +
                      (' | COST: ' + cost_over[0]['message'][:200] + ' — specify the implementation choice the estimate hinges on and supply cost_revision' if cost_over else '') +
                      ' No core redesign: specify, transcribe, reconcile.')
        a = pending(d, root, repair)
        if a: return a
        if not receipt_valid(d, 'technical_repair_materialize'):
            return action('REPAIR', 'Apply source-grounded technical corrections', 'bash',
                          run=[command(root, 'quality_materialize', dir=d, operation='technical_repair')])
        tech_input = REPAIRED
        # A repair is the one technical text no earlier reviewer has read; it gets its own
        # check. When nothing was repaired the implementability audit already covered the
        # technical expansion, so no second reviewer call is spent (the archive's median run
        # is ~65 min against a 120 min wall; every reasoning-tier call costs ~10 min).
        revised = (d / COST_REVISED).exists()
        checks = ['source_fidelity', 'equations', 'evaluation_independence', 'implementability'] + (['cost'] if revised else [])
        tr = spec(d, root, 'technical_review', [tech_input, TECH, selected, IMPL,
                  'phase4/work/technical_repairs.json', 'phase4/work/mechanism_record.json', P1] + ([COST_REVISED, COST] if revised else []),
                  [TECH_REVIEW], ['technical_review.txt'],
                  'Required checks: ' + ', '.join(checks) + '. You review the REPAIRED text against its sources' +
                  ('; the repair re-figured the cost (phase4/work/cost_assessment_revised.json) after specifying the choice the '
                   'audit\'s estimate hinged on — check that arithmetic against the audit\'s figures and the ceiling.' if revised else
                   '; cost was assessed by the audit.'))
        if not failed or receipt_valid(d, 'technical_review'):
            a = pending(d, root, tr)
            if a: return a
            review = read(d / TECH_REVIEW)
            fs_review = review_findings(review, checks)
            # The review found the DECLARED experiment infeasible under corrected arithmetic and named a
            # bounded falsification change (same minimal experiment, metric, load-bearing variable): that
            # goes back through the audited revision transaction once, then Phase 4 re-runs on the revised
            # candidate. Observed: a corrected control-row count made one declared cell need 828 rows of 400,
            # and the only exit was failure.
            if (any(x['severity'] == 'fail' for x in fs_review) and review.get('route') == 'falsification_revision'
                    and review.get('revision_targets') and not (d / '.phase4_revision_used').exists() and not failed):
                return action('REVISE_FALSIFICATION', 'Route the infeasible declared experiment through one bounded '
                              'falsification revision', 'bash',
                              run=[command(root, 'quality_materialize', dir=d, operation='phase4_revision')])
            a = gate(fs_review)
            if a: return a
            if revised:
                a = gate(cost_findings(read(d / COST_REVISED), read(d / selected), phase1))
                if a: return a
    der_inputs = [tech_input, cost_path(d), IMPL]
    if (d / 'phase4/work/fidelity_findings.json').exists():
        der_inputs.append('phase4/work/fidelity_findings.json')
    der = spec(d, root, 'plain_derive', der_inputs, ['phase4/work/derive_map.json'],
               ['derive_plain.txt'], 'Audience: reader outside this subfield. Keep necessary explanations; '
               'no fixed short-card budget. Derive from this FINAL technical version only.' +
               (' phase4/work/fidelity_findings.json lists what the previous derivation got wrong; fix exactly '
                'those transfers.' if len(der_inputs) == 4 else ''))
    a = pending(d, root, der)
    if a: return a
    if not receipt_valid(d, 'final_assemble'):
        return action('ASSEMBLE', 'Assemble final shared Markdown/PDF source', 'bash',
                      run=[command(root, 'quality_materialize', dir=d, operation='final')])
    if failed or os.environ.get('IDEASPARK_FIDELITY', 'off').lower() not in ('on', '1', 'true'):
        # Off by default: the plain-vs-technical fidelity review never blocked in any recorded run
        # (0 executed fails across two recorded comparisons) while costing one reasoning-tier call per run.
        # IDEASPARK_FIDELITY=on restores it, with its bounded REDERIVE.
        if not receipt_valid(d, 'publication'):
            return action('READY_TO_RENDER', 'Validate and render the checked proposal', 'bash',
                          run=[command(root, 'quality_publish', dir=d)])
        if failed:
            rec = read(d / FAILED_CARD, {})
            return action('DONE', 'Return the last candidate as a card marked FAILED VALIDATION', 'terminal', then=False,
                          notes='FAILED VALIDATION (' + str(rec.get('stage')) + '): ' + str(rec.get('reason', ''))[:300] + ' ' +
                          ' '.join(str(d / 'phase4' / n) for n in CARDS))
        return action('DONE', 'Return current-version proposal cards', 'terminal', then=False,
                      notes='Research proposal; not experimentally validated. ' +
                      ' '.join(str(d / 'phase4' / n) for n in CARDS))
    fi = spec(d, root, 'fidelity', [EXP, selected, 'phase4/work/mechanism_record.json', cost_path(d), IMPL],
              [FIDELITY], ['fidelity_review.txt'],
              'Required checks: title_anchor, claims, assumptions, operators, evaluation_independence, '
              'resources, beginner_readability, bilingual_fidelity. Judge fidelity, not inventiveness.')
    a = pending(d, root, fi)
    if a: return a
    fidelity = read(d / FIDELITY)
    fs = review_findings(fidelity, ['title_anchor', 'claims', 'assumptions', 'operators',
                                    'evaluation_independence', 'resources', 'beginner_readability',
                                    'bilingual_fidelity'])
    if any(f['severity'] == 'fail' for f in fs) and fidelity.get('verdict') == 'needs_work' and not (d / '.fidelity_retry_used').exists() and not failed:
        # The plain derivation is a transfer step; a transfer error is fixed by re-deriving with the
        # reviewer's findings in hand, once. A second failure is terminal.
        return action('REDERIVE', 'Re-derive the plain cards against the fidelity findings (once)', 'bash',
                      run=[command(root, 'quality_materialize', dir=d, operation='fidelity_retry')])
    a = gate(fs)
    if a: return a
    if not receipt_valid(d, 'publication'):
        return action('READY_TO_RENDER', 'Validate and render the checked proposal', 'bash',
                      run=[command(root, 'quality_publish', dir=d)])
    return action('DONE', 'Return current-version proposal cards', 'terminal', then=False,
                  notes='Research proposal; not experimentally validated. ' +
                  ' '.join(str(d / 'phase4' / n) for n in CARDS))


def _navigate(run, root, query, emit, retrieval):
    d = Path(run).resolve(); root = Path(root).resolve()
    if not has_contract(d):
        if d.exists() and any(d.iterdir()):
            return emit('UNSUPPORTED_RUN_DIR', 'Start a new run directory', 'terminal',
                        notes='This directory holds files but no run_contract.json: it was not started by this '
                              'version of the skill and cannot be resumed. One run = one fresh directory.',
                        then=False, run_dir=d)
        return emit('NEW_RUN', 'Initialize the run contract', 'bash',
                    run=[command(root, 'quality_init', dir=d, query=query)], run_dir=d)
    nw = read(d / 'needs_work.json', {})
    execution_error = nw and any(f.get('validator') == 'execution_contract' for f in nw.get('findings', []))
    if nw and nw.get('input_fingerprint') == failure_fingerprint(d) and (execution_error or not failed_card_enabled()):
        return emit('needs_work', 'Preserved draft needs revision', 'terminal', then=False,
                    notes='; '.join(f['message'] for f in nw['findings']), run_dir=d)
    if (d / FAILED_CARD).exists() and read(d / P1, {}).get('state') == 'proceed':
        try:
            a = late_flow(d, root, failed=True)
        except (ValueError, KeyError, TypeError, OSError) as e:
            a = action('needs_work', 'Malformed or missing artifact', 'terminal', notes=str(e), then=False)
        return emit(**a, run_dir=d)
    validation_failed = ((nw and nw.get('input_fingerprint') == failure_fingerprint(d)) or (d / 'phase_3_failed.md').exists())
    if validation_failed and failed_card_enabled() and read(d / P1, {}).get('state') == 'proceed':
        return emit('FAILED_CARD', 'Record the failure and print the last candidate as a card marked FAILED VALIDATION',
                    'bash', run=[command(root, 'quality_materialize', dir=d, operation='failed_card')], run_dir=d)
    if (d / 'phase_3_failed.md').exists() or (d / 'do_not_generate.md').exists():
        return retrieval(d, root, query)
    p1 = read(d / P1, {})
    if p1.get('state') != 'proceed':
        if not query and (d / 'context/user_query.txt').exists():
            query = (d / 'context/user_query.txt').read_text()
        return retrieval(d, root, query)
    try:
        a = late_flow(d, root)
    except (ValueError, KeyError, TypeError, OSError) as e:
        a = action('needs_work', 'Malformed or missing artifact', 'terminal', notes=str(e), then=False)
    return emit(**a, run_dir=d)


def navigate(run, root, query, emit, retrieval):
    try:
        return _navigate(run, root, query, emit, retrieval)
    except (ValueError, KeyError, TypeError, OSError) as e:
        return emit('needs_work', 'Malformed or missing artifact', 'terminal',
                    notes=str(e), then=False, run_dir=Path(run))


def failure_fingerprint(run):
    # Draft changes invalidate a needs_work notice, never the underlying review gates.
    return digest({'artifacts': {str(p.relative_to(run)): fingerprint(p)
                   for p in sorted(Path(run).glob('phase*/*.json'))},
                   'pending_work': {str(p.relative_to(run)): fingerprint(p) for p in
                       sorted(Path(run).glob('.quality/*/*.json')) if p.name in ('request.json', 'result.json')},
                   'implementation': fingerprint(Path(__file__).parent),
                   'prompts': fingerprint(Path(__file__).parent.parent / 'references/system-prompts')})
