"""18 innovation lenses and 9 meta-categories. Copy of the taxonomy used by SKILL.md."""

CLUSTER_NAMES = {
    0: "Security Inversion",
    1: "Expressivity Analysis",
    2: "Causal Identification",
    3: "Cross-Domain Reframing",
    4: "Objective Reframing (RL)",
    5: "Symmetry Exploitation",
    6: "Domain-Knowledge Injection",
    7: "Probabilistic Reformulation",
    8: "Compositional Decomposition",
    9: "Process-Level Supervision",
    10: "Framework Import",
    11: "Assumption Inversion",
    12: "Loss/Objective Redesign",
    13: "Game-Theoretic Reformulation",
    14: "Formal Characterization",
    15: "Variational Reformulation",
    16: "Structural Reparameterization",
    17: "Convergence Analysis",
}

META_CATEGORIES = {
    "Cross-Domain Transfer": [3, 10],
    "Theoretical Formalization": [1, 14, 17],
    "Structural Diagnosis & Redesign": [12, 16],
    "Sequential Decision & Game Theory": [4, 13],
    "Symmetry & Domain Structure": [5, 6],
    "Compositional & Process Innovation": [8, 9],
    "Mathematical Reformulation": [7, 15],
    "Assumption & Role Inversion": [0, 11],
    "Causal Identification": [2],
}

CLUSTER_TO_META = {}
for _meta, _clusters in META_CATEGORIES.items():
    for _c in _clusters:
        CLUSTER_TO_META[_c] = _meta
