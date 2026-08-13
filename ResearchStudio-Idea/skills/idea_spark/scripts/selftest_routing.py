#!/usr/bin/env python3
"""Routing/merger branch self-test for IdeaSpark.

Fabricates minimal sandbox run dirs and asserts on the `next` navigator's emits
plus the revision merger's kill-switch behavior — covering exactly the branches
real runs rarely (or never) exercise, so a skill edit cannot silently break them:

  T0  audit emit lists blocking_findings.json as an input
  T1  guard: blocking findings present, zero dispositions -> bounce re-audit
  T2  guard: refuted disposition, no recheck -> emit bounded refutation re-check
  T3  guard: recheck judged a refutation INVALID -> bounce re-audit
  T4  guard: all refutations judged valid -> advance proceeds to Phase 4 skeleton
  T5  guard: advance coexists with an upheld finding -> bounce (inconsistent)
  T6  2nd abandon, BOTH attempts subsumption-killed -> bottleneck-level retry
  T7  2nd abandon, bottleneck retry already used -> terminal, all attempts cited
  T8  2nd abandon, lessons repeat what generation already had -> terminal
  T17 2nd abandon carrying NEW upheld obstacle findings -> directed 3rd attempt
  T18 abandon at candidate-cycle cap (3 cycles used) -> terminal
  T19 obstacle death then NEW subsumption threat -> retry (new negative anchor)
  T20 audit bounce archives the rejected report (bounce is counted, not silent)
  T21 two rejected audits -> bounce budget spent, routes to abandon (no livelock)
  T22 two rejected coherence outputs -> gate declared unable to complete (no livelock)
  T9  post-archive state -> Phase 1 emit carries BOTTLENECK-RETRY MODE anchors
  T10 sibling run exists -> Phase 2 emit carries the CROSS-RUN DEDUP soft anchors
  T11 merger: authorized rewrite_falsification is applied (strengthen-only route)
  T12 merger: unauthorized generic op on a kill-switch field is REFUSED
  T13 no 2.3 + no collision -> 2.3 emit carries the PARALLEL collision launch
  T14 collision landed first -> 2.3 gate still required (no skip, no re-launch)
  T15 sidecar terms mismatch the canonical candidate -> collision re-issued
  T16 sidecar terms match -> proceeds to the audit emit (positive control)

Stdlib only. Run: python3 scripts/selftest_routing.py [--keep]
Exit 0 = all green; 1 = at least one failure (details on stderr).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
RUN_PY = SKILL / 'scripts' / 'run.py'

FINDING = ('equivalent_to_naive: the coalition machinery never changes the retention '
           'decision versus greedy leave-one-out on the same oracle')
FINDING2 = 'step-7 interaction gate is structurally inert for interference'
FINDING3 = 'monotonicity claim is numerically false as written'


def wj(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1))


def candidate() -> dict:
    return {
        'title': 'Selftest Candidate: Held-Out Widget Gating',
        'hook': 'A fabricated candidate for routing fixtures.',
        'core_mechanism': 'Gate widget commits on a held-out oracle.',
        'core_mechanism_reasoning': 'PREMISES: P1. NAIVE-BASELINE AUDIT: branch (i).',
        'core_mechanism_steps': 'S1 do a thing. S2 gate it.',
        'gap_closure': [{
            'gap': 'No prior work gates widgets on a held-out oracle.',
            'main_pattern': 'reframe_as_solvable_object',
            'sub_pattern': 'C00 (Reframe as a Solvable Object)',
            'how_closed': 'Reframed as a solvable gating object.',
        }],
        'composition_note': 'Single-pattern defense: the reframe move is complete on its '
                            'own; a second pattern would add surface, not closure.',
        'falsification_prediction': 'ORIGINAL FALSIFICATION: minimal experiment E, metric M '
                                    'up, load-bearing variable V, negative control returns '
                                    'M to baseline.',
        'compute_budget': '10 GPU-days on 80GB-class GPUs.',
        'signature_terms': ['held-out widget gating', 'commit gate oracle'],
        'alias_terms': ['validation-set accept rule'],
    }


def base_run(d: Path, with_critique=None, blocking: bool = True) -> None:
    """Fabricate a run state complete through collision, optionally + critique."""
    papers = [
        {'paper_id': 'semanticscholar:aaa', 'title': 'Widget Gating Prior Art',
         'year_month': '2025-01', 'venue': 'arXiv.org', 'source': 'semanticscholar',
         'retrieved_via': 'semanticscholar', 'abstract': 'widgets'},
        {'paper_id': 'arxiv:0000.00001', 'title': 'Held-Out Selection for Widgets',
         'year_month': '2025-02', 'venue': 'arXiv.org', 'source': 'arxiv',
         'retrieved_via': 'arxiv', 'abstract': 'held-out'},
    ]
    wj(d / 'phase0' / 'lit_results.json', papers)
    cols = ('paper_id | year_month | venue | title | ideation pattern tags | '
            'bottleneck this paper targets | open issue / unresolved gap | '
            'resolves_problem | retrieved_via')
    rows = ['| ' + ' | '.join([p['paper_id'], p['year_month'], p['venue'], p['title'],
                               'reframe_as_solvable_object', 'widget gating', 'unsolved',
                               '—', p['retrieved_via']]) + ' |' for p in papers]
    (d / 'phase0' / 'lit_table.md').write_text(
        '| ' + cols + ' |\n|' + '|'.join(['---'] * 9) + '|\n' + '\n'.join(rows) + '\n')
    wj(d / 'phase0' / 'fulltext_cache.json', {})
    (d / 'phase0' / '.lit_grounding_mode').write_text('real')
    wj(d / 'phase1' / 'phase1_output.json',
       {'state': 'proceed', 'intake': {'contribution_type': 'method'},
        'closest_adjacent': [{'paper_id': 'semanticscholar:aaa',
                              'summary_and_residue': 'close but no gate'}],
        'bottleneck_statement': 'Widgets lack certified gating.'})
    wj(d / 'phase2_select' / 'phase2_select_output.json',
       {'selected_gaps': [{'gap': 'No prior work gates widgets on a held-out oracle.',
                           'main_pattern': 'reframe_as_solvable_object'}],
        'coherence_thread_type': 'n_a',
        'composition_note': 'Single-pattern defense: complete on its own.',
        'pattern_saturation': [], 'deferred_gaps': []})
    wj(d / 'phase2_generate' / 'phase2_generate_output.json', candidate())
    unrepaired = []
    if blocking:
        unrepaired = [
            {'finding': FINDING, 'severity': 'blocking', 'why_not_repaired': 'redesign',
             'verbatim_step_quote': 'S2 gate it.',
             'executed_evidence': 'script: v(mech)=0.35 vs v(naive)=0.60',
             'reading_dependence': 'reading_robust'},
            {'finding': FINDING2, 'severity': 'blocking', 'why_not_repaired': 'redesign',
             'verbatim_step_quote': 'S2 gate it.', 'executed_evidence': 'gate never fires',
             'reading_dependence': 'reading_robust'},
            {'finding': FINDING3, 'severity': 'blocking', 'why_not_repaired': 'redesign',
             'verbatim_step_quote': 'S2 gate it.', 'executed_evidence': '0.60 -> 0.35',
             'reading_dependence': 'reading_robust'},
        ]
        wj(d / 'phase2_coherence' / 'blocking_findings.json', unrepaired)
    wj(d / 'phase2_coherence' / 'phase2_coherence_output.json',
       {'verdict': 'pass', 'unrepaired': unrepaired, 'applied_revisions': [],
        'trace_report': {}})
    wj(d / 'phase3_collision' / 'collision_hits.json',
       [{'title': 'Held-Out Selection for Widgets', 'collision_channel': 'signature',
         'paper_id': 'arxiv:0000.00001', 'relevance_score': 5}])
    if with_critique is not None:
        wj(d / 'phase3_critique' / 'phase3_critique_output.json', with_critique)


def crit(verdict: str, dispositions=None, unaddressable: bool = False) -> dict:
    c = {'verdict': verdict, 'verdict_layer': 'soft_judgment',
         'verdict_rationale': 'fixture', 'revision_targets': [],
         'paper_pointed_threat': {
             'threat_paper_id': 'arxiv:0000.00001' if unaddressable else 'no_threat_found',
             'addressable_via': 'unaddressable' if unaddressable else None}}
    if dispositions is not None:
        c['blocking_findings_disposition'] = dispositions
    return c


def run_next(d: Path) -> str:
    r = subprocess.run([sys.executable, str(RUN_PY), 'next', '--dir', str(d)],
                       capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr


RESULTS = []


def check(name: str, ok: bool, detail: str = '') -> None:
    RESULTS.append((name, ok, detail))
    print(('  ok ' if ok else 'FAIL ') + name + ('' if ok else f' — {detail}'),
          file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', action='store_true', help='keep the sandbox dir')
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix='ideaspark_selftest_'))
    try:
        # T0 — audit emit lists the blocking-findings file
        d = tmp / 'T0' / 'run'; base_run(d)
        out = run_next(d)
        check('T0 audit emit lists blocking_findings.json',
              'audit-and-verdict' in out and 'blocking_findings.json' in out
              and 'blocking_findings_disposition' in out, out[:300])

        # T1 — zero dispositions -> bounce
        d = tmp / 'T1' / 'run'; base_run(d, with_critique=crit('advance'))
        out = run_next(d)
        check('T1 missing dispositions bounce',
              'dispositioned only 0' in out and 'Re-run Phase 3.2' in out, out[:300])

        # T2 — refuted disposition, no recheck -> recheck emit
        disp = [{'finding_ref': FINDING[:40], 'status': 'refuted', 'basis': 'weak'},
                {'finding_ref': FINDING2[:40], 'status': 'upheld', 'basis': 'stands'},
                {'finding_ref': FINDING3[:40], 'status': 'upheld', 'basis': 'stands'}]
        d = tmp / 'T2' / 'run'; base_run(d, with_critique=crit('revise', disp))
        out = run_next(d)
        check('T2 refutation re-check required',
              'Refutation re-check' in out and 'refutation_recheck.txt' in out, out[:300])

        # T3 — recheck says refutation invalid -> bounce
        d = tmp / 'T3' / 'run'; base_run(d, with_critique=crit('revise', disp))
        wj(d / 'phase3_critique' / 'refutation_recheck.json',
           {'rechecks': [{'finding_ref': FINDING[:40], 'claimed_flaw': 'none_stated',
                          'refutation_valid': False, 'reason': 'basis re-reasons only'}]})
        out = run_next(d)
        check('T3 invalid refutation bounce',
              'INVALID' in out and 'Re-run Phase 3.2' in out, out[:300])

        # T4 — all refutations valid, no upheld -> advance proceeds to Phase 4
        disp_all_ref = [{'finding_ref': f[:40], 'status': 'refuted', 'basis':
                         'arithmetic error shown'} for f in (FINDING, FINDING2, FINDING3)]
        d = tmp / 'T4' / 'run'; base_run(d, with_critique=crit('advance', disp_all_ref))
        wj(d / 'phase3_critique' / 'refutation_recheck.json',
           {'rechecks': [{'finding_ref': f[:40], 'claimed_flaw': 'arithmetic_error',
                          'refutation_valid': True, 'reason': 'recomputed'}
                         for f in (FINDING, FINDING2, FINDING3)]})
        out = run_next(d)
        check('T4 valid refutations let advance through',
              'Phase 4 skeleton' in out, out[:300])

        # T5 — advance + upheld -> inconsistent bounce
        disp_mix = [{'finding_ref': FINDING[:40], 'status': 'upheld', 'basis': 'stands'},
                    {'finding_ref': FINDING2[:40], 'status': 'refuted', 'basis': 'err'},
                    {'finding_ref': FINDING3[:40], 'status': 'refuted', 'basis': 'err'}]
        d = tmp / 'T5' / 'run'; base_run(d, with_critique=crit('advance', disp_mix))
        wj(d / 'phase3_critique' / 'refutation_recheck.json',
           {'rechecks': [{'finding_ref': f[:40], 'claimed_flaw': 'arithmetic_error',
                          'refutation_valid': True, 'reason': 'ok'}
                         for f in (FINDING2, FINDING3)]})
        out = run_next(d)
        check('T5 advance-over-upheld bounce',
              'UPHELD' in out and 'Re-run Phase 3.2' in out, out[:300])

        # T6 — second abandon, both subsumption-killed -> bottleneck retry
        d = tmp / 'T6' / 'run'
        base_run(d, with_critique=crit('abandon', unaddressable=True), blocking=False)
        (d / '.retry_used').touch()
        wj(d / 'attempt_1' / 'phase3_critique' / 'phase3_critique_output.json',
           crit('abandon', unaddressable=True))
        out = run_next(d)
        check('T6 bottleneck-level retry offered',
              'bottleneck-level retry available' in out
              and '.bottleneck_retry_used' in out, out[:300])

        # T7 — bottleneck retry already used -> terminal citing all attempts
        d = tmp / 'T7' / 'run'
        base_run(d, with_critique=crit('abandon', unaddressable=True), blocking=False)
        (d / '.retry_used').touch(); (d / '.bottleneck_retry_used').touch()
        wj(d / 'attempt_1' / 'phase3_critique' / 'phase3_critique_output.json',
           crit('abandon', unaddressable=True))
        wj(d / 'attempt_2' / 'phase3_critique' / 'phase3_critique_output.json',
           crit('abandon', unaddressable=True))
        out = run_next(d)
        check('T7 terminal after bottleneck retry',
              'bottleneck retry already used' in out and 'phase_3_failed' in out
              and 'attempt_2' in out, out[:300])

        # T8 — mechanism-level double death -> terminal, no bottleneck retry
        d = tmp / 'T8' / 'run'
        base_run(d, with_critique=crit('abandon'), blocking=False)
        (d / '.retry_used').touch()
        wj(d / 'attempt_1' / 'phase3_critique' / 'phase3_critique_output.json',
           crit('abandon'))
        out = run_next(d)
        check('T8 no-new-information terminal',
              'no NEW binding information' in out and 'phase_3_failed' in out, out[:300])

        # T9 — post-archive: Phase 1 emit carries bottleneck-retry anchors
        d = tmp / 'T9' / 'run'
        base_run(d, blocking=False)  # then strip to the archived state
        for sub in ('phase1', 'phase2_select', 'phase2_generate',
                    'phase2_coherence', 'phase3_collision'):
            shutil.rmtree(d / sub, ignore_errors=True)
        (d / '.retry_used').touch(); (d / '.bottleneck_retry_used').touch()
        wj(d / 'attempt_1' / 'phase3_critique' / 'phase3_critique_output.json',
           crit('abandon', unaddressable=True))
        wj(d / 'attempt_2' / 'phase3_critique' / 'phase3_critique_output.json',
           crit('abandon', unaddressable=True))
        wj(d / 'attempt_2' / 'phase1' / 'phase1_output.json',
           {'state': 'proceed', 'bottleneck_statement': 'retired bottleneck'})
        out = run_next(d)
        check('T9 Phase 1 bottleneck-retry anchors',
              'Phase 1' in out and 'BOTTLENECK-RETRY MODE' in out
              and 'attempt_2' in out, out[:300])

        # T10 — sibling run -> CROSS-RUN DEDUP line in the Phase 2 emit
        parent = tmp / 'T10'
        sib = parent / 'sib'; base_run(sib, blocking=False)  # sibling with a candidate
        d = parent / 'run'
        base_run(d, blocking=False)
        for sub in ('phase2_select', 'phase2_generate', 'phase2_coherence',
                    'phase3_collision'):
            shutil.rmtree(d / sub, ignore_errors=True)
        out = run_next(d)
        check('T10 cross-run dedup anchors',
              'CROSS-RUN DEDUP' in out and 'Selftest Candidate' in out, out[:400])

        # T13 — no 2.3 + no collision -> 2.3 emit WITH the parallel launch
        d = tmp / 'T13' / 'run'; base_run(d, blocking=False)
        shutil.rmtree(d / 'phase2_coherence', ignore_errors=True)
        shutil.rmtree(d / 'phase3_collision', ignore_errors=True)
        out = run_next(d)
        check('T13 parallel collision launch with 2.3',
              'coherence gate (dry-run trace)' in out
              and 'launch 3.1 collision in parallel' in out
              and 'phase3_collision --idea-json' in out
              and 'TWO independent actions' in out, out[:400])

        # T14 — collision landed first: the 2.3 gate is still required, no re-launch
        d = tmp / 'T14' / 'run'; base_run(d, blocking=False)
        shutil.rmtree(d / 'phase2_coherence', ignore_errors=True)
        out = run_next(d)
        check('T14 collision-first still gates on 2.3',
              'coherence gate (dry-run trace)' in out
              and 'launch 3.1 collision in parallel' not in out
              and 'TWO independent actions' not in out
              and 'phase3_collision --idea-json' not in out, out[:400])

        # T15 — sidecar terms mismatch the canonical candidate -> re-issue collision
        d = tmp / 'T15' / 'run'; base_run(d, blocking=False)
        wj(d / 'phase3_collision' / '.collision_terms.json',
           {'signature_terms': ['stale pre-repair term'], 'alias_terms': []})
        out = run_next(d)
        check('T15 stale collision terms re-issued',
              'Re-run Phase 3.1 collision' in out and 'repaired terms' in out, out[:400])

        # T16 — sidecar terms match -> proceeds to the audit emit (positive control)
        d = tmp / 'T16' / 'run'; base_run(d, blocking=False)
        c = candidate()
        wj(d / 'phase3_collision' / '.collision_terms.json',
           {'signature_terms': c['signature_terms'], 'alias_terms': c['alias_terms']})
        out = run_next(d)
        check('T16 matching sidecar reaches the audit',
              'audit-and-verdict' in out, out[:400])

        # T17 — 2nd abandon with NEW upheld obstacle findings -> directed 3rd attempt
        disp_up = [{'finding_ref': f[:40], 'status': 'upheld', 'basis': 'stands'}
                   for f in (FINDING, FINDING2, FINDING3)]
        d = tmp / 'T17' / 'run'
        base_run(d, with_critique=crit('abandon', disp_up))
        wj(d / 'attempt_1' / 'phase3_critique' / 'phase3_critique_output.json',
           crit('abandon'))  # first death carried no lessons -> these findings are NEW
        (d / '.retry_used').touch()
        out = run_next(d)
        check('T17 directed third attempt on new obstacle findings',
              'NEW binding directive' in out and 'attempt_2' in out
              and 'phase_3_failed' not in out, out[:400])

        # T18 — new lessons but candidate-cycle cap reached -> terminal
        d = tmp / 'T18' / 'run'
        base_run(d, with_critique=crit('abandon', disp_up))
        wj(d / 'attempt_1' / 'phase3_critique' / 'phase3_critique_output.json',
           crit('abandon'))
        wj(d / 'attempt_2' / 'phase3_critique' / 'phase3_critique_output.json',
           crit('abandon'))
        (d / '.retry_used').touch()
        out = run_next(d)
        check('T18 candidate-cycle cap terminal',
              'candidate-cycle cap' in out and 'phase_3_failed' in out, out[:400])

        # T19 — obstacle death first, NEW subsumption threat second -> retry
        # (info-gain dividend: the threat paper is a new negative anchor, and no
        # prior threat exists so the framing is NOT indicted)
        d = tmp / 'T19' / 'run'
        base_run(d, with_critique=crit('abandon', unaddressable=True), blocking=False)
        wj(d / 'attempt_1' / 'phase3_critique' / 'phase3_critique_output.json',
           crit('abandon', disp_up))
        (d / '.retry_used').touch()
        out = run_next(d)
        check('T19 new threat anchor retries (not framing-indicted)',
              'NEW binding directive' in out and 'bottleneck-level retry' not in out
              and 'phase_3_failed' not in out, out[:400])

        # T20/T21 — the advance-over-upheld bounce is bounded and archives
        disp_up = [{'finding_ref': f[:40], 'status': 'upheld', 'basis': 'stands'}
                   for f in (FINDING, FINDING2, FINDING3)]
        d = tmp / 'T20' / 'run'; base_run(d, with_critique=crit('advance', disp_up))
        out = run_next(d)
        check('T20 bounce archives the rejected report',
              'Re-run Phase 3.2' in out and 'rejected_1' in out, out[:400])

        d = tmp / 'T21' / 'run'; base_run(d, with_critique=crit('advance', disp_up))
        for k in (1, 2):
            (d / 'phase3_critique' / f'rejected_{k}').mkdir(parents=True, exist_ok=True)
        out = run_next(d)
        check('T21 spent bounce budget routes to abandon',
              'Archive attempt 1' in out and 'Re-run Phase 3.2' not in out, out[:400])

        # T22 — the 2.3 malformed redo is bounded
        d = tmp / 'T22' / 'run'; base_run(d, blocking=False)
        wj(d / 'phase2_coherence' / 'phase2_coherence_output.json', {'verdict': 'GARBAGE'})
        shutil.rmtree(d / 'phase3_collision', ignore_errors=True)
        shutil.rmtree(d / 'phase3_critique', ignore_errors=True)
        for k in (1, 2):
            (d / 'phase2_coherence' / f'rejected_{k}').mkdir(parents=True, exist_ok=True)
        out = run_next(d)
        check('T22 coherence redo budget spent -> gate declared unable',
              'could not complete' in out and 'Redo Phase 2.3' not in out, out[:400])

        # T11 — merger applies an AUTHORIZED rewrite_falsification
        d = tmp / 'T11'; d.mkdir(parents=True)
        cand_p = d / 'cand.json'; wj(cand_p, candidate())
        critique_p = d / 'critique.json'
        wj(critique_p, {'verdict': 'revise',
                        'revision_targets': [{'scope': 'falsification',
                                              'field': 'falsification_prediction',
                                              'issue': 'strengthen-only addition',
                                              'fix_direction': 'add baseline arm'}]})
        patch_p = d / 'patch.json'
        wj(patch_p, {'applied_revisions': [{
            'scope': 'falsification', 'op': 'rewrite_falsification',
            'field': 'falsification_prediction',
            'value': 'ORIGINAL FALSIFICATION: minimal experiment E, metric M up, '
                     'load-bearing variable V, negative control returns M to baseline; '
                     'ADDED comparison baseline arm B.',
            'outcome': 'applied', 'delta_summary': 'strengthen-only baseline add'}]})
        r = subprocess.run([sys.executable, str(RUN_PY), 'phase3_merge_revisions',
                            '--phase2', str(cand_p), '--revisions', str(patch_p),
                            '--critique', str(critique_p), '--out', str(d)],
                           capture_output=True, text=True, timeout=60)
        final = d / 'final_candidate.json'
        ok = (r.returncode == 0 and final.exists()
              and 'ADDED comparison baseline arm B' in
              json.loads(final.read_text()).get('falsification_prediction', ''))
        check('T11 authorized falsification rewrite applied', ok,
              (r.stdout + r.stderr)[:300])

        # T12 — merger REFUSES an unauthorized generic op on a kill-switch field
        d = tmp / 'T12'; d.mkdir(parents=True)
        cand_p = d / 'cand.json'; wj(cand_p, candidate())
        patch_p = d / 'patch.json'
        wj(patch_p, {'applied_revisions': [{
            'scope': 'tactical', 'op': 'replace', 'field': 'falsification_prediction',
            'value': 'weakened experiment', 'outcome': 'applied',
            'delta_summary': 'illegal edit'}]})
        r = subprocess.run([sys.executable, str(RUN_PY), 'phase3_merge_revisions',
                            '--phase2', str(cand_p), '--revisions', str(patch_p),
                            '--out', str(d)],
                           capture_output=True, text=True, timeout=60)
        check('T12 unauthorized kill-switch edit refused',
              r.returncode != 0 and not (d / 'final_candidate.json').exists(),
              (r.stdout + r.stderr)[:300])

        # ---- Phase 0.5 coverage-check routing (offline: fabricate intermediates) ----
        def phase0_stage(dd):
            """A run at 'lit_table written, no fulltext' — pre-coverage-check."""
            wj(dd / 'phase0' / 'lit_results.json',
               [{'paper_id': 'semanticscholar:aaa', 'title': 'A', 'source': 'semanticscholar',
                 'retrieved_via': 'semanticscholar'}])
            (dd / 'phase0' / 'lit_table.md').write_text(
                '| paper_id | year_month | venue | title | ideation pattern tags | '
                'bottleneck this paper targets | open issue / unresolved gap | '
                'resolves_problem | retrieved_via |\n|---|---|---|---|---|---|---|---|---|\n'
                '| semanticscholar:aaa | 2025-01 | arXiv.org | A | reframe_as_solvable_object | '
                'b | g | — | semanticscholar |\n')
            (dd / 'phase0' / '.lit_grounding_mode').write_text('real')

        # P0 — a run dir that does not exist is a FRESH RUN, not an error.
        # `next` is read-only; hosts that call it before mkdir (the natural reading
        # of an inspect command) used to get rc=2 and abort the whole skill.
        d = tmp / 'P0_missing' / 'never_created'
        r = subprocess.run([sys.executable, str(RUN_PY), 'next', '--dir', str(d)],
                           capture_output=True, text=True, timeout=120)
        check('P0 missing run dir -> fresh-run emit, rc=0',
              r.returncode == 0 and 'Fresh run' in r.stdout and 'phase0' in r.stdout
              and not d.exists(), f'rc={r.returncode} ' + (r.stdout + r.stderr)[:300])

        # ---- Phase 0.4 relevance-partition routing (before tagging) ----
        def phase0_preTag(dd):
            """A run right after retrieval: lit_results present, no lit_table yet."""
            wj(dd / 'phase0' / 'lit_results.json',
               [{'paper_id': 'semanticscholar:aaa', 'title': 'A', 'source': 'semanticscholar',
                 'retrieved_via': 'semanticscholar', 'abstract': 'x'}])
            (dd / 'phase0' / '.lit_grounding_mode').write_text('real')

        # P1 — lit_results present, no partition file -> partition nomination emit
        d = tmp / 'P1' / 'run'; phase0_preTag(d)
        out = run_next(d)
        check('P1 relevance partition emitted',
              'relevance partition' in out and 'relevance_partition.json' in out
              and 'off_topic' in out and 'do NOT downgrade' in out, out[:400])

        # P2 — partition file present, not applied -> apply_partition emit
        d = tmp / 'P2' / 'run'; phase0_preTag(d)
        wj(d / 'phase0' / 'relevance_partition.json',
           [{'paper_id': 'semanticscholar:aaa', 'relevance': 'core', 'reason': 'y'}])
        out = run_next(d)
        check('P2 apply_partition emitted',
              'apply_partition' in out and '.partition_applied' in out, out[:400])

        # P3 — partition applied -> falls through to tagging (lit_table) emit
        d = tmp / 'P3' / 'run'; phase0_preTag(d)
        (d / 'phase0' / '.partition_applied').touch()
        out = run_next(d)
        check('P3 applied partition -> tagging emit',
              'lit_table.md' in out and 'relevance partition' not in out, out[:400])

        # P4 — env off -> partition skipped, straight to tagging
        d = tmp / 'P4' / 'run'; phase0_preTag(d)
        env_off_p = dict(os.environ, IDEASPARK_RELEVANCE_PARTITION='off')
        out = (subprocess.run([sys.executable, str(RUN_PY), 'next', '--dir', str(d)],
                              capture_output=True, text=True, timeout=120, env=env_off_p).stdout)
        check('P4 env=off skips partition -> tagging',
              'lit_table.md' in out and 'relevance partition' not in out, out[:400])

        # Q1-Q2 — the user's question is an ARTIFACT, not a string the host retypes.
        # Every phase that reasons about intent (0.4 partition, 0.5 recall, 1, 2.1) must be
        # pointed at phase0/user_query.txt. Before this, Phase 2.1 could not see the user's
        # words at all: it received only phase1_output.json's 10-slot intake summary, so a
        # stated direction ("I want fusion, not search") was unreachable by the generator.
        d = tmp / 'Q1' / 'run'; phase0_preTag(d)
        (d / 'phase0' / 'user_query.txt').write_text('fuse the modalities, do not search\n')
        out = run_next(d)
        check('Q1 partition emit cites user_query.txt, not a retyped string',
              'user_query.txt' in out and 'relevance partition' in out, out[:400])

        d = tmp / 'Q2' / 'run'; phase0_stage(d)
        (d / 'phase0' / 'user_query.txt').write_text('fuse the modalities, do not search\n')
        for m in ('.partition_applied', '.coverage_check_done'):
            (d / 'phase0' / m).touch()
        wj(d / 'phase0' / 'fulltext_cache.json', {})
        wj(d / 'phase1' / 'phase1_output.json', {'state': 'proceed', 'intake': {}})
        out = run_next(d)
        check('Q2 Phase 2.1 emit cites user_query.txt (was blind to the user)',
              'user_query.txt' in out and '2.1' in out, out[:400])

        # Q3 — a name-dropped paper must be reachable. The URL/ID regex only sees links,
        # so "based on AdaWorld" produced no user_ref, no U-tier fetch, and no anchor — the
        # emit has to ASK for the names, not bury add_user_ref in a notes line.
        d = tmp / 'Q3' / 'never_created'
        out = subprocess.run([sys.executable, str(RUN_PY), 'next', '--dir', str(d)],
                             capture_output=True, text=True, timeout=120).stdout
        check('Q3 fresh-run emit requests named_papers + offers --named-papers',
              'named_papers' in out and '--named-papers' in out, out[:400])

        # C1 — lit_table done, no nominations -> coverage-check emit
        d = tmp / 'C1' / 'run'; phase0_stage(d)
        out = run_next(d)
        check('C1 coverage check emitted',
              'coverage check' in out and 'host_refs_nominations.json' in out
              and 'do NOT downgrade' in out
              and 'last ~12 months' in out, out[:400])

        # C2 — nominations present, add_host_refs not run -> resolve emit
        d = tmp / 'C2' / 'run'; phase0_stage(d)
        wj(d / 'phase0' / 'host_refs_nominations.json',
           [{'title': 'Some Missing Paper', 'source': 'parametric', 'why': 'x'}])
        out = run_next(d)
        check('C2 resolve+merge host refs emitted',
              'add_host_refs' in out and 'host_refs_unresolved.md' in out, out[:400])

        # C3 — host refs admitted with a NEW id -> tag-into-lit_table emit
        d = tmp / 'C3' / 'run'; phase0_stage(d)
        wj(d / 'phase0' / 'host_refs_nominations.json', [{'title': 'X', 'source': 'parametric'}])
        wj(d / 'phase0' / 'host_refs.json',
           [{'paper_id': 'arxiv:9999.99999', 'title': 'Newly Admitted', 'retrieved_via': 'host_recall'}])
        out = run_next(d)
        check('C3 tag admitted host rows',
              'tag the admitted host refs' in out and 'lit_table_merge' in out
              and 'coverage_check_done' in out, out[:400])

        # C4 — host refs resolved, nothing new admitted -> finalize (touch marker)
        d = tmp / 'C4' / 'run'; phase0_stage(d)
        wj(d / 'phase0' / 'host_refs_nominations.json', [])
        wj(d / 'phase0' / 'host_refs.json', [])
        out = run_next(d)
        check('C4 finalize coverage (no admissions)',
              'finalize coverage' in out and 'coverage_check_done' in out
              and 'full-text fetch' not in out, out[:400])

        # C5 — marker present -> coverage skipped, straight to fulltext
        d = tmp / 'C5' / 'run'; phase0_stage(d)
        (d / 'phase0' / '.coverage_check_done').touch()
        out = run_next(d)
        check('C5 marker skips coverage -> fulltext',
              'full-text fetch' in out and 'coverage check' not in out, out[:400])

        # C6 — env off -> coverage skipped entirely, straight to fulltext
        d = tmp / 'C6' / 'run'; phase0_stage(d)
        env_off = dict(os.environ, IDEASPARK_COVERAGE_CHECK='off')
        out = (subprocess.run([sys.executable, str(RUN_PY), 'next', '--dir', str(d)],
                              capture_output=True, text=True, timeout=120, env=env_off).stdout)
        check('C6 env=off skips coverage -> fulltext',
              'full-text fetch' in out and 'coverage check' not in out, out[:400])
    finally:
        if args.keep:
            print(f'sandbox kept at {tmp}', file=sys.stderr)
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    n_fail = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f'\n[{"GREEN" if n_fail == 0 else "RED"}] selftest_routing: '
          f'{len(RESULTS) - n_fail}/{len(RESULTS)} passed', file=sys.stderr)
    return 0 if n_fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
