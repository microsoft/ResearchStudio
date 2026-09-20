"""Explicit mutating commands for v2. No model calls; collision delegates the unchanged connector CLI."""
from __future__ import annotations
import json
import re
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from scripts.quality_contract import *
from scripts.quality_flow import (P1, SEL, GEN, COH, REFINED, CRIT, REV, FINAL, POST, REPAIRED_CAND, REPAIR, ROUNDS, BLOCKING, COST_REVISED, cost_path, FAILED_CARD, P4_FINDINGS, REVISION_BASE,
    SKEL, TECH, IMPL, REPAIRED, TECH_REVIEW, COST, EXP, FIDELITY, authoritative_candidate,
    failure_fingerprint, late_flow)


def require(run, *stages):
    for s in stages:
        if receipt_valid(run, s):
            continue
        # A reviewer-applied consistency patch re-sealed the final candidate after the review and the
        # merge; its receipt stands in for both (the patch is derived from that review of that merge).
        if s in ('post_revision', 'revision_materialize') and receipt_valid(run, 'consistency_patch'):
            continue
        raise ValueError('Missing or stale stage: ' + s)


def materialize(d, root, operation, findings_json=None):
    from scripts.merge_revisions import merge_phase3_revisions, apply_patch
    from scripts.phase4_skeleton import build_skeleton, parse_lit_table, assemble_expansion
    base = REPAIRED_CAND if (d / REPAIRED_CAND).exists() else GEN
    canonical = REFINED if receipt_valid(d, 'wording_materialize') else base
    if operation == 'coherence':
        require(d, 'generation', 'coherence')
        co = read(d / COH)
        outputs = [BLOCKING]
        if co.get('applied_revisions'):
            raise ValueError('The trace reports; it does not patch (use suggested_repairs)')
        # Only a STRUCTURAL finding with its derivation blocks: the program enforces the tag the prompt
        # asks for. An instance-contingent number is a note for the falsification experiment. The gate's
        # wording fixes become W# suggestions the author applies or keeps.
        raw = [b for b in co.get('unrepaired', []) if b.get('severity') == 'blocking']
        nc = (co.get('trace_report') or {}).get('naive_comparison') or {}
        ablation = nc.get('naive_kind') == 'ablation' and nc.get('identity') == 'bit_identical'
        def blocks(b):
            if b.get('tag') not in ('impossibility', 'structural') or not str(b.get('derivation', '')).strip():
                return False
            return ablation if str(b.get('source', '')).upper() == 'T5' else True
        keep = [b for b in raw if blocks(b)]
        blocking = [{**b, 'finding_id': f'B{i + 1}'} for i, b in enumerate(keep)]
        suggested = [{**s, 'id': f'W{i + 1}'} for i, s in enumerate(co.get('suggested_repairs', []) or []) if isinstance(s, dict)]
        atomic_json(d / outputs[0], {'findings': blocking, 'suggested_repairs': suggested,
                                     'regime': [b for b in co.get('unrepaired', []) or [] if isinstance(b, dict) and b.get('tag') == 'regime'],   # any severity
                                     # holds only for particular VALUES of the candidate's variables: the experimenter's business, never blocking
                                     'parameter_notes': [b for b in co.get('unrepaired', []) or [] if isinstance(b, dict) and b.get('tag') == 'parameter'],
                                     't5_notes': [b for b in raw if str(b.get('source', '')).upper() == 'T5' and b not in keep],
                                     'demoted_to_notes': [b for b in raw if b not in keep and b.get('tag') not in ('regime', 'parameter')
                                                          and str(b.get('source', '')).upper() != 'T5']})
        stage = 'coherence_materialize'; inputs = [base, COH]
    elif operation == 'formula_repair':
        require(d, 'coherence_materialize', 'formula_repair')
        patch = read(d / REPAIR); before = read(d / canonical)
        bf = read(d / BLOCKING); blocking = bf['findings']; suggested = bf.get('suggested_repairs', [])
        fs = [f for f in repair_findings(patch, before, blocking, suggested) if f['severity'] == 'fail']
        if fs: raise ValueError('Repair patch violates its contract: ' + fs[0]['message'])
        ledger = read(d / ROUNDS, {'contract_version': VERSION, 'rounds': []}); n = len(ledger['rounds']) + 1
        naive = ((read(d / COH).get('trace_report') or {}).get('naive_comparison') or {}).get('verdict')
        status = read(d / COH).get('previous_findings_status') or []
        entry = {'round': n, 'blocking': len(blocking), 'naive': naive,
                 'prior_round': {'resolved': sum(1 for s in status if isinstance(s, dict) and s.get('status') == 'resolved'),
                                 'persists': sum(1 for s in status if isinstance(s, dict) and s.get('status') == 'persists')} if status else None,
                 'findings': [str(b.get('finding', ''))[:240] for b in blocking],
                 'operations': [{k: op.get(k) for k in ('target_id', 'op', 'field', 'outcome', 'changes_object', 'delta_summary')}
                                for op in patch.get('applied_revisions', []) if isinstance(op, dict)]}
        rd = d / f'phase2_coherence/round_{n}'; rd.mkdir(parents=True, exist_ok=False)
        stage_dir(d, 'formula_repair').rename(rd / 'formula_repair_stage'); (d / REPAIR).rename(rd / 'formula_repair.json')
        entry['object_declared'] = [op.get('target_id') for op in patch.get('applied_revisions', [])
                                    if isinstance(op, dict) and (op.get('changes_object') is True or op.get('outcome') == 'skipped_changes_object')]
        bids = {b.get('finding_id') for b in blocking}
        applied_b = [op for op in patch.get('applied_revisions', []) if isinstance(op, dict) and op.get('outcome') == 'applied' and op.get('target_id') in bids]
        applied_w = [op for op in patch.get('applied_revisions', []) if isinstance(op, dict) and op.get('outcome') == 'applied' and op.get('target_id') not in bids]
        if repair_stops(patch) and not applied_b:
            # The author says the only fixes replace the intervention object: that is a new idea, not a
            # repair. The executed findings stay in force and go to the audit. Wording suggestions the
            # author applied in the same patch are kept as the refined candidate without a re-trace
            # (nothing executed changed). A MIXED patch — some B# repaired, one declared object-level —
            # is applied and re-traced; the declared finding rides along.
            entry['stop'] = 'object'
            if applied_w:
                after = apply_patch(before, applied_w)
                if len(claim_texts(after)) < len(claim_texts(before)):
                    raise ValueError('Repair weakened the candidate: claims were removed')
                atomic_json(d / REFINED, after); entry['wording_applied'] = len(applied_w)
                deterministic_receipt(d, 'wording_materialize', [d / canonical, d / BLOCKING, rd / 'formula_repair.json'], [REFINED])
            ledger['rounds'].append(entry); atomic_json(d / ROUNDS, ledger)
            atomic_json(d / '.formula_repair_stop', entry)
            return
        after = apply_patch(before, patch['applied_revisions'])
        if len(claim_texts(after)) < len(claim_texts(before)):
            raise ValueError('Repair weakened the candidate: claims were removed')
        for k in ('falsification_prediction', 'compute_budget'):
            if after.get(k) != before.get(k): raise ValueError('Repair touched a kill-switch field: ' + k)
        if not blocking:
            # Wording-only round: the author applied or kept the gate's suggestions; nothing was executed
            # against, so the trace stands and is not re-run. The result is the canonical refined candidate.
            entry['wording_only'] = True
            atomic_json(d / REFINED, after)
            ledger['rounds'].append(entry); atomic_json(d / ROUNDS, ledger)
            deterministic_receipt(d, 'wording_materialize', [d / canonical, d / BLOCKING, rd / 'formula_repair.json'], [REFINED])
            return
        # Archive this round's trace and canonical; the next coherence trace runs on the repaired candidate.
        for rel in (COH, REFINED, BLOCKING, 'phase2_coherence/merged_revision.json', REPAIRED_CAND):
            if (d / rel).exists(): (d / rel).rename(rd / Path(rel).name)
        for st in ('coherence', 'coherence_materialize', 'wording_materialize', 'collision'):
            if stage_dir(d, st).exists(): stage_dir(d, st).rename(rd / (st + '_stage'))
        atomic_json(d / REPAIRED_CAND, after)
        # The next trace verifies these by id (resolved | persists); it sees nothing else of this round.
        atomic_json(d / 'phase2_coherence/previous_findings.json', {'contract_version': VERSION, 'round': n, 'findings': [
            {k: b.get(k) for k in ('finding_id', 'finding', 'verbatim_step_quote', 'derivation', 'source')} for b in blocking]})
        ledger['rounds'].append(entry); atomic_json(d / ROUNDS, ledger)
        return
    elif operation == 'repair_retry':
        require(d, 'formula_repair'); marker = d / '.repair_retry_used'
        if marker.exists():
            raise ValueError('repair_retry already used; the patch still breaks its contract — terminal')
        findings = json.loads(findings_json or '[]')
        if not findings:
            raise ValueError('repair_retry needs the failing contract findings')
        history = d / '.quality/repair_retry_history' / str(uuid.uuid4()); history.mkdir(parents=True)
        stage_dir(d, 'formula_repair').rename(history / 'formula_repair')
        if (d / REPAIR).exists(): (d / REPAIR).rename(history / Path(REPAIR).name)
        atomic_json(d / 'phase2_coherence/repair_findings.json',
                    {'contract_version': VERSION, 'findings': findings,
                     'rule': 'The repair patch violated a deterministic contract check (see findings). Re-issue the '
                             'same repair with the violation fixed.'})
        marker.touch()
        return
    elif operation == 'revision':
        require(d, 'critique', 'revision')
        if read(d / REV).get('contract_version') != 2:
            raise ValueError('A revision patch requires contract_version=2')
        base = REVISION_BASE if (d / REVISION_BASE).exists() else canonical
        merge_phase3_revisions(d / base, d / REV, d / 'phase3_revise', d / CRIT, incremental=(base == REVISION_BASE))
        stage = 'revision_materialize'; inputs = [base, REV, CRIT]
        outputs = [FINAL, 'phase3_revise/merged_revision.json']
    elif operation == 'skeleton':
        require(d, 'critique', 'coherence_materialize')
        if read(d / CRIT)['verdict'] == 'revise': require(d, 'post_revision', 'revision_materialize')
        selected = authoritative_candidate(d)
        hits = read(d / 'phase3_collision/collision_hits.json', [])
        skeleton = build_skeleton(read(d / selected), read(d / P1), read(d / SEL), read(d / CRIT),
            read(d / 'phase3_revise/merged_revision.json'), parse_lit_table(d / 'phase0/lit_table.md'),
            read(d / 'phase0/lit_results.json', []), hits)
        skeleton['contract_version'] = VERSION
        skeleton['sub_claims'] = '<TODO[sub_claims]: only source-supported subordinate claims; [] is valid>'
        # Final assessment is made AFTER implementation audit, never inferred from the old estimate.
        skeleton['feasibility_validation']['compute'] = {'verdict': 'unknown',
            'rationale': 'Awaiting current-version resource assessment'}
        for lang in ('en', 'zh'):
            for key, hint in [('plain_falsification', 'same experiment, metric, controls and failure conditions'),
                              ('plain_core_claim', 'main contribution explained without changing its strength'),
                              ('plain_resource_summary', 'current cost, user ceiling, uncertainty and feasibility'),
                              ('plain_open_questions', 'implementation choices and unresolved proof obligations; explicit none if none')]:
                field = key + '_' + lang
                skeleton[field] = '<TODO[' + field + ']: ' + hint + '>'
        atomic_json(d / SKEL, skeleton)
        pre = read(d / canonical) if selected == FINAL else None
        post_review = read(d / POST, {}) if selected == FINAL else None
        atomic_json(d / 'phase4/work/mechanism_record.json',
                    build_mechanism_record(read(d / selected), read(d / COH).get('trace_report', {}), pre, post_review,
                                           read(d / COH).get('unrepaired', [])))
        stage = 'skeleton'; inputs = [selected, P1, SEL, CRIT, COH, 'phase0/lit_table.md',
                                     'phase0/lit_results.json', 'phase3_collision/collision_hits.json']
        outputs = [SKEL, 'phase4/work/mechanism_record.json']
    elif operation == 'technical':
        require(d, 'skeleton', 'technical_fill')
        fill = read(d / 'phase4/work/fill_map.json')
        if any(k.startswith('plain_') or k == 'title_zh' for k in fill):
            raise ValueError('Technical fill cannot author plain-language fields')
        technical = assemble_expansion(read(d / SKEL), fill)
        plain_free = {k: v for k, v in technical.items() if not k.startswith('plain_') and k != 'title_zh'}
        if '<TODO[' in json.dumps(plain_free):
            raise ValueError('Technical TODOs remain')
        atomic_json(d / TECH, technical)
        stage = 'technical_assemble'; inputs = [SKEL, 'phase4/work/fill_map.json']; outputs = [TECH]
    elif operation == 'technical_repair':
        require(d, 'implementability', 'technical_repair')
        candidate = read(d / authoritative_candidate(d)); repairs = read(d / 'phase4/work/technical_repairs.json')
        ops = repairs.get('applied_revisions', [])
        if not ops:
            raise ValueError('Source omission requires an actual correction or needs_work')
        for op in ops:
            if op.get('op') != 'replace' or op.get('field', '').split('.')[0].split('[')[0] not in (
                'method_flow', 'key_equations', 'core_claim', 'sub_claims', 'motivation'):
                raise ValueError('Technical correction is restricted to source-grounded technical fields')
            if op.get('kind') == 'specification':
                # An operation the candidate left undefined is written down as a preregistered choice;
                # no source quote exists by definition, so the rationale and the review carry it.
                if not str(op.get('rationale', '')).strip():
                    raise ValueError('A specification repair needs a rationale (why this choice, fixed before any arm is run)')
                continue
            source = candidate.get(op.get('source_field', ''))
            quote = op.get('source_quote')
            if not isinstance(source, str) or not quote or quote not in source:
                raise ValueError(f"Repair op on {op.get('field')} ({op.get('kind') or 'transcribe'}) needs an exact canonical "
                                 f"source quote (source_field + source_quote found verbatim in the candidate)")
        # Every step the audit stopped is in this repair's remit: it gets an operation or an `unresolved`
        # entry, never silence. Observed: a repair closed S2 and said nothing about S4's source omission,
        # and the technical review (one reasoning-tier call) failed the whole batch for that alone.
        trace = read(d / IMPL).get('trace_report', {}) or {}
        stopped = [str(x.get('step') or x.get('step_id')) for x in trace.get('formalized_procedure', []) or []
                   if isinstance(x, dict) and x.get('status') == 'stopped']
        step_ids = [x.get('step_id') for x in (read(d / TECH).get('method_flow') or {}).get('steps', []) or []]
        covered = {str(u.get('step_id')) for u in repairs.get('unresolved', []) or [] if isinstance(u, dict)}
        for op in ops:
            m = re.match(r'method_flow\.steps\[(\d+)\]', op.get('field', ''))
            if m and int(m.group(1)) < len(step_ids):
                covered.add(str(step_ids[int(m.group(1))]))
        missing = [x for x in stopped if x not in covered]
        if missing:
            raise ValueError('The audit stopped ' + ', '.join(missing) + ': each stopped step needs an operation on it or an '
                             'unresolved entry naming it (the review fails a silent omission)')
        atomic_json(d / REPAIRED, apply_patch(read(d / TECH), ops))
        stage = 'technical_repair_materialize'
        inputs = [TECH, 'phase4/work/technical_repairs.json', authoritative_candidate(d), IMPL]; outputs = [REPAIRED]
        cr = repairs.get('cost_revision')
        if isinstance(cr, dict):
            # The repair specified the choice the audit's estimate hinged on and re-figured the cost. The
            # audit's file stays untouched; the revised one is bound to the same candidate and the technical
            # review checks its arithmetic before anything downstream reads it.
            if not all(str(cr.get(k, '')).strip() for k in ('current_estimate', 'basis', 'change_reason')):
                raise ValueError('cost_revision needs current_estimate, basis and change_reason')
            base = read(d / COST)
            atomic_json(d / COST_REVISED, {**base, 'current_estimate': cr['current_estimate'], 'basis': cr['basis'],
                                           'change_reason': cr['change_reason'], 'status': 'revised_by_repair',
                                           'audit_estimate': base.get('current_estimate')})
            outputs.append(COST_REVISED)
    elif operation == 'final':
        require(d, 'implementability', 'plain_derive')
        repaired = receipt_valid(d, 'technical_repair_materialize')
        if repaired: require(d, 'technical_review')
        ti = REPAIRED if repaired else TECH
        cp = cost_path(d)
        out = finalize_expansion(read(d / ti), read(d / 'phase4/work/derive_map.json'), read(d / cp), read(d / IMPL),
                                 read(d / 'phase4/work/technical_repairs.json', {}) if repaired else None)
        rec = read(d / FAILED_CARD, {})
        if rec:
            out['proposal_status'] = 'FAILED VALIDATION (' + str(rec.get('stage')) + ') — ' + str(rec.get('reason', ''))[:600]
            out['validation_failures'] = [str(x.get('message', ''))[:1200] for x in rec.get('findings', [])]
        atomic_json(d / EXP, out)
        stage = 'final_assemble'; inputs = [ti, 'phase4/work/derive_map.json', cp, IMPL] + ([TECH_REVIEW] if repaired else []) + ([FAILED_CARD] if rec else [])
        outputs = [EXP]
    elif operation == 'generation_retry':
        require(d, 'generation'); marker = d / '.generation_retry_used'
        if marker.exists():
            raise ValueError('generation_retry already used; the gate still fails — terminal')
        findings = json.loads(findings_json or '[]')
        if not findings:
            raise ValueError('generation_retry needs the failing gate findings')
        history = d / '.quality/generation_retry_history' / str(uuid.uuid4()); history.mkdir(parents=True)
        stage_dir(d, 'generation').rename(history / 'generation')
        for rel in (SEL, GEN):
            if (d / rel).exists(): (d / rel).rename(history / Path(rel).name)
        atomic_json(d / 'phase2_generate/selection_findings.json',
                    {'contract_version': VERSION, 'findings': findings,
                     'rule': 'On a method anchor a controlled_diagnostic_design sibling/companion, or any '
                             'evaluation_only component, is refused. The measurement belongs in '
                             'falsification_prediction; a consumed runtime signal is a '
                             'self_supervised_signal_engineering or assumption_audit_and_pivot leg.'})
        marker.touch()
        return
    elif operation == 'critique_retry':
        require(d, 'critique'); marker = d / '.critique_retry_used'
        if marker.exists():
            raise ValueError('critique_retry already used; the audit contract still fails — terminal')
        findings = json.loads(findings_json or '[]')
        if not findings:
            raise ValueError('critique_retry needs the failing validator findings')
        history = d / '.quality/critique_retry_history' / str(uuid.uuid4()); history.mkdir(parents=True)
        stage_dir(d, 'critique').rename(history / 'critique')
        if (d / CRIT).exists(): (d / CRIT).rename(history / Path(CRIT).name)
        atomic_json(d / 'phase3_critique/critique_findings.json',
                    {'contract_version': VERSION, 'findings': findings,
                     'rule': 'The audit report violated a deterministic contract check (see findings). Re-issue the '
                             'same audit with the violation fixed; do not change the scientific judgement to fit.'})
        marker.touch()
        return
    elif operation in ('fidelity_retry', 'revision_retry'):
        # Bounded recovery: archive the failed review round, hand its findings to the stage that
        # produced the reviewed text, and mark the budget spent. Second failure is terminal.
        carried = []
        if operation == 'fidelity_retry':
            require(d, 'fidelity'); marker = d / '.fidelity_retry_used'
            report = read(d / FIDELITY); dst = d / 'phase4/work/fidelity_findings.json'
            stages = ['plain_derive', 'final_assemble', 'fidelity', 'publication']
        else:
            require(d, 'post_revision'); marker = d / '.revision_retry_used'
            report = read(d / POST); dst = d / 'phase3_revise/post_revision_findings.json'
            # A falsification rewrite the technical review authorized stays authorized through the
            # re-revision: its targets are carried as TR# (scope falsification) with `authorized_by`.
            prior = read(dst, {}) if dst.exists() else {}
            carried = ([dict(t, target_id='TR' + str(i + 1)) for i, t in enumerate(prior.get('targets', []) or [])
                        if isinstance(t, dict) and t.get('scope') == 'falsification']
                       if prior.get('source') == 'technical_review' or prior.get('authorized_by') == 'technical_review' else [])
            stages = ['revision', 'revision_materialize', 'post_revision', 'post_collision', 'post_novelty']
        if report.get('verdict') != 'needs_work' and not [f for f in prune_findings(report, read(d / FINAL)) if f['validator'] == 'prune_component']:
            raise ValueError(operation + ' requires a needs_work review verdict or an executed removal test')
        if marker.exists():
            raise ValueError(operation + ' already used; the review still fails — terminal')
        history = d / '.quality' / (operation + '_history') / str(uuid.uuid4()); history.mkdir(parents=True)
        if operation == 'revision_retry':
            # The next patch applies to the text the reviewer just read, not to the canonical candidate:
            # nothing already accepted has to be re-issued, so nothing already accepted can be dropped.
            atomic_json(d / REVISION_BASE, read(d / FINAL))
        for st in stages:
            sd = stage_dir(d, st)
            if sd.exists(): sd.rename(history / st)
        atomic_json(dst, {'contract_version': VERSION, 'source': str(report.get('verdict')),
                          'reason': report.get('reason', ''), 'checks': report.get('checks', {}),
                          'prune': [f['message'] for f in prune_findings(report, read(d / FINAL)) if f['validator'] == 'prune_component'],
                          'targets': (retry_targets(report, change_scope(read(d / canonical), read(d / FINAL))['required_checks']
                                                    + ['target_resolution'], read(d / FINAL)) + carried) if operation == 'revision_retry' else [],
                          **({'authorized_by': 'technical_review'} if carried else {})})
        marker.touch()
        return
    elif operation == 'object_abandon':
        object_abandon(d); return
    elif operation == 'consistency_patch':
        consistency_patch(d); return
    elif operation == 'phase4_revision':
        # The technical review named a bounded falsification change; hand it to the audited revision
        # transaction and clear every Phase 4 stage so it re-runs on the revised candidate. The technical
        # text written for this candidate is kept for the next fill to preserve what the revision leaves alone.
        require(d, 'technical_review'); review = read(d / TECH_REVIEW)
        targets = [t for t in review.get('revision_targets', []) or [] if isinstance(t, dict)]
        if review.get('route') != 'falsification_revision' or not targets:
            raise ValueError('phase4_revision requires route=falsification_revision with revision_targets')
        marker = d / '.phase4_revision_used'
        if marker.exists():
            raise ValueError('phase4_revision already used; the review still fails — terminal')
        for i, t in enumerate(targets):
            t.setdefault('target_id', f'F{i + 1}'); t['scope'] = 'falsification'; t.setdefault('field', 'falsification_prediction')
        history = d / '.quality/phase4_revision_history' / str(uuid.uuid4()); history.mkdir(parents=True)
        for stage_name in ('revision', 'revision_materialize', 'post_revision', 'post_collision', 'post_novelty', 'skeleton',
                           'technical_fill', 'technical_assemble', 'implementability', 'technical_repair',
                           'technical_repair_materialize', 'technical_review', 'plain_derive', 'final_assemble', 'publication'):
            src = d / '.quality' / stage_name
            if src.exists(): src.rename(history / stage_name)
        keep = d / 'phase4/work/before_falsification_revision'; keep.mkdir(parents=True, exist_ok=True)
        for p in list((d / 'phase4/work').iterdir()):
            if p.is_file(): p.rename(keep / p.name)
        atomic_json(d / P4_FINDINGS, {'contract_version': VERSION, 'source': 'technical_review',
                                      'reason': str(review.get('reason', ''))[:2000], 'targets': targets})
        atomic_json(d / REVISION_BASE, read(d / (FINAL if (d / FINAL).exists() else authoritative_candidate(d))))
        # A fresh revision transaction gets its own single re-revision: the one spent on an earlier
        # transaction of this candidate does not count against it.
        (d / '.revision_retry_used').unlink(missing_ok=True)
        marker.touch()
        return
    elif operation == 'failed_card':
        # The run's validation ended in failure; record where and why, name the last candidate, and let
        # the card stages run on it. The card says FAILED VALIDATION and carries this record.
        nw = read(d / 'needs_work.json', {}); findings = list(nw.get('findings', []))
        stage_name = 'validation'
        if (d / 'phase_3_failed.md').exists():
            stage_name = 'phase_3'; crit = read(d / CRIT, {})
            findings.append(finding('phase_3_failed', 'audit verdict ' + str(crit.get('verdict')) + ' (' + str(crit.get('verdict_layer')) +
                                    '): ' + str(crit.get('verdict_rationale', ''))[:1500]))
        elif findings:
            stage_name = str(findings[0].get('message', '')).split(':', 1)[0][:40]
        if not findings:
            raise ValueError('failed_card requires a recorded validation failure (needs_work.json or phase_3_failed.md)')
        cand = FINAL if receipt_valid(d, 'revision_materialize') else authoritative_candidate(d)
        # The card's one-line reason is the deciding reviewer's own `reason`, not its evidence blob.
        reason = ''
        for st, rel in (('technical_review', TECH_REVIEW), ('fidelity', FIDELITY), ('post_revision', POST)):
            rep = read(d / rel, {}) if receipt_valid(d, st) else {}
            if rep and rep.get('verdict') not in (None, 'pass'):
                failed_checks = [k for k, v in (rep.get('checks') or {}).items() if isinstance(v, dict) and v.get('status') == 'fail']
                stage_name = st + (' (' + ', '.join(failed_checks) + ')' if failed_checks else '')
                reason = str(rep.get('reason', ''))[:600]; break
        if not reason:
            reason = '; '.join(str(x.get('message', ''))[:400] for x in findings)[:2000]
        atomic_json(d / FAILED_CARD, {'contract_version': VERSION, 'stage': stage_name, 'candidate': cand,
                                      'reason': reason, 'findings': findings})
        return
    else:
        raise ValueError('Unknown materialization operation')
    # Inputs and outputs only — never the scripts' own hashes (see module note on receipts).
    deterministic_receipt(d, stage, [d / p for p in inputs], outputs)


