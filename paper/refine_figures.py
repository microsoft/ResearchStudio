#!/usr/bin/env python3
"""Refined camera-ready figures for technical_report.tex.

All quantitative panels are generated from files under data/. Schematic
figures use only quantities already stated in the report.
"""

from __future__ import annotations

import json
import textwrap
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PAPER = ROOT / "paper"
FIGS = PAPER / "figures"

BLUE = "#3B6FB6"       # Oral
GOLD = "#E69F00"       # High-cited
VERM = "#D55E00"       # Reject
GREEN = "#009E73"
PURPLE = "#7A5AA6"
GRAY = "#6E6E6E"
LIGHT = "#F7F8FA"
DARK = "#222222"

mpl.rcParams.update(
    {
        "font.size": 8.5,
        "font.family": "DejaVu Sans",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 0.7,
        "xtick.major.width": 0.7,
        "ytick.major.width": 0.7,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.03,
    }
)


def load_json(path: str):
    with (ROOT / path).open() as f:
        return json.load(f)


def short_name(name: str) -> str:
    repl = {
        "Audit and Relax Implicit Assumption": "Assumption audit",
        "Reframe via Alternative Formalism": "Formal reframing",
        "Align Heterogeneous Sources in Shared Space": "Shared latent alignment",
        "Encode Invariance as Hard Constraint": "Invariance constraint",
        "Diagnose Then Surgically Fix": "Surgical fix",
        "Audit Evaluation via Controlled Perturbation": "Evaluation audit",
        "Sharpen a Single Analytic Step": "Analytic refinement",
        "Exploit Redundancy via Compression": "Redundancy compression",
        "Decompose and Recombine": "Decompose / recombine",
        "Engineer Auxiliary Supervision Signal": "Auxiliary signal",
        "Localize via Causal Probing": "Causal probing",
        "Soft Probabilistic Relaxation": "Soft relaxation",
        "Aggregate Over Diverse Candidates": "Candidate aggregation",
    }
    return repl.get(name, name)


def wrap(s: str, width: int = 20) -> str:
    return "\n".join(textwrap.wrap(s, width=width, break_long_words=False))


def methodology_names():
    tax = load_json("data/clustering/results/methodologies.json")["taxonomy"]
    return {t["id"]: t["name"] for t in tax}


def primary_counts_by_decision():
    names = methodology_names()
    hierarchy = load_json("data/clustering/results/all_hierarchy.json")["papers"]
    records = load_json("data/dataset/all_records_full.json")
    p2m = {p["paper_id"]: p["primary_methodology"] for p in hierarchy}
    out = defaultdict(lambda: Counter())
    for r in records:
        mid = p2m.get(r["paper_id"], "")
        if not mid:
            continue
        if r.get("is_oral"):
            out[mid]["oral"] += 1
        if r.get("is_hc"):
            out[mid]["hc"] += 1
        if r.get("is_reject"):
            out[mid]["reject"] += 1
    return names, out


def panel_label(ax, label: str):
    ax.text(
        -0.02,
        1.04,
        label,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=10,
        fontweight="bold",
        color=DARK,
    )


def rounded_box(ax, xy, wh, text, fc, ec=None, lw=1.0, fs=8.2, weight="normal"):
    x, y = xy
    w, h = wh
    ec = ec or fc
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.018,rounding_size=0.035",
        facecolor=fc,
        edgecolor=ec,
        linewidth=lw,
    )
    ax.add_patch(patch)
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=fs,
        color=DARK,
        fontweight=weight,
        linespacing=1.25,
    )
    return patch


def arrow(ax, p1, p2, color=GRAY, lw=1.2, rad=0.0):
    ax.add_patch(
        FancyArrowPatch(
            p1,
            p2,
            arrowstyle="-|>",
            mutation_scale=11,
            linewidth=lw,
            color=color,
            connectionstyle=f"arc3,rad={rad}",
        )
    )


