"""IdeaSpark output validators.

Validators:
  subpattern_citation_consistency — each Phase 2 gap_closure[] sub_pattern citation resolves to a
                            real C## cluster whose true parent == the cited main_pattern, and whose
                            cited parenthetical == that cluster's parent display name. Catches
                            citations guessed from the parent pattern's name instead of read from
                            overview.md.
  kill_switch_integrity   — kill-switch fields (falsification_prediction paragraph,
                            compute_budget) byte-identical Phase 2 → Phase 4 (or
                            Phase 2 → Phase 3.3 final_candidate → Phase 4 when revise ran).
                            Hard fail on drift.
  expansion_completeness  — Phase 4 expansion has the structural sections the idea-card rendering needs
                            (motivation with ≥ 2 why_prior_stopped, method_flow.steps[] with
                            linked_component + linked_falsification, feasibility 5 sub-verdicts +
                            overall, abstract_draft, core_claim). Hard fail — orchestrator blocks
                            ship unless `--allow-incomplete-expansion` override is set.
  implementability_completeness — Phase 4.1.5 implementability audit covers every method step
                            (enriched_steps[] one-per-step, same ids/order, each with what_changes +
                            what_to_do_en/zh), records underspecified_points[], and carries no
                            kill-switch field. Hard fail on coverage gap or bounded-contract breach.
  implementability_readability — Phase 4.1.5 std-register fields avoid the known readability regressions
                            (no "占位/placeholder" leak; no bare English jargon word in Chinese prose).
                            Warn — surfaces a slip past Hard rule 8 without blocking ship.

Usage:
  from scripts.validators import run_all_validators
  findings = run_all_validators(phase2_path, phase3_path, phase4_path)
  if any(f['severity'] == 'fail' for f in findings):
      raise ValidatorError(...)
"""
from __future__ import annotations
from .kill_switch_integrity import validate_kill_switch_integrity
from .expansion_completeness import validate_expansion_completeness
from .subpattern_citation_consistency import validate_subpattern_citation_consistency
from .implementability_completeness import validate_implementability_completeness
from .implementability_readability import validate_implementability_readability


def run_all_validators(phase2_path=None, phase3_path=None, phase4_path=None, phase1_path=None,
                       phase4_impl_path=None) -> list[dict]:
    """Run all validators given which phase outputs are available."""
    findings = []

    if phase2_path and phase3_path and phase4_path:
        findings.extend(validate_kill_switch_integrity(phase2_path, phase3_path, phase4_path))

    if phase2_path:
        findings.extend(validate_subpattern_citation_consistency(phase2_path))

    if phase4_path:
        findings.extend(validate_expansion_completeness(phase4_path))

    if phase4_path and phase4_impl_path:
        findings.extend(validate_implementability_completeness(phase4_path, phase4_impl_path))

    if phase4_impl_path:
        findings.extend(validate_implementability_readability(phase4_impl_path))

    return findings