def collision(d, root, candidate, post=False):
    require(d, 'coherence_materialize')
    source = path_in_run(d, candidate)
    payload = read(source)
    stage = 'post_collision' if post else 'collision'
    out = d / ('phase3_revise/collision' if post else 'phase3_collision')
    inputs = [source]
    if post:
        if post == 'confirmed':
            require(d, 'post_revision')
            payload.update({k: read(d / POST)['confirmed_terms'].get(k, []) for k in ('signature_terms', 'alias_terms')})
        source = d / 'phase3_revise/collision_query.json'; atomic_json(source, payload)
        inputs = [source]            # retrieval consumes terms only; the query file is the whole input
    else:
        # Retrieval consumes terms only. Mechanism changes are handled by the novelty audit,
        # not disguised as a need to rerun identical network requests.
        source = d / 'phase3_collision/query_candidate.json'; atomic_json(source, payload)
    before = input_hashes(inputs)
    rc = subprocess.run([sys.executable, str(root / 'scripts/run.py'), 'phase3_collision',
                         '--idea-json', str(source), '--out', str(out)]).returncode
    if rc or not (out / 'collision_hits.json').exists():
        raise ValueError('Collision retrieval did not complete; no receipt issued')
    if not read(out / 'collision_hits.json', []):
        # Every connector returned nothing. A candidate whose signature AND alias terms match no paper on
        # arXiv/OpenAlex/S2/OpenReview is not plausible; an empty pool is a connector failure (observed: S2 403,
        # OpenReview auth, arXiv silent) and a novelty audit on it would be an audit of nothing. No receipt:
        # the host retries when connectivity is back.
        raise ValueError('Collision retrieval returned zero hits from every connector; treated as connector failure, no receipt issued')
    if before != input_hashes(inputs):
        raise ValueError('Candidate changed during collision retrieval')
    deterministic_receipt(d, stage, inputs,
                          [str((out / 'collision_hits.json').relative_to(d))])


