"""expansion_completeness validator: check that Phase 4 expansion has the structural sections
the idea-card rendering depends on, and that the prompt's hard rules ("≥ 2 why_prior_stopped",
"steps[] with linked_component + linked_falsification", "feasibility 5 sub-verdicts + overall")
were actually honored.

kill_switch_integrity only checks the kill-switch echo. The rest of the Phase 4 schema can
silently degrade — an LLM under context pressure may produce a single `why_prior_stopped`,
omit the `feasibility_validation.engineering` block, leave `abstract_draft` empty — and the
rendered card will surface blank sections without anyone noticing. This validator catches that.

Severity: fail. Missing structural sections would silently render as blank content in the
markdown / LaTeX output; this validator blocks the run so the user either re-runs Phase 4.1
or explicitly opts in via the `--allow-incomplete-expansion` override at the orchestrator level.
"""
from __future__ import annotations
import json
from pathlib import Path


REQUIRED_TOP_LEVEL = [
    "title",
    "title_zh",                  # Chinese title for the 中文 cards (acronyms stay English)
    "method_name",               # short method handle, e.g. 'Persistent Baseline GRPO (PB-GRPO)'
    "hook",
    "abstract_draft",
    "motivation",
    "core_claim",
    "sub_claims",
    "method_flow",
    "plain_motivation_en",       # 普通版 English motivation (rendered deliverable)
    "plain_motivation_zh",       # 普通版 Chinese motivation
    "plain_method_steps_en",     # 普通版 per-step rendering (mirrors method_flow.steps)
    "plain_method_steps_zh",
    "plain_method_modules_en",   # module buckets over the plain steps
    "plain_method_modules_zh",
    "falsification_prediction",  # paragraph (new flat schema)
    "compute_budget",            # flat (new schema; was nested under falsification_prediction)
    "almost_prior_paper_id",     # flat (new schema; was R0_case.almost_prior.paper_id)
    "what_step_was_missed",      # flat (new schema; was R0_case.almost_prior.what_step_was_missed)
    "feasibility_validation",
    "differentiation_from_lit",
    "reviewer_concerns_and_responses",
    "literature_breakdown",      # Phase 0 + 3.1 lit tables rendered in the audit card
]

MOTIVATION_SUBFIELDS = [
    "problem_framing",
    "why_now",
    "why_prior_stopped",
    "what_changes_when_gap_closes",
]

FEASIBILITY_SUBVERDICTS = ["compute", "data", "theoretical", "engineering", "falsification"]

STEP_FIELDS = ["step_id", "title", "what_changes", "linked_component", "linked_falsification"]

PLAIN_STEP_FIELDS = ["step_id", "what_to_do", "why_this_makes_sense"]
PLAIN_MODULE_FIELDS = ["module_id", "purpose_oneline", "step_ids"]