def fig_pipeline():
    fig, ax = plt.subplots(figsize=(12.0, 4.9))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.text(
        0.02,
        0.975,
        "NoveltySkill empirical substrate",
        fontsize=13,
        fontweight="bold",
        ha="left",
        va="top",
        color=DARK,
    )
    ax.text(
        0.02,
        0.915,
        "Contrast conference outcomes, induce strategy operators, then use reject evidence as an audit scaffold.",
        fontsize=8.8,
        ha="left",
        color=GRAY,
    )

    xs = [0.04, 0.235, 0.43, 0.625, 0.82]
    w = 0.145
    y = 0.50
    h = 0.26
    boxes = [
        ("Corpus\n1,947 papers\n2021-2025", "#EAF0FA", BLUE),
        ("Strategy extraction\n8 base fields\n+ 4 abstract fields", "#FFF4E0", GOLD),
        ("Embedding + clustering\nOpenAI embeddings\nUMAP + HDBSCAN", "#EAF7F1", GREEN),
        ("Induced substrate\n47 tactics\n13 patterns\n28 domains", "#F2EEF8", PURPLE),
        ("Skill artifact\noperational cards\nNoveltySkill audit\nidea card", "#FDEFE8", VERM),
    ]
    for i, (txt, fc, ec) in enumerate(boxes):
        rounded_box(ax, (xs[i], y), (w, h), txt, fc, ec=ec, lw=1.1, fs=8.2, weight="bold" if i in (0, 3, 4) else "normal")
        if i < len(boxes) - 1:
            arrow(ax, (xs[i] + w + 0.01, y + h / 2), (xs[i + 1] - 0.012, y + h / 2))

    # Corpus strata.
    strata = [("Oral", "1,014", BLUE), ("High-Cited", "211", GOLD), ("Reject", "722", VERM)]
    for j, (lab, num, col) in enumerate(strata):
        rounded_box(ax, (0.034 + j * 0.059, 0.30), (0.054, 0.085), f"{lab}\n{num}", col + "22", ec=col, lw=0.9, fs=6.2)

    # Substrate cards.
    rounded_box(ax, (0.60, 0.22), (0.13, 0.11), "13 cards\n8 panels each", "#F2EEF8", ec=PURPLE, fs=7.3)
    rounded_box(ax, (0.745, 0.22), (0.13, 0.11), "47 cards\n6 panels each", "#F2EEF8", ec=PURPLE, fs=7.3)
    arrow(ax, (0.69, 0.50), (0.665, 0.335), color=PURPLE, lw=1.0, rad=0.08)
    arrow(ax, (0.69, 0.50), (0.81, 0.335), color=PURPLE, lw=1.0, rad=-0.08)

    # Four findings band.
    findings = [
        ("Shared strategy space", "Reject mostly fails on execution"),
        ("k = 3 composition", "57.3% of papers"),
        ("Domain-conditioned rates", "same pattern, different landing odds"),
        ("PC vs community split", "Oral taste and citation durability diverge"),
    ]
    x0 = 0.055
    for i, (head, sub) in enumerate(findings):
        xi = x0 + i * 0.235
        rounded_box(ax, (xi, 0.065), (0.205, 0.105), f"{head}\n{sub}", "#FFFFFF", ec="#D6DAE0", lw=0.8, fs=7.1)
    ax.text(0.02, 0.19, "Empirical findings", fontsize=8, fontweight="bold", color=GRAY)

    FIGS.mkdir(exist_ok=True)
    out = FIGS / "fig_pipeline.pdf"
    fig.savefig(out)
    plt.close(fig)
    print(f"wrote {out}")