def retry_targets(post, required=None, candidate=None):
    """Post-revision findings as revision targets the merger accepts: P# for each executed removal
    test that left every claim standing (delete the component), F# for each failed EXECUTED check.
    Every one must be covered by the re-revision (applied, or skipped with evidence) — the same
    rule as the audit's R# targets. Judgement-only fails are not targets: they do not block."""
    out = []
    for i, t in enumerate(t for t in (post.get('removal_tests') or [])
                          if isinstance(t, dict) and t.get('claims_unchanged') is True and t.get('executed') is True
                          and str(t.get('field', '')).split('[')[0].split('.')[0] in ('core_mechanism', 'core_mechanism_steps', 'gap_closure')
                          and not (candidate and named_in_falsification(t.get('component'), candidate.get('falsification_prediction', '')))):
        out.append({'target_id': f'P{i + 1}', 'scope': 'tactical', 'field': t.get('field'), 'kind': 'prune',
                    'instruction': f"Delete '{t.get('component')}' from every field that mentions it; keep the rest byte-identical. "
                                   + str(t.get('evidence', ''))[:300]})
    n = 0
    for name, c in (post.get('checks') or {}).items():
        if required is not None and name not in required:
            continue                                  # e.g. cost: reported, never a revision target
        if isinstance(c, dict) and c.get('status') == 'fail' and c.get('executed') is True:
            n += 1
            out.append({'target_id': f'F{n}', 'scope': 'tactical', 'check': name, 'kind': 'failed_check',
                        'instruction': str(c.get('evidence', ''))[:600]})
    return out


