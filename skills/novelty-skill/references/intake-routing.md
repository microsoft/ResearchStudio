# Intake routing — Phase 1 OOD triggers and clarification rules

This file documents the routing decisions Phase 1 makes *after* lens probing (`lens-probes.md`). Lens probing identifies whether the problem has a literature-grounded bottleneck; intake routing decides whether the system should proceed at all given the user's stated constraints.

## OOD triggers — emit `do_not_generate.md`

The skill must refuse to ideate (with concrete remedial steps) when any of these is true:

1. **Too broad**. The user's problem is "I want to do an AI paper" or "give me ideas in ML."
2. **No anchor**. No clear domain, task, data, or baseline named, AND the user does not provide them after one round of clarification.
3. **Saturated area**. Phase 0 returns saturation flag (>= 60% of recent work in one methodology) AND no Phase 1 lens reaches sharpness ≥ 2 — i.e., the field has been worked over to the point where the standard lenses produce no novel sharp diagnosis.
4. **Engineering integration**. The request is "ship this feature in our system" rather than "produce a research contribution claim."
5. **Application-tail with no taxonomy fit**. Phase 0 returns `taxonomy_coverage_warning` AND no lens reaches sharpness ≥ 2.
6. **No verifiable benchmark**. The problem has no metric or eval pipeline that can verify a claim.
7. **Constraint-venue mismatch**. User wants ICML Oral but has 2 weeks and a laptop GPU.
8. **Unobtainable resources**. Required data or compute is not feasible.

Each OOD case has a corresponding **remedial step** the skill suggests:

- (1)-(2) → ask the user to provide domain, task, baseline, data.
- (3) → suggest a literature-mapping query first or pivot to a sub-problem; this skill is the wrong tool when the area has been worked over.
- (4) → suggest the user reframe as a contribution claim; engineering integration is out of scope.
- (5) → suggest writing a benchmark or analysis paper, or running the skill against a sub-problem with cleaner taxonomy fit.
- (6) → recommend constructing a benchmark first.
- (7) → recommend either a different venue or scope reduction.
- (8) → recommend pivoting to a problem with feasible resources.

## Clarification triggers — emit `clarification_request.md`

Less severe than OOD: the user has *some* anchor but is missing fields the lens probes need. Phase 1 emits a structured clarification request rather than refusing outright. Triggers:

- **Missing baseline**. No current method named — lens probes can't find "the gap left by X" without X.
- **Missing constraints**. No compute / data / time budget — Phase 4 can't audit feasibility.
- **Ambiguous target venue**. Conference matters because the same idea matures differently for ICLR vs NeurIPS vs a workshop.
- **Theory-vs-empirical preference unstated**. Affects which lenses (theory-leaning vs engineering-leaning) the system surfaces by default in cases where multiple are sharp.
- **Active lens count = 1**. Sharp on one lens but not 2; user's reframing of the problem might activate a second.

Clarification request format:

```markdown
# Clarification needed

I can't run the full diagnosis without the following. Each item explains what changes if you provide it.

- **{field}**: {what it is} — affects {which phase / lens / scoring dimension}.
- ...

If you'd rather proceed with what we have, I'll flag the missing fields and emit a `do_not_generate.md` with the gap list rather than a degraded idea card.
```

## Phase 1 output schema

```json
{
  "intake": {
    "domain": "...", "venue": "...", "time": "...", "data": [...], "compute": "...",
    "expertise": "...", "preference": "...", "baseline": "...", "limitation": "...",
    "contribution_type": "...", "risk": "..."
  },
  "active_lenses": [
    {"lens_id": "...", "leaning": "theory|engineering|hybrid", "sharpness": 0, "gap": "..."}
  ],
  "leaning_balance": "theory + engineering | theory-only-justified | engineering-only-justified | imbalanced",
  "bottleneck_statement": "<paragraph stitching active lens gaps with Phase 0 paper IDs>",
  "what_phase_0_already_tried": ["..."],
  "what_phase_0_did_not_address": ["..."],
  "anti_patterns_to_avoid": [
    {"composition": [...], "reason": "...", "required_mitigation": "...", "applicable": true}
  ],
  "state": "proceed | needs_clarification | do_not_generate",
  "missing_fields": [],
  "ood_reasons": [],
  "remedial_steps": []
}
```

The `state` decision rule:

- `proceed` — `len(active_lenses) >= 2`, leaning balance satisfied, no OOD triggers.
- `needs_clarification` — `len(active_lenses) < 2` but the gap looks fillable; or leaning balance imbalanced and the user has not declared preference. Emit `missing_fields`.
- `do_not_generate` — any OOD trigger fires AND the trigger isn't fixable by clarification (e.g., saturated area is not user-fixable; missing baseline is). Emit `ood_reasons` and `remedial_steps`.