def fig_hierarchy_refined():
    names, counts = primary_counts_by_decision()
    hierarchy = load_json("data/clustering/results/all_hierarchy.json")
    cluster_to_m = hierarchy["cluster_to_methodology"]
    n_clusters = Counter(c["primary_methodology"] for c in cluster_to_m if c.get("primary_methodology"))

    mids = sorted(
        names,
        key=lambda m: counts[m]["oral"] + counts[m]["hc"] + counts[m]["reject"],
        reverse=True,
    )
    labels = [short_name(names[m]) for m in mids]
    oral = np.array([counts[m]["oral"] for m in mids])
    hc = np.array([counts[m]["hc"] for m in mids])
    reject = np.array([counts[m]["reject"] for m in mids])
    total = oral + hc + reject
    clusters = np.array([n_clusters[m] for m in mids])

    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(11.6, 5.7), gridspec_kw={"width_ratios": [2.9, 1.15], "wspace": 0.08}
    )
    y = np.arange(len(mids))
    ax1.barh(y, oral, color=BLUE, label="Oral", height=0.72)
    ax1.barh(y, hc, left=oral, color=GOLD, label="High-Cited", height=0.72)
    ax1.barh(y, reject, left=oral + hc, color=VERM, label="Reject", height=0.72)
    ax1.set_yticks(y)
    ax1.set_yticklabels(labels)
    ax1.invert_yaxis()
    ax1.set_xlabel("Papers assigned by cluster-level primary mapping")
    ax1.grid(axis="x", color="#E5E7EB", linewidth=0.7)
    ax1.legend(frameon=False, ncol=3, loc="lower right", fontsize=8)
    for i, t in enumerate(total):
        ax1.text(t + 4, i, f"{t}", va="center", fontsize=7, color=GRAY)
    panel_label(ax1, "a")
    ax1.set_title("Level-1 innovation patterns: volume and outcome mix", loc="left", fontsize=10.5, pad=8)

    ax2.hlines(y, 0, clusters, color="#CCD2DA", linewidth=2.0)
    ax2.scatter(clusters, y, s=48, color=PURPLE, edgecolor="white", linewidth=0.8, zorder=3)
    ax2.set_yticks(y)
    ax2.set_yticklabels([])
    ax2.invert_yaxis()
    ax2.set_xlabel("# tactical clusters")
    ax2.set_xlim(0, max(clusters) + 1.5)
    ax2.grid(axis="x", color="#E5E7EB", linewidth=0.7)
    for i, c in enumerate(clusters):
        ax2.text(c + 0.25, i, str(c), va="center", fontsize=7, color=GRAY)
    panel_label(ax2, "b")
    ax2.set_title("Fragmentation", loc="left", fontsize=10.5, pad=8)

    fig.suptitle(
        "Taxonomy hierarchy without forcing a donut: large framing patterns split into many tactics",
        x=0.02,
        ha="left",
        y=1.01,
        fontsize=12,
        fontweight="bold",
    )
    out = FIGS / "fig_hierarchy_donut.pdf"
    fig.savefig(out)
    plt.close(fig)
    print(f"wrote {out}")


