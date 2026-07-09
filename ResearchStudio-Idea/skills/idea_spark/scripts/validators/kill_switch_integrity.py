"""kill_switch_integrity validator.

Phase 2 candidate emits two kill-switch fields:
  - falsification_prediction (single paragraph naming the experiment, the metrics,
    and their predicted directions)
  - compute_budget (flat string)

Both MUST equal byte-for-byte in the Phase 4 expansion. The prompts say "orchestrator
validator rejects drift" — this is that validator.

Architecture: Phase 3.2 audit produces a judgment report and leaves the candidate untouched.
The chain is Phase 2 → Phase 4 (Phase 3 passthrough) in the advance path, or
Phase 2 → Phase 3.3 final_candidate → Phase 4 in the revise path.

This validator accepts phase3_path optionally: if Phase 3 contains a final_candidate (3.3 ran),
it validates the 3-link chain; otherwise it treats Phase 3 as passthrough and checks Phase 2 → Phase 4.

Audited falsification rewrite (the ONE sanctioned kill-switch change): when the Phase 3.2
audit's falsification_structure_check found the paragraph structurally deficient, Phase 3.3
may carry a `rewrite_falsification` op that the merger applies under audit authorization and
records as `falsification_rewritten: true` in the patch doc. On that path this validator
checks `falsification_prediction` byte-identity on the Phase 3.3 final_candidate → Phase 4
link (the rewritten paragraph is the new commitment) instead of Phase 2 → Phase 4, and it
FAILS if the rewrite marker is present without an actual applied rewrite_falsification entry
(or vice versa). `compute_budget` keeps the full Phase 2 → 3.3 → 4 byte-identity always.

Why it matters: a misbehaving Phase 3.3 / Phase 4 model could substitute the kill-switch
experiment with an easier one ("we'll use a simpler dataset / smaller compute"), making the
candidate look more feasible than the original Phase 2 candidate committed to. This validator
catches that silently.
"""
from __future__ import annotations
import json
from pathlib import Path


KILL_SWITCH_FIELDS = [
    ('falsification_prediction',),
    ('compute_budget',),
]


_MISSING = object()  # sentinel distinct from None (legitimate JSON null)


def _get_raw_nested(d: dict, path: tuple):
    """Walk dotted path. Returns _MISSING if any segment is absent (dict has no key
    OR intermediate is not a dict). Returns the raw value (any type) otherwise — caller
    is responsible for type validation. Distinct from `_get_nested` which silently
    swallowed wrong-type values as None and produced misleading 'missing' errors when
    the field was actually present-but-wrong-type (e.g. nested dict from old schema)."""
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return _MISSING
        if k not in cur:
            return _MISSING
        cur = cur[k]
    return cur


def _check_kill_switch_value(d: dict, path: tuple, phase_label: str, field_name: str):
    """Resolve a kill-switch field and classify the result. Returns (value_or_None, finding_or_None).
    - Missing field → ('warn' if phase_label='Phase 2' else 'fail') finding, value=None
    - Wrong type (not string) → 'fail' finding (clear schema-violation message), value=None
    - Empty string → 'fail' finding (kill-switch cannot be empty), value=None
    - Valid non-empty string → no finding, value=the string"""
    raw = _get_raw_nested(d, path)
    if raw is _MISSING:
        # legitimately missing — Phase 2 missing is warn (candidate may be unfinished),
        # Phase 4 missing is fail (anti-substitution chain broken)
        sev = 'warn' if phase_label == 'Phase 2' else 'fail'
        return None, {
            'severity': sev, 'validator': 'kill_switch_integrity',
            'message': f'{phase_label} missing field {field_name}',
        }
    if not isinstance(raw, str):
        return None, {
            'severity': 'fail', 'validator': 'kill_switch_integrity',
            'message': f'{phase_label} {field_name} has wrong type {type(raw).__name__} '
                       f'(expected string — `falsification_prediction` is a single paragraph '
                       f'and `compute_budget` is a flat string)',
        }
    if not raw.strip():
        return None, {
            'severity': 'fail', 'validator': 'kill_switch_integrity',
            'message': f'{phase_label} {field_name} is empty string (kill-switch cannot be empty)',
        }
    return raw, None