def versioned_lessons(d, current):
    from scripts.next_step import _lessons
    lessons = {x for x in _lessons(current) if x[0] != 'finding'}
    lookup = {b['finding_id']: b for b in read(d / 'phase2_coherence/blocking_findings.json', {}).get('findings', [])}
    for item in current.get('blocking_findings_disposition', []):
        if item.get('status') == 'upheld':
            evidence = lookup.get(resolve_finding_ref(item.get('finding_ref'), lookup), {})
            if not evidence:
                raise ValueError('Retry finding id does not resolve to archived evidence')
            lessons.add(('finding', digest({k: v for k, v in evidence.items() if k != 'finding_id'})))
    post = read(d / POST, {})
    if post.get('verdict') == 'redesign':
        lessons.add(('revision', digest(post.get('checks', {}))))
    return lessons


def _attempt_summary(a, label):
    """Everything a reader needs about one candidate cycle, from files that already exist."""
    cand = (read(a / REFINED, None) if (a / REFINED).exists() else None) or (read(a / REPAIRED_CAND, None) if (a / REPAIRED_CAND).exists() else None) or read(a / GEN, {})
    sel = read(a / SEL, {}); crit = read(a / CRIT, {})
    findings = {b.get('finding_id'): b for b in read(a / 'phase2_coherence/blocking_findings.json', {}).get('findings', [])}
    upheld = {resolve_finding_ref(x.get('finding_ref'), findings) or str(x.get('finding_ref'))
              for x in crit.get('blocking_findings_disposition', []) if x.get('status') == 'upheld'}
    return {'label': label, 'title': cand.get('title'), 'hook': cand.get('hook'),
            'patterns': [g.get('chosen_pattern_id') for g in sel.get('selected_gaps', [])],
            'object': cand.get('intervention_object'),
            'verdict': crit.get('verdict'), 'layer': crit.get('verdict_layer'),
            'rationale': crit.get('verdict_rationale', ''),
            'upheld': [findings.get(i, {}).get('finding', i) for i in sorted(upheld)],
            'candidate': cand}