def fig_multilabel_combinations_refined():
    combos = load_json("data/clustering/multilabel/extra/combinations_by_size.json")
    names = methodology_names()

    def label_combo(combo):
        return " + ".join(short_name(names[c]) for c in combo)

    panels = [
        ("Top 2-way combinations", combos["top10_pairs_by_oral"][:8], BLUE),
        ("Top 3-way combinations", combos["top10_triples_by_oral"][:8], VERM),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 5.15), gridspec_kw={"wspace": 0.58})
    for ax, (title, rows, accent) in zip(axes, panels):
        rows = list(reversed(rows))
        y = np.arange(len(rows))
        totals = np.array([r["oral"] + r["hc"] + r["reject"] for r in rows])
        oral = np.array([100 * r["oral"] / max(1, totals[i]) for i, r in enumerate(rows)])
        hc = np.array([100 * r["hc"] / max(1, totals[i]) for i, r in enumerate(rows)])
        reject = np.array([100 * r["reject"] / max(1, totals[i]) for i, r in enumerate(rows)])
        labels = [wrap(label_combo(r["combo"]), 26) for r in rows]

        ax.barh(y, oral, color=BLUE, height=0.70, label="Oral")
        ax.barh(y, hc, left=oral, color=GOLD, height=0.70, label="High-Cited")
        ax.barh(y, reject, left=oral + hc, color=VERM, height=0.70, label="Reject")
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=6.8)
        ax.set_xlim(0, 100)
        ax.set_xlabel("Composition outcome share (%)")
        ax.set_title(title, loc="left", fontsize=10.5, fontweight="bold", color=DARK)
        ax.grid(axis="x", color="#E5E7EB", linewidth=0.7)
        ax.axvline(58.5, color=GRAY, linestyle=(0, (3, 2)), linewidth=1.0)
        ax.text(58.5, len(rows) - 0.1, "dataset pO", ha="center", va="bottom", fontsize=6.7, color=GRAY)
        for i, r in enumerate(rows):
            n = int(totals[i])
            ax.text(101.2, i, f"n={n}", va="center", fontsize=6.4, color=GRAY)
            if r["reject"] == 0:
                ax.add_patch(
                    FancyBboxPatch(
                        (-1.0, i - 0.43),
                        102.0,
                        0.86,
                        boxstyle="round,pad=0.02,rounding_size=0.08",
                        facecolor="none",
                        edgecolor=GREEN,
                        linewidth=1.5,
                        clip_on=False,
                    )
                )
                ax.text(73, i, "0 Reject", va="center", ha="center", fontsize=7.5, color=GREEN, fontweight="bold")
        ax.set_ylim(-0.7, len(rows) - 0.25)
    axes[0].legend(frameon=False, ncol=3, bbox_to_anchor=(0.0, -0.16), loc="upper left", fontsize=8)
    fig.suptitle(
        "Multi-label compositions: accepted work is a pattern stack, not a single category",
        x=0.01,
        ha="left",
        y=1.02,
        fontsize=12,
        fontweight="bold",
    )
    out = FIGS / "fig_multilabel_combinations.pdf"
    fig.savefig(out)
    plt.close(fig)
    print(f"wrote {out}")


def fig_reject_strategy_space():
    names = methodology_names()
    records = load_json("data/dataset/all_records_full.json")
    reject_ids = {r["paper_id"] for r in records if r.get("is_reject")}

    all_h = load_json("data/clustering/results/all_hierarchy.json")["papers"]
    full = Counter()
    for p in all_h:
        if p["paper_id"] in reject_ids:
            mid = p.get("primary_methodology") or "unclustered"
            full[mid] += 1

    rej_h = load_json("data/clustering/results/reject_hierarchy.json")["papers"]
    reject_only = Counter()
    for p in rej_h:
        if p.get("out_of_taxonomy"):
            reject_only["out_of_taxonomy"] += 1
        else:
            reject_only[p.get("primary_methodology") or "unclustered"] += 1

    mids = sorted(set(full) | set(reject_only), key=lambda m: reject_only[m], reverse=True)
    label_map = {**{m: short_name(n) for m, n in names.items()}, "unclustered": "Unclustered", "out_of_taxonomy": "Out-of-taxonomy"}
    labels = [label_map[m] for m in mids]
    y = np.arange(len(mids))

    fig, ax = plt.subplots(figsize=(9.7, 6.0))
    ax.scatter([full[m] for m in mids], y, s=38, color="#AEB6C2", edgecolor="white", zorder=3, label="Reject in full clustering")
    ax.scatter([reject_only[m] for m in mids], y, s=46, color=PURPLE, edgecolor="white", zorder=4, label="Reject-only clustering")
    for i, m in enumerate(mids):
        x1, x2 = full[m], reject_only[m]
        color = VERM if abs(x2 - x1) >= 20 else "#B8BDC6"
        ax.plot([x1, x2], [i, i], color=color, linewidth=1.3, alpha=0.95, zorder=2)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Reject papers mapped to each strategy operator")
    ax.grid(axis="x", color="#E5E7EB", linewidth=0.7)
    ax.legend(frameon=False, loc="lower right", fontsize=8)
    ax.set_title("Reject-only clustering recovers the same strategy vocabulary", loc="left", fontsize=11, fontweight="bold")
    ax.text(
        0.98,
        0.13,
        "22 / 23 reject-only clusters\nmap to existing patterns\n\n1 small adversarial-stealth\ncluster is out-of-taxonomy",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=8,
        color=DARK,
        bbox=dict(boxstyle="round,pad=0.35", facecolor="#FFFFFF", edgecolor="#D6DAE0", linewidth=0.8),
    )
    out = FIGS / "fig_reject_strategy_space.pdf"
    fig.savefig(out)
    plt.close(fig)
    print(f"wrote {out}")


