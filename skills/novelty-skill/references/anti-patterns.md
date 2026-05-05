# Anti-patterns — reject-favored compositions to guard against

This file is a **guard, not a ban**. The 1947-paper analysis surfaced three 2-way compositions whose Oral rate is well below dataset baseline. They are not forbidden — sometimes a problem genuinely calls for one — but Phase 1 must flag them in `anti_patterns_to_avoid` and Phase 4 audit must explicitly verify the documented failure mode is mitigated before such a composition advances.

This is the **only place the historical acceptance prior enters the lens-mode design**. The prior is used as a structural risk signal, not as a generation guidance.

## The three reject-favored 2-way compositions

| Composition | n | Oral rate | Failure mode | Required mitigation if used |
|---|---|---|---|---|
| `assumption_audit_and_relax` + `auxiliary_signal_engineering` | 40 | 30% | "Audit promises a principled diagnosis but the auxiliary-signal action delivers a heuristic — reviewers read this as the diagnosis was theater." | The audit must produce a *derivable* identifiability condition, and the auxiliary signal must be the *unique signal that satisfies that condition*. A coincidence of "we audited X and added signal Y" is not enough. |
| `assumption_audit_and_relax` + `invariance_as_architectural_constraint` | 57 | 39% | "The audit and the invariance act on different abstractions; nothing structurally ties them. The audit reveals an assumption, but the invariance is dropped on top of the architecture independently." | The relaxed assumption must *imply* the invariance: removing the assumption must mathematically force the symmetry, not merely permit it. The Phase 4 audit must check this implication chain. |
| `assumption_audit_and_relax` + `root_cause_surgical_remediation` | 111 | 44% | "Audit identifies the assumption, but the surgical fix is local engineering without an analytic preservation guarantee. Largest reject-favored cell in the dataset; reviewers say 'the diagnosis was right but the fix is just a patch.'" | Pair the surgical fix with an analytic refinement (a preservation theorem, a stability bound, a regret guarantee). Without it, this composition is reject-prone regardless of empirical result. |

## How Phase 1 uses this

After active lenses are determined, Phase 1 emits:

```json
{
  "active_lenses": [...],
  "bottleneck_statement": "...",
  "anti_patterns_to_avoid": [
    {
      "composition": ["assumption_audit_and_relax", "root_cause_surgical_remediation"],
      "reason": "<one of the failure modes from the table above>",
      "required_mitigation": "<the mitigation from the table>",
      "applicable": true
    }
  ]
}
```

A composition is `applicable: true` only if both innovation patterns are in the active lens set. Phase 2 must then either avoid this composition or include the required mitigation as an explicit Phase 3 generation constraint.

## How Phase 4 uses this

If a generated candidate's `pattern_composition` matches one of the three anti-patterns and the candidate does not visibly include the required mitigation, the candidate is **rejected outright**, regardless of audit dimension scores. The mitigation must be *visible in the candidate's `core_mechanism` and `falsification_prediction`*, not merely claimed in the framing.

## What this is not

- **Not a ban**. The data shows these compositions Oral 30-44% of the time; they can succeed. The prior here is a risk weight, not a verdict.
- **Not a generation incentive**. The system never proposes a composition because of its acceptance prior. The prior is consulted only after the lens-driven composition is proposed, to check for the documented failure mode.
- **Not the only source of reviewer risk**. Phase 4 dimension `Failure-mode exposure` continues to check innovation pattern-card-level failure modes. Anti-patterns are a level above: composition-level failure modes that aren't visible in any single card.

## Note on the 100%-Oral composition

The dataset's standout 3-way `assumption_audit_and_relax + formal_reframing_via_equivalence + shared_latent_alignment` (n=18, 0% Reject) is **not** treated as a target template either. It is a *case study*: when the bottleneck statement genuinely calls for all three lenses simultaneously, this composition has historical evidence of working. When it does not, the system must not contort the bottleneck statement to summon this composition. See `references/composition-templates.md` for the long form of this principle.