def write_failure_report(d, attempts):
    """phase_3_failed.md: every cycle's title, verdict and the executed evidence that ended it, then the
    BEST cycle in full. Best = no hard floor, then fewest upheld executed findings, then latest — the
    least-refuted candidate, not an audited-passed one: the card pipeline is not run on it, and the
    report says so. Its candidate JSON is copied out so a user who wants to keep working has the text."""
    rows = [_attempt_summary(a, a.name) for a in attempts] + [_attempt_summary(d, 'final cycle')]
    best = sorted(enumerate(rows), key=lambda ir: (ir[1]['layer'] == 'hard_floor', len(ir[1]['upheld']), -ir[0]))[0][1]
    out = ['# Proposal not advanced', '',
           'Candidate-cycle cap or information gain exhausted. No card was produced: every cycle below was '
           'refused by the audit on executed or quoted evidence, and the pipeline does not print a mechanism '
           'its own trace refuted. The best cycle is reproduced in full at the end for a reader who wants to '
           'take it further by hand; it is an unaudited draft, not a proposal.', '']
    for r in rows:
        out += [f"## {r['label']}: {r['title']}", '',
                f"patterns: {', '.join(p for p in r['patterns'] if p)} · verdict: {r['verdict']} ({r['layer']})", '',
                f"hook: {r['hook']}", '', f"why refused: {r['rationale']}", '']
        for f in r['upheld']: out += [f"- executed finding upheld: {str(f)[:400]}", '']
    c = best['candidate']
    out += [f"## Best cycle in full (unaudited draft): {best['title']}", '',
            f"Chosen because: {'no hard floor; ' if best['layer'] != 'hard_floor' else ''}{len(best['upheld'])} upheld executed finding(s).", '',
            '### core_mechanism', '', str(c.get('core_mechanism', '')), '',
            '### core_mechanism_steps', '', str(c.get('core_mechanism_steps', '')), '',
            '### falsification_prediction', '', str(c.get('falsification_prediction', '')), '',
            '### compute_budget', '', str(c.get('compute_budget', '')), '']
    (d / 'phase_3_failed.md').write_text('\n'.join(out))
    atomic_json(d / 'phase_3_failed_best_candidate.json', {'contract_version': VERSION, 'status': 'unaudited_draft',
                'cycle': best['label'], 'verdict': best['verdict'], 'verdict_layer': best['layer'],
                'upheld_findings': best['upheld'], 'candidate': c})


