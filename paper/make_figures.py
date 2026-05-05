#!/usr/bin/env python3
"""Generate the 5 figures owned by paper/make_figures.py:
  paper/figures/{fig_pipeline,fig_umap_clusters,fig_umap_label,fig_methodology_bias,fig_temporal}.pdf
"""
import json
import sys
from pathlib import Path
from collections import defaultdict, Counter

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "paper"
FIGS = PAPER / "figures"
FIGS.mkdir(exist_ok=True)
DATA = ROOT / "data"
RES = DATA / "clustering" / "results"
EMB = DATA / "clustering" / "embeddings"

sys.path.insert(0, str(PAPER))
from figstyle import PALETTE, apply_style, despine, savefig_pdf  # noqa: E402

apply_style()


# ---------------------------------------------------------------------
# fig_pipeline — schematic of the data pipeline
# ---------------------------------------------------------------------
def fig_pipeline():
    fig, ax = plt.subplots(figsize=(13.0, 3.4))
    ax.set_xlim(0, 13)
    ax.set_ylim(0, 3.4)
    ax.axis("off")

    box_color = PALETTE.oral
    # Each box gets its own width tuned to the longest text line in it.
    # Header (bold) | body (8pt). Boxes spaced with 0.2 gap.
    entries = [
        ("Corpus",           "1947 papers\nICLR · ICML · NeurIPS\n2021–2025\n1014 Oral · 211 HC · 722 Reject", 2.05),
        ("Extraction",       "8 base fields (Sonnet)\n+ 4 abstract$_*$ fields\n(domain-agnostic rewrite)", 1.95),
        ("Embedding",        "OpenAI\ntext-embedding-3-large\n3072-dim · 4 abstract fields", 2.10),
        ("Cluster",          "UMAP + HDBSCAN\n47 innovation sub-patterns\nsilhouette 0.474\nunclustered 34.5%", 2.05),
        ("Pattern induction","Opus 4.7\n→ 13 innovation patterns\n(no preset taxonomy)", 1.95),
        ("Operational cards","13 × 8-panel\n47 × 6-panel\n(every claim cites paper_ids)", 1.95),
    ]
    gap = 0.20
    x = 0.10
    boxes = []
    h = 1.85
    y = 0.85
    for (title, body, w) in entries:
        boxes.append((x, y, w, h, title, body))
        x += w + gap

    for (bx, by, bw, bh, title, body) in boxes:
        ax.add_patch(FancyBboxPatch(
            (bx, by), bw, bh,
            boxstyle="round,pad=0.04,rounding_size=0.10",
            linewidth=0.9, edgecolor=box_color,
            facecolor=box_color + "12",
        ))
        ax.text(bx + bw / 2, by + bh - 0.30, title,
                ha="center", va="center", fontsize=9.5,
                fontweight="bold", color=PALETTE.oral)
        ax.text(bx + bw / 2, by + bh / 2 - 0.18, body,
                ha="center", va="center", fontsize=8.0,
                color=PALETTE.neutral, linespacing=1.35)

    for i in range(len(boxes) - 1):
        x1 = boxes[i][0] + boxes[i][2] + 0.02
        x2 = boxes[i + 1][0] - 0.02
        y_m = boxes[i][1] + boxes[i][3] / 2
        ax.add_patch(FancyArrowPatch(
            (x1, y_m), (x2, y_m),
            arrowstyle="->,head_width=3,head_length=5",
            color=PALETTE.neutral, linewidth=0.9,
        ))

    ax.text(6.5, 3.10, "NoveltySkill data pipeline",
            ha="center", va="center", fontsize=11.5, fontweight="bold",
            color=PALETTE.neutral)
    ax.text(6.5, 0.34,
            "every cluster → innovation pattern → card link is traceable to source paper_ids",
            ha="center", va="center", fontsize=8, color="#888", style="italic")

    out = FIGS / "fig_pipeline.pdf"
    savefig_pdf(fig, out)
    print(f"wrote {out}")


