"""implementability_completeness validator: check that the Phase 4.1.5 implementability audit
(`phase4_implementability.json`) covers every method step and stays inside its bounded contract.

Phase 4.1.5 takes the terse Phase 4.1 method steps and rewrites each into an implementable, readable
specification (`enriched_steps[]`), recording the holes it filled or left open (`underspecified_points[]`).
The renderer swaps the enriched prose into the cards by `step_id`. Two ways this can silently go wrong:
  - a step is missing from `enriched_steps` → that step renders with the old terse text, so the card is
    inconsistently detailed and the user can't tell which steps were audited;
  - the audit re-emits a kill-switch field (`falsification_prediction` / `compute_budget`) → it must not,
    because those are byte-identical-preserved by earlier phases and this file structurally has no business
    carrying them.

Severity: fail. Coverage gaps would ship a half-enriched method; a kill-switch field in this file signals
the audit overstepped its bounded contract.
"""
from __future__ import annotations
import json
from pathlib import Path

ENRICHED_FIELDS = ["step_id", "what_changes", "what_to_do_en", "what_to_do_zh"]
KILL_SWITCH_FIELDS = ["falsification_prediction", "compute_budget"]


def _is_empty(v) -> bool:
    if v is None: return True
    if isinstance(v, str) and not v.strip(): return True
    if isinstance(v, (list, dict)) and len(v) == 0: return True
    return False


def validate_implementability_completeness(phase4_path: str, phase4_impl_path: str) -> list[dict]:
    findings = []
    p4 = json.loads(Path(phase4_path).read_text())
    impl = json.loads(Path(phase4_impl_path).read_text())

    # 1. No kill-switch field may appear in the audit file (bounded-contract guard).
    leaked = [f for f in KILL_SWITCH_FIELDS if f in impl]
    if leaked:
        findings.append({
            "severity": "fail", "validator": "implementability_completeness",
            "message": f"implementability audit file carries kill-switch field(s) {leaked}; it must never "
                       f"emit or touch falsification_prediction / compute_budget.",
        })

    # 2. enriched_steps must cover every method_flow step_id, same set, same order.
    steps = (p4.get("method_flow", {}) or {}).get("steps", []) or []
    method_ids = [(s or {}).get("step_id") for s in steps]
    enriched = impl.get("enriched_steps") or []
    if not isinstance(enriched, list) or len(enriched) == 0:
        findings.append({
            "severity": "fail", "validator": "implementability_completeness",
            "message": "enriched_steps[] is missing or empty; the audit must produce one entry per method step.",
        })
    else:
        enriched_ids = [(e or {}).get("step_id") for e in enriched]
        if enriched_ids != method_ids:
            findings.append({
                "severity": "fail", "validator": "implementability_completeness",
                "message": f"enriched_steps step_ids {enriched_ids} do not match method_flow.steps "
                           f"{method_ids} (must be same ids, same order — every step audited).",
            })
        for i, e in enumerate(enriched):
            missing = [f for f in ENRICHED_FIELDS if _is_empty((e or {}).get(f))]
            if missing:
                findings.append({
                    "severity": "fail", "validator": "implementability_completeness",
                    "message": f"enriched_steps[{i}] missing fields: {missing}.",
                })

    # 3. underspecified_points must be present (a list; may be empty when the method was already concrete).
    enriched_by_id = {(e or {}).get("step_id"): e for e in enriched if isinstance(e, dict)}
    pts = impl.get("underspecified_points")
    if pts is None or not isinstance(pts, list):
        findings.append({
            "severity": "fail", "validator": "implementability_completeness",
            "message": "underspecified_points[] missing or not a list (use [] when no holes were found).",
        })
    else:
        for i, pt in enumerate(pts):
            missing = [f for f in ("step_id", "hole", "fill", "severity") if _is_empty((pt or {}).get(f))]
            if missing:
                findings.append({
                    "severity": "fail", "validator": "implementability_completeness",
                    "message": f"underspecified_points[{i}] missing fields: {missing}.",
                })
            sev = (pt or {}).get("severity")
            if sev not in (None, "filled", "open"):
                findings.append({
                    "severity": "fail", "validator": "implementability_completeness",
                    "message": f"underspecified_points[{i}].severity '{sev}' invalid (expected 'filled' or 'open').",
                })
            # An open decision must be surfaced to the reader: the audit places a 【…】annotation inline in
            # the matching enriched step's prose (all three card languages). A bare open point that never
            # reaches the card silently drops the authorial decision, which is the whole point of flagging it.
            if sev == "open":
                e = enriched_by_id.get((pt or {}).get("step_id")) or {}
                no_marker = [f for f in ENRICHED_FIELDS[1:] if "【" not in str(e.get(f, ""))]
                if no_marker:
                    findings.append({
                        "severity": "fail", "validator": "implementability_completeness",
                        "message": f"underspecified_points[{i}] is 'open' for step {(pt or {}).get('step_id')!r} but its "
                                   f"enriched step carries no 【…】annotation in {no_marker}; an open decision must be "
                                   f"placed inline (right after the sentence it qualifies) in every card language.",
                    })

    if not findings:
        findings.append({
            "severity": "pass", "validator": "implementability_completeness",
            "message": "Implementability audit covers every method step and respects its bounded contract.",
        })
    return findings