def retry(d):
    from scripts.next_step import _attempt_dirs, _lessons
    require(d, 'critique')
    current = read(d / CRIT)
    post = read(d / POST, {}) if receipt_valid(d, 'post_revision') else {}
    if current.get('verdict') != 'abandon' and post.get('verdict') != 'redesign':
        raise ValueError('Retry requires an audited abandon/redesign')
    attempts = _attempt_dirs(d)
    lessons = versioned_lessons(d, current)
    seen = set().union(*(versioned_lessons(a, read(a / CRIT, {}))
                        for a in attempts)) if attempts else set()
    repeated_threat = any(k == 'threat' for k, _ in lessons) and any(k == 'threat' for k, _ in seen)
    bottleneck = repeated_threat and not (d / '.bottleneck_retry_used').exists()
    if (d / '.bottleneck_retry_used').exists() or (attempts and not bottleneck and
            (not lessons - seen or len(attempts) + 1 >= 3)):
        # Deterministic diagnostic; no extra model call needed to format a failure.
        write_failure_report(d, attempts)
        return
    index = max([int(p.name[8:]) for p in attempts] + [0]) + 1
    archive = d / f'attempt_{index}'; archive.mkdir(exist_ok=False)
    names = ['phase2_select', 'phase2_generate', 'phase2_coherence', 'phase3_collision',
             'phase3_critique', 'phase3_revise', 'phase4', '.quality', 'needs_work.json',
             '.formula_repair_stop', '.repair_retry_used']
    if bottleneck: names.insert(0, 'phase1')
    for name in names:
        target = d / name
        if target.exists(): target.rename(archive / name)
    (d / ('.bottleneck_retry_used' if bottleneck else '.retry_used')).touch()
    contract = read(d / 'run_contract.json'); contract['attempt'] = index + 1
    atomic_json(d / 'run_contract.json', contract)