def fig_skill_workflow():
    fig, ax = plt.subplots(figsize=(12.0, 5.9))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.text(0.02, 0.965, "NoveltySkill execution path", fontsize=13, fontweight="bold", ha="left", va="top")
    ax.text(
        0.02,
        0.91,
        "The skill does not write a paper; it produces one audit-cleared idea card or an explicit failure report.",
        fontsize=8.7,
        color=GRAY,
        ha="left",
    )

    phases = [
        ("Phase 0\nRetrieval", "DBLP / OpenAlex\nOpenReview / arXiv\nreal-retrieval sentinel", BLUE),
        ("Phase 1\nBottleneck", "closest adjacent\nwhere prior stopped\nOOD routing", GREEN),
        ("Phase 2\nCandidate", "pattern composition\n1 primary + 0-2 support\nsignature terms", PURPLE),
        ("Phase 3\nAudit", "reject scan\nanti-pattern check\npaper threat", VERM),
        ("Phase 4\nIdea card", "motivation\nmethod flow\nfalsification", GOLD),
    ]
    xs = [0.045, 0.235, 0.425, 0.615, 0.805]
    w, h, y = 0.145, 0.24, 0.57
    for i, (head, body, col) in enumerate(phases):
        rounded_box(ax, (xs[i], y), (w, h), f"{head}\n\n{body}", col + "18", ec=col, lw=1.2, fs=7.7, weight="bold" if i == 3 else "normal")
        if i < len(phases) - 1:
            arrow(ax, (xs[i] + w + 0.01, y + h / 2), (xs[i + 1] - 0.01, y + h / 2))

    # Audit internals.
    ax.text(0.555, 0.465, "Phase 3 hard floor", fontsize=8, fontweight="bold", color=VERM, ha="left")
    checks = [
        ("composition\nreject scan", "triggered -> abandon"),
        ("mitigation\nsubstance", "keyword-only -> revise/abandon"),
        ("paper-pointed\nthreat", "exact overlap -> abandon"),
    ]
    for j, (a, b) in enumerate(checks):
        rounded_box(ax, (0.535 + j * 0.097, 0.315), (0.086, 0.105), f"{a}\n{b}", "#FFFFFF", ec=VERM, lw=0.9, fs=5.45)
        arrow(ax, (0.688, 0.57), (0.578 + j * 0.097, 0.425), color=VERM, lw=0.8, rad=-0.08 + j * 0.08)

    # Validators.
    ax.text(0.815, 0.465, "Validators", fontsize=8, fontweight="bold", color=PURPLE, ha="left")
    rounded_box(ax, (0.823, 0.315), (0.068, 0.105), "kill-switch\nintegrity\nhard fail", "#FFFFFF", ec=PURPLE, lw=0.9, fs=5.05)
    rounded_box(ax, (0.906, 0.315), (0.068, 0.105), "expansion\ncomplete\nsoft warn", "#FFFFFF", ec=PURPLE, lw=0.9, fs=5.05)
    arrow(ax, (0.875, 0.57), (0.857, 0.425), color=PURPLE, lw=0.8, rad=0.08)
    arrow(ax, (0.875, 0.57), (0.94, 0.425), color=PURPLE, lw=0.8, rad=-0.08)

    # Outcomes.
    out_y = 0.075
    outcomes = [
        ("advance", "idea card\nPDF + Markdown + JSON", GREEN),
        ("revise", "named fields only\nkill-switch untouched", GOLD),
        ("abandon", "phase_3_failed\nuser-side fixes", VERM),
        ("do_not_generate", "direction OOD\nstructured diagnosis", GRAY),
    ]
    for i, (head, body, col) in enumerate(outcomes):
        rounded_box(ax, (0.12 + i * 0.205, out_y), (0.165, 0.105), f"{head}\n{body}", col + "17", ec=col, lw=0.95, fs=6.9)
    ax.text(0.02, 0.13, "Outcomes", fontsize=8, fontweight="bold", color=GRAY)
    out = FIGS / "fig_skill_workflow.pdf"
    fig.savefig(out)
    plt.close(fig)
    print(f"wrote {out}")