def validate_kill_switch_integrity(phase2_path, phase3_path, phase4_path) -> list[dict]:
    """Read the phase outputs and check kill-switch fields are byte-identical.

    New flow (audit-only Phase 3.2): Phase 2.2 candidate → Phase 4 expansion. Phase 3.2 is a
    passthrough (no final_candidate emitted). V1 checks Phase 2 → Phase 4 directly.

    When Phase 3.3 ran (verdict=revise path), Phase 3 contains `final_candidate`; V1 also
    checks Phase 2 → Phase 3 final_candidate → Phase 4. Otherwise V1 silently skips that link.

    Phase 2 candidate location: 3 schemas supported
      1. Simplified K=1: top-level candidate (has falsification_prediction directly)
      2. Old K=N: candidates[] + winner field
      3. Old K=N: k3_candidates[] without explicit winner -> first
    """
    findings = []
    p2 = json.loads(Path(phase2_path).read_text())
    p3 = json.loads(Path(phase3_path).read_text()) if phase3_path else {}
    p4 = json.loads(Path(phase4_path).read_text())

    if p2.get('falsification_prediction') is not None:
        winner_candidate = p2
    else:
        winner_id = p2.get('winner') or (p2.get('selection_block') or {}).get('winner')
        candidates = p2.get('candidates') or p2.get('k3_candidates') or p2.get('k2_candidates') or []
        if winner_id and isinstance(candidates, list):
            winner_candidate = next((c for c in candidates if c.get('candidate_id') == winner_id), None)
        elif isinstance(candidates, list) and candidates:
            winner_candidate = candidates[0]
        else:
            winner_candidate = None
        if winner_candidate is None:
            findings.append({'severity': 'fail', 'validator': 'kill_switch_integrity', 'message': f'Phase 2 winner={winner_id} not found in candidates list'})
            return findings

    # Phase 3 may or may not contribute a final_candidate to the byte-identical chain:
    #   - 3.2 verdict=advance + no 3.3 run: phase3 is critique output, has no final_candidate. V1 skips.
    #   - 3.2 verdict=revise + 3.3 run: phase3 is revise output, has final_candidate. V1 validates 3-link chain.
    # The `final_candidate.falsification_prediction is not None` check distinguishes the two cases.
    #
    # NEW patch-only 3.3 contract: the LLM emits only `applied_revisions[]` and a Python merger
    # (`scripts/run.py phase3_merge_revisions`) writes a sibling `final_candidate.json` file AND
    # back-injects the merged candidate into the patch file's `final_candidate` slot. So legacy
    # consumers (this validator) keep finding it under `phase3_revise_output.json['final_candidate']`.
    # The sibling-file fallback below handles the hand-authored-patch case where back-injection
    # did not run (no `final_candidate` key inline) but the merger DID produce the sibling file.
    final_candidate = p3.get('final_candidate') if isinstance(p3, dict) else None
    if final_candidate is None and phase3_path:
        sibling = Path(phase3_path).parent / 'final_candidate.json'
        if sibling.exists():
            try:
                final_candidate = json.loads(sibling.read_text())
            except Exception:
                final_candidate = None
    has_phase3_chain = (final_candidate is not None and isinstance(final_candidate, dict)
                       and isinstance(final_candidate.get('falsification_prediction'), str))

    # Audited falsification rewrite detection: the merger stamps `falsification_rewritten`
    # into the patch doc AND the patch must carry a matching applied rewrite_falsification
    # entry. Marker/entry disagreement is a hard fail (someone hand-edited the patch).
    rewrite_marker = bool(isinstance(p3, dict) and p3.get('falsification_rewritten'))
    rewrite_entries = [
        r for r in (p3.get('applied_revisions') or [])
        if isinstance(r, dict) and r.get('op') == 'rewrite_falsification'
        and not str(r.get('outcome', '')).startswith('skipped_')
    ] if isinstance(p3, dict) else []
    if rewrite_marker != bool(rewrite_entries):
        findings.append({
            'severity': 'fail', 'validator': 'kill_switch_integrity',
            'message': ('falsification_rewritten marker and applied rewrite_falsification patch '
                        'entries disagree (marker={}, entries={}) — the patch file was modified '
                        'outside the merger; re-run phase3_merge_revisions').format(
                            rewrite_marker, len(rewrite_entries)),
        })
    falsification_rewritten = rewrite_marker and bool(rewrite_entries)
    if falsification_rewritten and not has_phase3_chain:
        findings.append({
            'severity': 'fail', 'validator': 'kill_switch_integrity',
            'message': 'falsification_rewritten is set but Phase 3 carries no well-typed '
                       'final_candidate — merger output is incomplete',
        })

    for field_path in KILL_SWITCH_FIELDS:
        field_name = '.'.join(field_path)
        # The audited rewrite re-bases falsification_prediction's commitment at Phase 3.3:
        # the byte-identity anchor becomes the final_candidate, not the Phase 2 candidate.
        rebased = falsification_rewritten and field_name == 'falsification_prediction' and has_phase3_chain

        v2, p2_finding = _check_kill_switch_value(winner_candidate, field_path, 'Phase 2 candidate', field_name)
        if p2_finding is not None:
            findings.append(p2_finding)
            continue
        v4, p4_finding = _check_kill_switch_value(p4, field_path, 'Phase 4 expansion', field_name)
        if p4_finding is not None:
            findings.append(p4_finding)
            continue

        if rebased:
            v3, p3_finding = _check_kill_switch_value(final_candidate, field_path, 'Phase 3 final_candidate', field_name)
            if p3_finding is not None:
                findings.append(p3_finding)
                continue
            if v3 == v2:
                findings.append({
                    'severity': 'fail', 'validator': 'kill_switch_integrity',
                    'message': f'{field_name}: falsification_rewritten is set but Phase 3 '
                               f'final_candidate is byte-identical to Phase 2 — no rewrite '
                               f'actually landed; re-run phase3_merge_revisions',
                })
                continue
            if v3 != v4:
                findings.append({
                    'severity': 'fail', 'validator': 'kill_switch_integrity',
                    'message': f'{field_name} drifted between Phase 3 final_candidate (audited '
                               f'rewrite) and Phase 4 expansion',
                    'phase3_value': v3[:120] + ('…' if len(v3) > 120 else ''),
                    'phase4_value': v4[:120] + ('…' if len(v4) > 120 else ''),
                })
            continue

        # Primary check: Phase 2 → Phase 4 byte-identical
        if v2 != v4:
            findings.append({
                'severity': 'fail', 'validator': 'kill_switch_integrity',
                'message': f'{field_name} drifted between Phase 2 candidate and Phase 4 expansion',
                'phase2_value': v2[:120] + ('…' if len(v2) > 120 else ''),
                'phase4_value': v4[:120] + ('…' if len(v4) > 120 else ''),
            })
            continue

        # Secondary check: Phase 3 final_candidate (only if present and well-typed — i.e., 3.3 ran)
        if has_phase3_chain:
            v3, p3_finding = _check_kill_switch_value(final_candidate, field_path, 'Phase 3 final_candidate', field_name)
            if p3_finding is not None:
                findings.append(p3_finding)
            elif v2 != v3:
                findings.append({
                    'severity': 'fail', 'validator': 'kill_switch_integrity',
                    'message': f'{field_name} drifted between Phase 2 candidate and Phase 3 final_candidate (revise path)',
                    'phase2_value': v2[:120] + ('…' if len(v2) > 120 else ''),
                    'phase3_value': v3[:120] + ('…' if len(v3) > 120 else ''),
                })

    if not findings:
        if falsification_rewritten:
            chain_desc = ('Phase 2 → 3.3 → 4 (revise path; falsification_prediction re-based at '
                          '3.3 via audited rewrite, compute_budget full-chain)')
        elif has_phase3_chain:
            chain_desc = 'Phase 2 → 3.3 final_candidate → 4 (revise path)'
        else:
            chain_desc = 'Phase 2 → 4 (Phase 3 passthrough, advance path)'
        findings.append({'severity': 'pass', 'validator': 'kill_switch_integrity', 'message': f'All 2 kill-switch fields byte-identical across {chain_desc}'})
    return findings