# ---------------------------------------------------------------------
# fig_umap_clusters — 47 sub-patterns scattered, plus unclustered
# ---------------------------------------------------------------------
def fig_umap_clusters():
    XY = np.load(RES / "all_umap2d.npy")
    assign = json.load(open(RES / "all_clusters.json"))
    ids_order = json.load(open(EMB / "ids.json"))
    pid2cid = {a["paper_id"]: a["cluster_id"] for a in assign["assignments"]}
    cids = np.array([pid2cid.get(pid, -1) for pid in ids_order])

    fig, ax = plt.subplots(figsize=(8.0, 6.0))
    # Unclustered first (gray, behind)
    mask_unc = cids == -1
    ax.scatter(XY[mask_unc, 0], XY[mask_unc, 1],
               s=4, c=PALETTE.unclustered, alpha=0.45, linewidths=0,
               label=f"unclustered (n={mask_unc.sum()})")
    real_cids = sorted(set(cids[~mask_unc].tolist()))
    palette = PALETTE.cat_long
    for i, cid in enumerate(real_cids):
        m = cids == cid
        ax.scatter(XY[m, 0], XY[m, 1], s=6, color=palette[i % len(palette)],
                   alpha=0.78, linewidths=0)
    ax.set_xlabel("UMAP-1")
    ax.set_ylabel("UMAP-2")
    ax.set_title(f"47 innovation sub-patterns (HDBSCAN, mcs=10) · n={len(ids_order)}")
    ax.legend(loc="lower right", fontsize=8, frameon=False)
    despine(ax)
    out = FIGS / "fig_umap_clusters.pdf"
    savefig_pdf(fig, out)
    print(f"wrote {out}")


# ---------------------------------------------------------------------
# fig_umap_label — UMAP colored by Oral / HC / Reject
# ---------------------------------------------------------------------
def fig_umap_label():
    XY = np.load(RES / "all_umap2d.npy")
    ids_order = json.load(open(EMB / "ids.json"))
    recs = json.load(open(DATA / "dataset" / "all_records_full.json"))
    by_id = {r["paper_id"]: r for r in recs}
    label = []
    for pid in ids_order:
        r = by_id[pid]
        if r["is_oral"]:
            label.append("Oral")
        elif r["is_hc"]:
            label.append("HC")
        elif r["is_reject"]:
            label.append("Reject")
        else:
            label.append("Other")
    label = np.array(label)

    fig, ax = plt.subplots(figsize=(8.0, 6.0))
    palette = {"Reject": PALETTE.reject, "HC": PALETTE.hc, "Oral": PALETTE.oral, "Other": PALETTE.unclustered}
    sizes = {"Reject": 6, "HC": 12, "Oral": 6, "Other": 3}
    alphas = {"Reject": 0.55, "HC": 0.92, "Oral": 0.55, "Other": 0.4}
    edge = {"Reject": "none", "HC": "white", "Oral": "none", "Other": "none"}
    edge_w = {"Reject": 0, "HC": 0.4, "Oral": 0, "Other": 0}
    # Draw order: Other → Reject → Oral → HC (HC on top with white outline)
    for d in ("Other", "Reject", "Oral", "HC"):
        m = label == d
        if m.sum() == 0:
            continue
        ax.scatter(XY[m, 0], XY[m, 1], s=sizes[d], color=palette[d],
                   alpha=alphas[d], linewidths=edge_w[d], edgecolors=edge[d],
                   label=f"{d} (n={m.sum()})")
    ax.set_xlabel("UMAP-1")
    ax.set_ylabel("UMAP-2")
    ax.set_title("Same UMAP, colored by acceptance class")
    ax.legend(loc="lower right", fontsize=9, frameon=False)
    despine(ax)
    out = FIGS / "fig_umap_label.pdf"
    savefig_pdf(fig, out)
    print(f"wrote {out}")


# ---------------------------------------------------------------------
# fig_methodology_bias — Δ_OR per innovation pattern (+ Δ_OH where HC≥5)
# ---------------------------------------------------------------------
def fig_methodology_bias():
    tax = json.load(open(RES / "methodologies.json"))["taxonomy"]
    hier = json.load(open(RES / "all_hierarchy.json"))["papers"]
    pid2prim = {h["paper_id"]: h["primary_methodology"] for h in hier}
    recs = json.load(open(DATA / "dataset" / "all_records_full.json"))

    cnt = defaultdict(lambda: {"oral": 0, "hc": 0, "reject": 0})
    for r in recs:
        pm = pid2prim.get(r["paper_id"])
        if not pm:
            continue
        if r["is_oral"]:
            cnt[pm]["oral"] += 1
        if r["is_hc"]:
            cnt[pm]["hc"] += 1
        if r["is_reject"]:
            cnt[pm]["reject"] += 1

    n_oral_total = sum(c["oral"] for c in cnt.values())
    n_hc_total = sum(c["hc"] for c in cnt.values())
    n_rej_total = sum(c["reject"] for c in cnt.values())

    rows = []
    for t in tax:
        c = cnt[t["id"]]
        share_o = c["oral"] / n_oral_total if n_oral_total else 0
        share_h = c["hc"] / n_hc_total if n_hc_total else 0
        share_r = c["reject"] / n_rej_total if n_rej_total else 0
        delta_or = share_o - share_r
        delta_oh = share_o - share_h if c["hc"] >= 5 else None
        rows.append((t["name"], delta_or, delta_oh, c))

    rows.sort(key=lambda x: x[1])
    names = [r[0] for r in rows]
    delta_or = np.array([r[1] for r in rows])
    delta_oh = [r[2] for r in rows]

    fig, ax = plt.subplots(figsize=(10, 5.4))
    y = np.arange(len(rows))
    colors = [PALETTE.oral if d > 0 else PALETTE.reject for d in delta_or]
    ax.barh(y, delta_or * 100, color=colors, height=0.62,
            edgecolor="white", linewidth=0.8)
    for i, d in enumerate(delta_oh):
        if d is None:
            continue
        ax.scatter([d * 100], [i], color=PALETTE.accent, marker="D", s=26,
                   zorder=5, edgecolor="white", linewidth=0.6)
    ax.axvline(0, color=PALETTE.neutral, linewidth=0.7)
    ax.set_yticks(y)
    ax.set_yticklabels(names)
    ax.set_xlabel("Share difference (percentage points)")
    ax.set_title(r"Acceptance bias per innovation pattern  ($\Delta_{OR}$ bars; $\Delta_{OH}$ diamonds where $n_{HC}\geq 5$)")
    h_or = mpatches.Patch(color=PALETTE.oral, label=r"$\Delta_{OR}>0$ (Oral-favored)")
    h_re = mpatches.Patch(color=PALETTE.reject, label=r"$\Delta_{OR}<0$ (Reject-favored)")
    h_oh = plt.Line2D([], [], marker="D", linestyle="", color=PALETTE.accent,
                      markeredgecolor="white", markeredgewidth=0.6,
                      label=r"$\Delta_{OH}$ (Oral$-$HC share)")
    ax.legend(handles=[h_or, h_re, h_oh], loc="lower right", frameon=False)
    despine(ax)
    out = FIGS / "fig_methodology_bias.pdf"
    savefig_pdf(fig, out)
    print(f"wrote {out}")


