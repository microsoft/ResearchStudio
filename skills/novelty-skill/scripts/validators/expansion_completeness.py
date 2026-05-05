"""expansion_completeness validator: check that Phase 4 expansion has the structural sections
the idea-card PDF template depends on, and that the prompt's hard rules ("≥ 2 why_prior_stopped",
"steps[] with linked_component + linked_falsification", "feasibility 5 sub-verdicts + overall")
were actually honored.

kill_switch_integrity only checks the kill-switch echo. The rest of the Phase 4 schema can
silently degrade — an LLM under context pressure may produce a single `why_prior_stopped`,
omit the `feasibility_validation.engineering` block, leave `abstract_draft` empty — and the
PDF will render with blank sections without anyone noticing. This validator catches that.

Severity: warn (not fail). The PDF still ships; the user is alerted to the missing sections
so they can re-run Phase 4.1 or fill the gaps manually before sharing.
"""
from __future__ import annotations
import json
from pathlib import Path


REQUIRED_TOP_LEVEL = [
    "title",
    "hook",
    "abstract_draft",
    "motivation",
    "core_claim",
    "sub_claims",
    "method_flow",
    "theoretical_leg",
    "engineering_leg",
    "falsification_prediction",
    "mechanism_probe_proposal",
    "feasibility_validation",
    "differentiation_from_lit",
    "reviewer_concerns_and_responses",
]

MOTIVATION_SUBFIELDS = [
    "problem_framing",
    "why_now",
    "why_prior_stopped",
    "what_changes_when_gap_closes",
]

FEASIBILITY_SUBVERDICTS = ["compute", "data", "theoretical", "engineering", "falsification"]

STEP_FIELDS = ["step_id", "title", "what_changes", "linked_component", "linked_falsification"]


def _is_empty(v) -> bool:
    if v is None: return True
    if isinstance(v, str) and not v.strip(): return True
    if isinstance(v, (list, dict)) and len(v) == 0: return True
    return False


def validate_expansion_completeness(phase4_path: str) -> list[dict]:
    findings = []
    p4 = json.loads(Path(phase4_path).read_text())

    # 1. Top-level fields present and non-empty
    missing_top = [f for f in REQUIRED_TOP_LEVEL if _is_empty(p4.get(f))]
    if missing_top:
        findings.append({
            "severity": "warn", "validator": "expansion_completeness",
            "message": f"Top-level fields missing or empty: {missing_top}. PDF rendering will leave these sections blank.",
            "missing_fields": missing_top,
        })

    # 2. Motivation sub-fields + why_prior_stopped count
    motivation = p4.get("motivation") or {}
    missing_mot = [f for f in MOTIVATION_SUBFIELDS if _is_empty(motivation.get(f))]
    if missing_mot:
        findings.append({
            "severity": "warn", "validator": "expansion_completeness",
            "message": f"motivation sub-fields missing or empty: {missing_mot}.",
            "missing_fields": missing_mot,
        })
    why_stopped = motivation.get("why_prior_stopped") or []
    if isinstance(why_stopped, list) and len(why_stopped) < 2:
        findings.append({
            "severity": "warn", "validator": "expansion_completeness",
            "message": f"motivation.why_prior_stopped has {len(why_stopped)} entries; prompt rule requires ≥ 2 with paper_id citations.",
        })
    else:
        for i, entry in enumerate(why_stopped if isinstance(why_stopped, list) else []):
            missing_sub = [f for f in ("paper_id", "what_they_did", "what_they_did_not_do", "structural_reason_they_stopped")
                           if _is_empty((entry or {}).get(f))]
            if missing_sub:
                findings.append({
                    "severity": "warn", "validator": "expansion_completeness",
                    "message": f"motivation.why_prior_stopped[{i}] missing sub-fields: {missing_sub}.",
                })

    # 3. method_flow.steps[] each with linked_component + linked_falsification
    method_flow = p4.get("method_flow") or {}
    steps = method_flow.get("steps") or []
    if not isinstance(steps, list) or len(steps) == 0:
        findings.append({
            "severity": "warn", "validator": "expansion_completeness",
            "message": "method_flow.steps[] is missing or empty.",
        })
    else:
        for i, step in enumerate(steps):
            missing_step = [f for f in STEP_FIELDS if _is_empty((step or {}).get(f))]
            if missing_step:
                findings.append({
                    "severity": "warn", "validator": "expansion_completeness",
                    "message": f"method_flow.steps[{i}] missing fields: {missing_step}.",
                })

    # 4. feasibility_validation has 5 sub-verdicts + overall
    feas = p4.get("feasibility_validation") or {}
    for sv in FEASIBILITY_SUBVERDICTS:
        block = feas.get(sv)
        if _is_empty(block):
            findings.append({
                "severity": "warn", "validator": "expansion_completeness",
                "message": f"feasibility_validation.{sv} block missing.",
            })
        elif isinstance(block, dict):
            if _is_empty(block.get("verdict")):
                findings.append({
                    "severity": "warn", "validator": "expansion_completeness",
                    "message": f"feasibility_validation.{sv}.verdict empty.",
                })
            if _is_empty(block.get("rationale")):
                findings.append({
                    "severity": "warn", "validator": "expansion_completeness",
                    "message": f"feasibility_validation.{sv}.rationale empty.",
                })
    if _is_empty(feas.get("overall")):
        findings.append({
            "severity": "warn", "validator": "expansion_completeness",
            "message": "feasibility_validation.overall verdict missing.",
        })

    # 5. reviewer_concerns_and_responses non-empty (at least the strongest_attack from Phase 3.2)
    rcr = p4.get("reviewer_concerns_and_responses") or []
    if isinstance(rcr, list) and len(rcr) == 0:
        findings.append({
            "severity": "warn", "validator": "expansion_completeness",
            "message": "reviewer_concerns_and_responses[] empty; expected ≥ 1 entry from Phase 3.2 strongest_attack.",
        })

    if not findings:
        findings.append({
            "severity": "pass", "validator": "expansion_completeness",
            "message": "All required Phase 4 sections present and non-empty.",
        })
    return findings
