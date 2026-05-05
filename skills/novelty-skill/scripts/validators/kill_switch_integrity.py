"""kill_switch_integrity validator.

Phase 2 candidate emits three kill-switch fields:
  - falsification_prediction.what_we_run
  - falsification_prediction.compute_budget
  - mechanism_probe_proposal

These MUST equal byte-for-byte in the Phase 4 expansion. The prompts say "orchestrator
validator rejects drift" — this is that validator.

Architecture note: Phase 3.2 was previously in the byte-identical chain (Phase 2 → Phase 3
final_candidate → Phase 4). The audit-only Phase 3.2 design does NOT emit a final_candidate
— it produces a judgment report and leaves the candidate untouched. Phase 4 reads Phase 2's
candidate directly when verdict = advance. The chain is Phase 2 → Phase 4 (Phase 3 passthrough)
in the advance path, or Phase 2 → Phase 3.3 final_candidate → Phase 4 in the revise path.

This validator accepts phase3_path optionally: if Phase 3 contains a final_candidate (3.3 ran
or legacy schema), it validates the 3-link chain. If Phase 3 has no final_candidate (new
audit-only design without revise), it treats Phase 3 as passthrough and checks Phase 2 → Phase 4.

Why it matters: a misbehaving Phase 3.3 / Phase 4 model could substitute the kill-switch
experiment with an easier one ("we'll use a simpler dataset / smaller compute"), making the
candidate look more feasible than the original Phase 2 candidate committed to. This validator
catches that silently.
"""
from __future__ import annotations
import json
from pathlib import Path


KILL_SWITCH_FIELDS = [
    ('falsification_prediction', 'what_we_run'),
    ('falsification_prediction', 'compute_budget'),
    # mechanism_probe_proposal is top-level in Phase 2 + Phase 3 final_candidate + Phase 4 expand
    ('mechanism_probe_proposal',),
]


def _get_nested(d: dict, path: tuple) -> str | None:
    cur = d
    for k in path:
        if not isinstance(cur, dict): return None
        cur = cur.get(k)
        if cur is None: return None
    return cur if isinstance(cur, str) else None


def validate_kill_switch_integrity(phase2_path, phase3_path, phase4_path) -> list[dict]:
    """Read the phase outputs and check kill-switch fields are byte-identical.

    New flow (audit-only Phase 3.2): Phase 2.2 candidate → Phase 4 expansion. Phase 3.2 is a
    passthrough (no final_candidate emitted). V1 checks Phase 2 → Phase 4 directly.

    Backward compat: if Phase 3 contains a `final_candidate` (legacy revise-design output), V1 also
    checks Phase 2 → Phase 3 final_candidate → Phase 4. If Phase 3 has no final_candidate (new
    audit-only design), V1 silently skips that link.

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
    #   - Legacy schema (deprecated): phase3 is critique with auto-revised final_candidate. V1 validates 3-link chain.
    # The `final_candidate.falsification_prediction is not None` check distinguishes all three cases.
    final_candidate = p3.get('final_candidate') if isinstance(p3, dict) else None
    has_phase3_chain = final_candidate is not None and isinstance(final_candidate, dict) and final_candidate.get('falsification_prediction') is not None

    for field_path in KILL_SWITCH_FIELDS:
        v2 = _get_nested(winner_candidate, field_path)
        v4 = _get_nested(p4, field_path)
        field_name = '.'.join(field_path)

        if v2 is None:
            findings.append({'severity': 'warn', 'validator': 'kill_switch_integrity', 'message': f'Phase 2 candidate missing field {field_name}'})
            continue
        if v4 is None:
            findings.append({'severity': 'fail', 'validator': 'kill_switch_integrity', 'message': f'Phase 4 expansion missing echo of {field_name}'})
            continue

        # Primary check: Phase 2 → Phase 4
        if v2 != v4:
            findings.append({
                'severity': 'fail', 'validator': 'kill_switch_integrity',
                'message': f'{field_name} drifted between Phase 2 candidate and Phase 4 expansion',
                'phase2_value': v2[:120] + ('…' if len(v2) > 120 else ''),
                'phase4_value': v4[:120] + ('…' if len(v4) > 120 else ''),
            })
            continue

        # Secondary check (legacy): Phase 3 final_candidate (only if present)
        if has_phase3_chain:
            v3 = _get_nested(final_candidate, field_path)
            if v3 is None:
                findings.append({'severity': 'warn', 'validator': 'kill_switch_integrity', 'message': f'Phase 3 final_candidate present but missing field {field_name}'})
            elif v2 != v3:
                findings.append({
                    'severity': 'fail', 'validator': 'kill_switch_integrity',
                    'message': f'{field_name} drifted between Phase 2 candidate and Phase 3 final_candidate (legacy chain)',
                    'phase2_value': v2[:120] + ('…' if len(v2) > 120 else ''),
                    'phase3_value': v3[:120] + ('…' if len(v3) > 120 else ''),
                })

    if not findings:
        chain_desc = 'Phase 2 → 3.3 final_candidate → 4 (revise path)' if has_phase3_chain else 'Phase 2 → 4 (Phase 3 passthrough, advance path)'
        findings.append({'severity': 'pass', 'validator': 'kill_switch_integrity', 'message': f'All 3 kill-switch fields byte-identical across {chain_desc}'})
    return findings