def snapshot_cross_run(d):
    """Freeze at init so changing neighboring runs cannot invalidate this run later."""
    target = d / 'context/cross_run.json'
    if target.exists(): return
    entries = []
    if os.environ.get('IDEASPARK_CROSS_RUN_DEDUP', '').lower() not in ('off', '0', 'false'):
        siblings = [s for s in d.parent.iterdir() if s.is_dir() and s != d and (s / 'phase0').exists()]
        for sib in sorted(siblings, key=lambda p: -p.stat().st_mtime):
            for rel in (FINAL, REFINED, GEN):
                try: c = read(sib / rel, {})
                except (ValueError, OSError): continue
                if c.get('title'):
                    entries.append({'source': str(sib / rel), 'source_sha256': fingerprint(sib / rel),
                                    'title': c['title'], 'signature_terms': c.get('signature_terms', [])[:4]})
                    break
            if len(entries) == 5: break
    atomic_json(target, {'purpose': 'CROSS-RUN DEDUP: soft context, never literature or veto', 'entries': entries})


def publish(d, root, no_pdf=False):
    from scripts.validators import run_all_validators
    from scripts.render_pdf import render_one
    a = late_flow(d, root, failed=(d / FAILED_CARD).exists())
    if a['state'] not in ('READY_TO_RENDER', 'DONE'):
        raise ValueError('Publication gate not satisfied: ' + a['step'])
    candidate = authoritative_candidate(d)
    p3 = d / ('phase3_revise/merged_revision.json' if candidate == FINAL else CRIT)
    findings = run_all_validators(phase1_path=d / P1, phase2_select_path=d / SEL,
        phase2_path=d / (REFINED if receipt_valid(d, 'wording_materialize') else (REPAIRED_CAND if (d / REPAIRED_CAND).exists() else GEN)),
        phase3_path=p3, phase4_path=d / EXP, phase4_impl_path=d / IMPL)
    # Dedicated validators handle the audit-only implementability report.
    fails = [f for f in findings if f['severity'] == 'fail']
    if fails and not (d / FAILED_CARD).exists():
        atomic_json(d / 'needs_work.json', {'input_fingerprint': failure_fingerprint(d), 'findings': fails})
        raise ValueError('Validation failed; draft preserved, no successful render')
    out = d / 'phase4'
    # Preserve earlier rendered artifacts; a failed PDF compile must not expose a stale PDF.
    old = [p for p in out.glob('idea.*') if p.is_file()]
    if old:
        saved = d / '.quality/publication/history' / str(uuid.uuid4()); saved.mkdir(parents=True)
        for p in old: shutil.copy2(p, saved / p.name)
        for p in old:
            if p.suffix == '.pdf': p.rename(saved / ('stale-' + p.name))
    findings += latex_findings(read(d / EXP))
    render_one(read(d / EXP), out, compile_pdfs=not no_pdf)
    outputs = [str(p.relative_to(d)) for p in out.glob('idea.*') if p.is_file()]
    errors = {p.name[:-len('.pdf.error.txt')]: p.read_text().strip() for p in (out / 'work').glob('idea.*.pdf.error.txt')}
    pdf_status = ('skipped_by_request' if no_pdf else
                  'compiled_with_errors' if errors else
                  'compiled_not_visually_verified' if len(list(out.glob('idea.std.*.pdf'))) == 2 else 'unavailable_or_failed')
    atomic_json(out / 'work/render_status.json', {'contract_version': VERSION,
        'pdf': pdf_status, 'pdf_errors': errors,
        'scientific_validation': 'not_experimentally_validated', 'validation_findings': findings})
    outputs.append('phase4/work/render_status.json')
    deterministic_receipt(d, 'publication', [d / EXP] + ([d / FIDELITY] if (d / FIDELITY).exists() else []), outputs)


def object_abandon(d):
    """The abandon written on the record when every surviving blocking finding is author-declared
    object-level: facts (the executed findings, the rounds, what resolved) and salvage, no directives."""
    require(d, 'coherence_materialize')
    bf = read(d / BLOCKING); rounds = read(d / ROUNDS, {}).get('rounds', [])
    declared = {}
    for r in rounds:
        for fid in r.get('object_declared') or []: declared.setdefault(fid, r.get('round'))
    findings = bf.get('findings', [])
    if not object_level_survivors(rounds, read(d / COH), findings):
        raise ValueError('object_abandon requires every surviving blocking finding to be author-declared object-level')
    resolved = [s for r in rounds for s in ((r.get('prior_round') or {}).get('resolved_ids') or [])]
    naive = ((read(d / COH).get('trace_report') or {}).get('naive_comparison') or {})
    facts = '; '.join(f"{f['finding_id']} ({f.get('source', '?')}): {str(f.get('finding', ''))[:300]} — derivation: {str(f.get('derivation', ''))[:200]}" for f in findings)
    rationale = ('Hard floor rule 2 on the record: every surviving executed blocking finding was declared object-level by the '
                 f'author (repair_rounds.json, rounds {sorted(set(declared.values()))}) and persisted in the re-trace. Executed: {facts}. '
                 f'Rounds: {len(rounds)}; formula repairs applied: {sum(1 for r in rounds for o in r.get("operations", []) if o.get("outcome") == "applied")}. '
                 'Salvage (what executed and held): ' + (', '.join(map(str, resolved)) + ' resolved by repair; ' if resolved else '') +
                 f"naive comparison {naive.get('verdict', 'n_a')}: {str(naive.get('reasoning', ''))[:300]}")
    crit = {'contract_version': VERSION, 'source': 'object_abandon', 'verdict': 'abandon', 'verdict_layer': 'hard_floor',
            'verdict_rationale': rationale,
            'paper_pointed_threat': {'threat_paper_id': 'not_checked', 'threat_source': None,
                                     'subsumption_argument': 'not checked: abandoned on executed evidence before the audit; the next cycle audits its own candidate'},
            'falsification_structure_check': {'verdict': 'not_checked', 'reasoning': 'not checked: abandoned on executed evidence'},
            'blocking_findings_disposition': [{'finding_ref': f['finding_id'], 'status': 'upheld',
                                               'basis': f"author declared changes_object (rounds {sorted(set(declared.values()))}); the re-trace reports it persisting: {str(f.get('executed_evidence', ''))[:300]}"}
                                              for f in findings],
            'revision_targets': []}
    atomic_json(d / CRIT, crit)
    deterministic_receipt(d, 'critique', [d / authoritative_candidate(d), d / COH, d / BLOCKING] + ([d / ROUNDS] if (d / ROUNDS).exists() else []), [CRIT])