def fig_ablation_construct():
    variants = [
        ("OpenAI\nabstract fields", 47, 34.5, 0.474, "strategy-like", GREEN),
        ("OpenAI\nbase fields", 48, 28.0, 0.569, "topic-like", VERM),
        ("SPECTER2\nabstract fields", 37, 42.6, 0.400, "mixed / diffuse", GRAY),
    ]
    x = np.arange(len(variants))
    labels = [v[0] for v in variants]
    k = [v[1] for v in variants]
    noise = [v[2] for v in variants]
    sil = [v[3] for v in variants]
    chars = [v[4] for v in variants]
    colors = [v[5] for v in variants]

    fig, axes = plt.subplots(1, 3, figsize=(11.5, 3.8), gridspec_kw={"width_ratios": [1, 1, 1.25], "wspace": 0.38})
    ax = axes[0]
    ax.bar(x, sil, color=colors, width=0.62)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7.2)
    ax.set_ylabel("Silhouette")
    ax.set_ylim(0, 0.65)
    ax.grid(axis="y", color="#E5E7EB", linewidth=0.7)
    panel_label(ax, "a")
    ax.set_title("Metric alone", loc="left", fontsize=10.5, fontweight="bold")
    ax.annotate("highest,\nbut topic-like", xy=(1, sil[1]), xytext=(1.25, 0.61), arrowprops=dict(arrowstyle="-|>", color=VERM, lw=0.8), fontsize=7, color=VERM)

    ax = axes[1]
    ax.bar(x, noise, color=colors, width=0.62)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7.2)
    ax.set_ylabel("Unclustered (%)")
    ax.set_ylim(0, 50)
    ax.grid(axis="y", color="#E5E7EB", linewidth=0.7)
    panel_label(ax, "b")
    ax.set_title("Coverage pressure", loc="left", fontsize=10.5, fontweight="bold")
    for i, val in enumerate(k):
        ax.text(i, noise[i] + 1.4, f"k={val}", ha="center", fontsize=7, color=GRAY)

    ax = axes[2]
    ax.axis("off")
    panel_label(ax, "c")
    ax.set_title("Construct validity", loc="left", fontsize=10.5, fontweight="bold")
    for i, (lab, _, _, _, ch, col) in enumerate(variants):
        y = 0.78 - i * 0.25
        rounded_box(ax, (0.03, y), (0.34, 0.14), lab.replace("\n", " / "), col + "18", ec=col, lw=1.0, fs=7.1)
        ax.text(0.43, y + 0.07, ch, fontsize=8.5, va="center", ha="left", color=DARK, fontweight="bold" if i == 0 else "normal")
    ax.text(
        0.03,
        0.04,
        "The selected row is not the maximum-silhouette row.\nIt is the row whose cohesion is strategy-level rather than topic-level.",
        fontsize=8,
        color=GRAY,
        ha="left",
        va="bottom",
    )

    fig.suptitle("Ablation: the objective is strategy clustering, not silhouette maximization", x=0.01, ha="left", y=1.05, fontsize=12, fontweight="bold")
    out = FIGS / "fig_ablation_construct.pdf"
    fig.savefig(out)
    plt.close(fig)
    print(f"wrote {out}")


def main():
    fig_pipeline()
    fig_hierarchy_refined()
    fig_multilabel_combinations_refined()
    fig_reject_strategy_space()
    fig_skill_workflow()
    fig_ablation_construct()


if __name__ == "__main__":
    main()
