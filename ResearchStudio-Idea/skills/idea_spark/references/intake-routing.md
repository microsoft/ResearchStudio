# Intake routing — Phase 1 OOD triggers

Phase 1 routes the user's input to one of two states: `proceed` (run Phase 2) or `do_not_generate` (emit a diagnosis explaining what's missing). This file documents the routing decisions.

## OOD triggers — emit `do_not_generate.md`

The skill refuses to ideate (with concrete remedial steps) when any of these fires:

1. **Too broad.** The user's problem is "I want to do an AI paper" or "give me ideas in ML" — no specific direction to ground a bottleneck against.
2. **No anchor.** No clear domain, task, data, or baseline named — Phase 1 cannot identify what limitation the candidate would address.

Each OOD case has a corresponding **remedial step** the skill suggests:

- (1) → ask the user to narrow the direction (specific area + specific limitation).
- (2) → ask the user to provide domain, task, baseline, and data.

Other concerns (engineering-integration framing, no verifiable benchmark, venue-time mismatch, unobtainable resources) are NOT routed to `do_not_generate` — they surface naturally downstream:

- Engineering-integration framing → Phase 2 generates a candidate that reads as engineering rather than research; reviewer-concerns-and-responses at Phase 4 surface this.
- No verifiable benchmark → falsification_prediction has no metric to commit to, exposing the issue.
- Venue-time mismatch → Phase 4's feasibility_validation catches with full context (compute_budget vs intake.compute, calendar against venue cycle).
- Unobtainable resources → Phase 4's feasibility_validation.data and .compute catch with full context.

Phase 1's OOD job is narrow: catch input the skill cannot do anything with. Inputs that the skill *can* generate against (even imperfectly) go through, and downstream phases handle their specific concerns.

## State decision rule

- `proceed` — bottleneck_statement can cite ≥ 2 paper_ids from lit_table that actually carry the bottleneck's residue, AND neither OOD trigger fires.
- `do_not_generate` — either OOD trigger fires, OR lit_table has fewer than ~5 papers genuinely related to the user's direction (the rest are loose keyword matches), so a literature-grounded bottleneck cannot be written.

In all `do_not_generate` cases, populate `ood_reasons` (which trigger fired) and `remedial_steps` (concrete fields to add for re-invocation). Phase 1 does not pause to ask the user mid-flow — it emits the diagnosis and stops.
