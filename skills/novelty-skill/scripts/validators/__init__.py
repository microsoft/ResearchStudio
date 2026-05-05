"""NoveltySkill output validators.

Two validators:
  kill_switch_integrity   — kill-switch fields (falsification.what_we_run / .compute_budget /
                            mechanism_probe_proposal) byte-identical Phase 2 → Phase 4 (or
                            Phase 2 → Phase 3.3 final_candidate → Phase 4 when revise ran).
                            Hard fail on drift.
  expansion_completeness  — Phase 4 expansion has the structural sections the idea-card PDF templating needs
                            (motivation with ≥ 2 why_prior_stopped, method_flow.steps[] with
                            linked_component + linked_falsification, feasibility 5 sub-verdicts +
                            overall, abstract_draft, core_claim). Soft warn — drift flagged not blocked.

Earlier design also had:
  - V_anti_pattern (deleted): keyword detection for anti-pattern mitigation. Substantively
    duplicated by Phase 3.2 audit's anti_pattern_check (mitigation_substantively_delivered),
    which judges at semantic level; keyword version was redundant.
  - V2 / V3 / V4 (deleted): composition primary check / evidence chain / anchor diversity
    Jaccard. Removed because the simplified Phase 2 schema renders them either trivially
    satisfied or directly enforced in the prompt itself.

Usage:
  from scripts.validators import run_all_validators
  findings = run_all_validators(phase2_path, phase3_path, phase4_path)
  if any(f['severity'] == 'fail' for f in findings):
      raise ValidatorError(...)
"""
from __future__ import annotations
from .kill_switch_integrity import validate_kill_switch_integrity
from .expansion_completeness import validate_expansion_completeness


def run_all_validators(phase2_path=None, phase3_path=None, phase4_path=None, phase1_path=None) -> list[dict]:
    """Run kill_switch_integrity + expansion_completeness given which phase outputs are available."""
    findings = []

    if phase2_path and phase3_path and phase4_path:
        findings.extend(validate_kill_switch_integrity(phase2_path, phase3_path, phase4_path))

    if phase4_path:
        findings.extend(validate_expansion_completeness(phase4_path))

    return findings