# Equations render inline under the method step they explain (linked_step_id), with a bilingual
# caption (description = English, description_zh = idiomatic Chinese for the 中文 card).
EQUATION_FIELDS = ["id", "latex", "description", "description_zh", "linked_step_id"]


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
            "severity": "fail", "validator": "expansion_completeness",
            "message": f"Top-level fields missing or empty: {missing_top}. PDF rendering will leave these sections blank.",
            "missing_fields": missing_top,
        })

    # 2. Motivation sub-fields + why_prior_stopped count
    motivation = p4.get("motivation") or {}
    missing_mot = [f for f in MOTIVATION_SUBFIELDS if _is_empty(motivation.get(f))]
    if missing_mot:
        findings.append({
            "severity": "fail", "validator": "expansion_completeness",
            "message": f"motivation sub-fields missing or empty: {missing_mot}.",
            "missing_fields": missing_mot,
        })
    why_stopped = motivation.get("why_prior_stopped") or []
    if isinstance(why_stopped, list) and len(why_stopped) < 2:
        findings.append({
            "severity": "fail", "validator": "expansion_completeness",
            "message": f"motivation.why_prior_stopped has {len(why_stopped)} entries; prompt rule requires ≥ 2 with paper_id citations.",
        })
    else:
        for i, entry in enumerate(why_stopped if isinstance(why_stopped, list) else []):
            missing_sub = [f for f in ("paper_id", "what_they_did", "what_they_did_not_do", "structural_reason_they_stopped")
                           if _is_empty((entry or {}).get(f))]
            if missing_sub:
                findings.append({
                    "severity": "fail", "validator": "expansion_completeness",
                    "message": f"motivation.why_prior_stopped[{i}] missing sub-fields: {missing_sub}.",
                })

    # 3. method_flow.steps[] each with linked_component + linked_falsification
    method_flow = p4.get("method_flow") or {}
    steps = method_flow.get("steps") or []
    if not isinstance(steps, list) or len(steps) == 0:
        findings.append({
            "severity": "fail", "validator": "expansion_completeness",
            "message": "method_flow.steps[] is missing or empty.",
        })
    else:
        for i, step in enumerate(steps):
            missing_step = [f for f in STEP_FIELDS if _is_empty((step or {}).get(f))]
            if missing_step:
                findings.append({
                    "severity": "fail", "validator": "expansion_completeness",
                    "message": f"method_flow.steps[{i}] missing fields: {missing_step}.",
                })

    # 3b. plain_method_steps_{en,zh} must mirror method_flow.steps (same step_ids, same order)
    #     and carry the plain sub-fields. The 普通版 cards render directly from these, so any
    #     drift from method_flow silently desyncs the deliverable from the audited method.
    step_ids = [(s or {}).get("step_id") for s in steps] if isinstance(steps, list) else []
    for lang in ("en", "zh"):
        plain_steps = p4.get(f"plain_method_steps_{lang}") or []
        if not isinstance(plain_steps, list) or len(plain_steps) == 0:
            findings.append({
                "severity": "fail", "validator": "expansion_completeness",
                "message": f"plain_method_steps_{lang} is missing or empty.",
            })
            continue
        plain_ids = [(s or {}).get("step_id") for s in plain_steps]
        if plain_ids != step_ids:
            findings.append({
                "severity": "fail", "validator": "expansion_completeness",
                "message": f"plain_method_steps_{lang} step_ids {plain_ids} do not match method_flow.steps {step_ids} (must be same ids, same order).",
            })
        for i, s in enumerate(plain_steps):
            missing = [f for f in PLAIN_STEP_FIELDS if _is_empty((s or {}).get(f))]
            if missing:
                findings.append({
                    "severity": "fail", "validator": "expansion_completeness",
                    "message": f"plain_method_steps_{lang}[{i}] missing fields: {missing}.",
                })

    # 3c. plain_method_modules_{en,zh} buckets must carry their sub-fields and reference known step_ids
    known_ids = set(filter(None, step_ids))
    for lang in ("en", "zh"):
        modules = p4.get(f"plain_method_modules_{lang}") or []
        if not isinstance(modules, list) or len(modules) == 0:
            findings.append({
                "severity": "fail", "validator": "expansion_completeness",
                "message": f"plain_method_modules_{lang} is missing or empty.",
            })
            continue
        for i, m in enumerate(modules):
            missing = [f for f in PLAIN_MODULE_FIELDS if _is_empty((m or {}).get(f))]
            if missing:
                findings.append({
                    "severity": "fail", "validator": "expansion_completeness",
                    "message": f"plain_method_modules_{lang}[{i}] missing fields: {missing}.",
                })
            bad_ids = [sid for sid in ((m or {}).get("step_ids") or []) if sid not in known_ids]
            if bad_ids:
                findings.append({
                    "severity": "fail", "validator": "expansion_completeness",
                    "message": f"plain_method_modules_{lang}[{i}] references unknown step_ids {bad_ids} (not in method_flow.steps).",
                })

    # 3d. key_equations (optional) render inline under their step: each must carry the bilingual
    #     caption and a linked_step_id that points at a real method_flow step, or the renderer
    #     drops it into a detached fallback block (the very layout this design removes).
    equations = p4.get("key_equations") or []
    if isinstance(equations, list):
        for i, e in enumerate(equations):
            missing = [f for f in EQUATION_FIELDS if _is_empty((e or {}).get(f))]
            if missing:
                findings.append({
                    "severity": "fail", "validator": "expansion_completeness",
                    "message": f"key_equations[{i}] missing fields: {missing}.",
                })
            sid = (e or {}).get("linked_step_id")
            if sid and sid not in known_ids:
                findings.append({
                    "severity": "fail", "validator": "expansion_completeness",
                    "message": f"key_equations[{i}].linked_step_id '{sid}' is not a known method_flow step_id; it would render in the detached fallback block.",
                })

    # 4. feasibility_validation has 5 sub-verdicts + overall
    feas = p4.get("feasibility_validation") or {}
    for sv in FEASIBILITY_SUBVERDICTS:
        block = feas.get(sv)
        if _is_empty(block):
            findings.append({
                "severity": "fail", "validator": "expansion_completeness",
                "message": f"feasibility_validation.{sv} block missing.",
            })
        elif isinstance(block, dict):
            if _is_empty(block.get("verdict")):
                findings.append({
                    "severity": "fail", "validator": "expansion_completeness",
                    "message": f"feasibility_validation.{sv}.verdict empty.",
                })
            if _is_empty(block.get("rationale")):
                findings.append({
                    "severity": "fail", "validator": "expansion_completeness",
                    "message": f"feasibility_validation.{sv}.rationale empty.",
                })
    if _is_empty(feas.get("overall")):
        findings.append({
            "severity": "fail", "validator": "expansion_completeness",
            "message": "feasibility_validation.overall verdict missing.",
        })

    # 5. reviewer_concerns_and_responses non-empty (at least the strongest_attack from Phase 3.2)
    rcr = p4.get("reviewer_concerns_and_responses") or []
    if isinstance(rcr, list) and len(rcr) == 0:
        findings.append({
            "severity": "fail", "validator": "expansion_completeness",
            "message": "reviewer_concerns_and_responses[] empty; expected ≥ 1 entry from Phase 3.2 strongest_attack.",
        })

    if not findings:
        findings.append({
            "severity": "pass", "validator": "expansion_completeness",
            "message": "All required Phase 4 sections present and non-empty.",
        })
    return findings