# ---------------------------------------------------------------------
# fig_temporal — temporal trends per innovation pattern (top-6 + bottom-7)
# ---------------------------------------------------------------------
def fig_temporal():
    tax = json.load(open(RES / "methodologies.json"))["taxonomy"]
    hier = json.load(open(RES / "all_hierarchy.json"))["papers"]
    pid2prim = {h["paper_id"]: h["primary_methodology"] for h in hier}
    recs = json.load(open(DATA / "dataset" / "all_records_full.json"))

    years = sorted(set(int(r["year"]) for r in recs))
    cnt = defaultdict(lambda: Counter())
    yr_total = Counter()
    for r in recs:
        pm = pid2prim.get(r["paper_id"])
        if not pm:
            continue
        cnt[pm][int(r["year"])] += 1
        yr_total[int(r["year"])] += 1

    sizes = [(t, sum(cnt[t["id"]].values())) for t in tax]
    sorted_tax = sorted(sizes, key=lambda x: -x[1])
    top6 = sorted_tax[:6]
    bottom7 = [t for t, _ in sorted_tax[6:]]

    fig, axes = plt.subplots(1, 2, figsize=(13.0, 4.8), sharey=False)

    def short(name, n=36):
        return name if len(name) <= n else name[: n - 1] + "…"

    # Top-6 panel
    ax = axes[0]
    for i, (t, _) in enumerate(top6):
        shares = [cnt[t["id"]].get(y, 0) / max(1, yr_total[y]) * 100 for y in years]
        ax.plot(years, shares, "-o", color=PALETTE.cat[i],
                linewidth=1.7, markersize=4, label=short(t["name"]))
    ax.set_xlabel("Year")
    ax.set_ylabel("Share of papers (%)")
    ax.set_title("Top-6 innovation patterns")
    ax.set_xticks(years)
    ax.legend(loc="upper left", fontsize=7.6, frameon=False, ncol=1)
    ax.grid(True, alpha=0.6, axis="y")
    despine(ax)

    # Bottom-7 panel
    ax = axes[1]
    for i, t in enumerate(bottom7):
        shares = [cnt[t["id"]].get(y, 0) / max(1, yr_total[y]) * 100 for y in years]
        ax.plot(years, shares, "-o", color=PALETTE.cat[(i + 6) % len(PALETTE.cat)],
                linewidth=1.5, markersize=3.6, label=short(t["name"]))
    ax.set_xlabel("Year")
    ax.set_ylabel("Share of papers (%)")
    ax.set_title("Remaining 7 innovation patterns")
    ax.set_xticks(years)
    ax.legend(loc="upper left", fontsize=7.6, frameon=False, ncol=1)
    ax.grid(True, alpha=0.6, axis="y")
    despine(ax)

    plt.tight_layout()
    out = FIGS / "fig_temporal.pdf"
    savefig_pdf(fig, out)
    print(f"wrote {out}")


if __name__ == "__main__":
    fig_pipeline()
    fig_umap_clusters()
    fig_umap_label()
    fig_methodology_bias()
    fig_temporal()