CONSISTENCY_FIELDS = ('core_mechanism', 'core_mechanism_reasoning', 'core_mechanism_steps', 'what_step_was_missed')
CONSISTENCY_LIST_FIELDS = {'gap_closure': 'how_closed', 'differentiation_from_lit': 'delta'}
CONSISTENCY_MAX = 8


def consistency_patch(d):
    """Apply the post-revision reviewer's bounded consistency fixes: exact-substring replacements in
    mechanism prose (never a kill-switch field, never a term list). An entry whose `old` is not found
    exactly once is skipped and recorded; the receipt re-seals final_candidate.json."""
    require(d, 'post_revision'); post = read(d / POST)
    entries = [e for e in (post.get('consistency_patch') or []) if isinstance(e, dict)][:CONSISTENCY_MAX]
    if post.get('verdict') != 'pass' or not entries:
        raise ValueError('consistency_patch requires a pass verdict with a non-empty consistency_patch')
    if receipt_valid(d, 'consistency_patch'):
        raise ValueError('consistency_patch already applied')
    pre = d / 'phase3_revise/final_candidate.pre_consistency.json'
    cand = read(d / FINAL); atomic_json(pre, cand)
    applied, skipped = [], []
    for e in entries:
        field, old, new = str(e.get('field', '')), str(e.get('old', '')), str(e.get('new', ''))
        m = re.fullmatch(r'(\w+)\[(\d+)\]\.(\w+)', field)
        try:
            if m and m.group(1) in CONSISTENCY_LIST_FIELDS and m.group(3) == CONSISTENCY_LIST_FIELDS[m.group(1)]:
                holder, key = cand[m.group(1)][int(m.group(2))], m.group(3)
            elif field in CONSISTENCY_FIELDS:
                holder, key = cand, field
            else:
                skipped.append(dict(e, why='field not patchable here')); continue
            text = holder.get(key)
            if not isinstance(text, str) or not old or text.count(old) != 1 or not new.strip():
                skipped.append(dict(e, why='old must occur exactly once in the field and new must be non-empty')); continue
            if len(new) > 2 * len(old) + 200:
                skipped.append(dict(e, why='a consistency fix is a clause, not a rewrite')); continue
            holder[key] = text.replace(old, new, 1); applied.append(e)
        except (KeyError, IndexError, TypeError):
            skipped.append(dict(e, why='field not found'))
    atomic_json(d / FINAL, cand)
    atomic_json(d / 'phase3_revise/consistency_patch.json', {'contract_version': VERSION, 'applied': applied, 'skipped': skipped})
    deterministic_receipt(d, 'consistency_patch', [d / POST, pre], [FINAL, 'phase3_revise/consistency_patch.json'])


def register_commands(sub, root):
    names = ('quality_init', 'quality_prepare', 'quality_record', 'quality_materialize',
             'quality_collision', 'quality_retry', 'quality_needs_work', 'quality_publish')
    for name in names:
        p = sub.add_parser(name, help='Quality flow: ' + name.replace('quality_', '') + ' (explicit execution)')
        p.add_argument('--dir', required=True)
        if name == 'quality_init': p.add_argument('--query')
        if name == 'quality_prepare': p.add_argument('--spec-json', required=True)
        if name == 'quality_record': p.add_argument('--stage', required=True)
        if name == 'quality_materialize':
            p.add_argument('--operation', required=True); p.add_argument('--findings-json', default=None)
        if name == 'quality_collision':
            p.add_argument('--candidate', required=True); p.add_argument('--post', default='no')
        if name == 'quality_needs_work': p.add_argument('--findings-json', required=True)
        if name == 'quality_publish': p.add_argument('--no-pdf', action='store_true')
        def execute(args, name=name):
            d = Path(args.dir).resolve()
            try:
                if name == 'quality_init':
                    init_run(d); snapshot_cross_run(d)
                    if args.query and not (d / 'context/user_query.txt').exists():
                        (d / 'context/user_query.txt').write_text(args.query)
                elif name == 'quality_prepare': prepare(d, json.loads(args.spec_json))
                elif name == 'quality_record': record(d, args.stage)
                elif name == 'quality_materialize': materialize(d, root, args.operation, args.findings_json)
                elif name == 'quality_collision': collision(d, root, args.candidate, args.post if args.post in ('yes', 'confirmed') else False)
                elif name == 'quality_retry': retry(d)
                elif name == 'quality_publish': publish(d, root, args.no_pdf)
                else: atomic_json(d / 'needs_work.json', {'input_fingerprint': failure_fingerprint(d),
                                                       'findings': json.loads(args.findings_json)})
            except RecordRejected as exc:
                print('REJECTED', name + ':', exc, file=sys.stderr); return 1
            except (ValueError, KeyError, OSError, TypeError) as exc:
                # An execution failure is terminal until real inputs/results change;
                # next must not keep emitting the same invalid merge/record forever.
                if name != 'quality_init':
                    try:
                        if has_contract(d):
                            atomic_json(d / 'needs_work.json', {
                                'input_fingerprint': failure_fingerprint(d),
                                'findings': [finding('execution_contract', name + ': ' + str(exc))]})
                    except (ValueError, OSError, TypeError):
                        pass  # report original failure; never claim a commit
                print('ERROR:', exc, file=sys.stderr); return 1
            print('OK', name); return 0
        p.set_defaults(func=execute)
