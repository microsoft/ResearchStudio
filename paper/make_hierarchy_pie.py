#!/usr/bin/env python3
"""Nested-donut: 13 innovation patterns (inner) and 47 innovation sub-patterns (outer,
colored by parent pattern).

Output: paper/figures/fig_hierarchy_donut.pdf
"""
import json
import sys
from pathlib import Path
from collections import Counter, defaultdict

import numpy as np
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "clustering"
PAPER = ROOT / "paper"
FIGS = PAPER / "figures"

sys.path.insert(0, str(PAPER))
from figstyle import PALETTE, apply_style, savefig_pdf  # noqa: E402

apply_style()


def main():
    clusters = json.load((DATA / "results" / "all_clusters.json").open())
    hier = json.load((DATA / "results" / "all_hierarchy.json").open())
    tax = json.load((DATA / "results" / "methodologies.json").open())["taxonomy"]

    sizes = Counter(a["cluster_id"] for a in clusters["assignments"])
    c2m = {m["cluster_id"]: m["primary_methodology"] for m in hier["cluster_to_methodology"]}

    m2c = defaultdict(list)
    for cid, n in sizes.items():
        if cid == -1:
            continue
        m2c[c2m[cid]].append((cid, n))

    mids = sorted(m2c.keys(), key=lambda m: -sum(n for _, n in m2c[m]))
    mname = {t["id"]: t["name"] for t in tax}

    inner_sizes = [sum(n for _, n in m2c[m]) for m in mids]
    inner_total = sum(inner_sizes)

    outer_sizes, outer_labels, outer_parents = [], [], []
    for m in mids:
        for cid, n in sorted(m2c[m], key=lambda x: -x[1]):
            outer_sizes.append(n)
            outer_labels.append(f"C{cid:02d}")
            outer_parents.append(m)

    # Each pattern picks a base color from cat_long; sub-pattern slices share the
    # parent base lightened by sibling index for visual separation.
    base = PALETTE.cat_long[: len(mids)]
    m_color = dict(zip(mids, base))

    def hex_to_rgb(c):
        c = c.lstrip("#")
        return tuple(int(c[i : i + 2], 16) / 255 for i in (0, 2, 4))

    inner_colors = [m_color[m] for m in mids]
    outer_colors = []
    for m in mids:
        siblings = sorted(m2c[m], key=lambda x: -x[1])
        rgb = np.array(hex_to_rgb(m_color[m]))
        for j in range(len(siblings)):
            f = 0.55 + 0.40 * (1.0 - j / max(1, len(siblings) - 0.5))
            shade = rgb * f + (1 - f) * np.ones(3)
            outer_colors.append((*shade, 0.92))

    fig, ax = plt.subplots(figsize=(12.8, 8.4))

    wedges_o, _ = ax.pie(
        outer_sizes, radius=1.0,
        colors=outer_colors,
        wedgeprops=dict(width=0.32, edgecolor="white", linewidth=0.7),
        startangle=90, counterclock=False,
    )
    # Outer labels for sub-patterns with n>=30; placed OUTSIDE the ring with leader lines.
    for w, lab, n in zip(wedges_o, outer_labels, outer_sizes):
        if n < 30:
            continue
        a = (w.theta1 + w.theta2) / 2
        ang = np.deg2rad(a)
        # Anchor on the wedge edge
        xr, yr = np.cos(ang), np.sin(ang)
        x_in, y_in = 0.97 * xr, 0.97 * yr
        x_out, y_out = 1.10 * xr, 1.10 * yr
        ha = "left" if xr >= 0 else "right"
        ax.annotate(
            f"{lab} ({n})",
            xy=(x_in, y_in), xytext=(x_out, y_out),
            ha=ha, va="center", fontsize=7.6,
            color=PALETTE.neutral,
            arrowprops=dict(arrowstyle="-", color="#999", lw=0.5),
        )

    wedges_i, _ = ax.pie(
        inner_sizes, radius=0.66,
        colors=inner_colors,
        wedgeprops=dict(width=0.32, edgecolor="white", linewidth=1.2),
        startangle=90, counterclock=False,
    )
    # Inner labels — only paper count INSIDE the slice; full names go in legend.
    for w, m, n in zip(wedges_i, mids, inner_sizes):
        if n < 50:
            continue
        a = (w.theta1 + w.theta2) / 2
        ang = np.deg2rad(a)
        x_lab, y_lab = 0.50 * np.cos(ang), 0.50 * np.sin(ang)
        ax.text(x_lab, y_lab, f"{n}", ha="center", va="center",
                fontsize=10.5, fontweight="bold", color="white")

    # Legend on the right with full innovation-pattern names and (n, k clusters)
    handles = []
    for m in mids:
        n = sum(c for _, c in m2c[m])
        kc = len(m2c[m])
        plural = "s" if kc != 1 else ""
        handles.append((
            plt.Rectangle((0, 0), 1, 1, fc=m_color[m]),
            f"{mname[m]} (n={n}, {kc} sub-pattern{plural})",
        ))
    ax.legend(
        [h for h, _ in handles], [s for _, s in handles],
        loc="center left", bbox_to_anchor=(1.10, 0.5),
        fontsize=8, frameon=False,
        title="Innovation patterns (inner ring)", title_fontsize=9,
    )

    ax.set_title(
        f"Hierarchical paper distribution: 13 innovation patterns (inner) "
        f"and 47 innovation sub-patterns (outer)\n"
        f"Total clustered papers: {inner_total} (of 1947); slice = paper count",
        fontsize=10.5, pad=14,
    )

    out = FIGS / "fig_hierarchy_donut.pdf"
    savefig_pdf(fig, out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
