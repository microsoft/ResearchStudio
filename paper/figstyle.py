"""Central matplotlib style for all NoveltySkill paper figures.

Conventions:
  - PALETTE.{oral, hc, reject, unclustered}      canonical 4-class colors
  - PALETTE.cat                                  10-color categorical (Tableau-muted)
  - PALETTE.cat_long                             20-color categorical for hierarchy
  - PALETTE.diverging                            Oral-vs-Reject bias colormap (RdBu_r)
  - PALETTE.sequential                           single-hue sequential (cubehelix-light)
  - PALETTE.heatmap                              two-direction heatmap base (viridis)
  - apply_style()                                set rcParams (call at top of every script)
  - despine(ax)                                  remove top/right spines (matplotlib idiom)
  - savefig_pdf(fig, path)                       savefig with TrueType + bbox tight

All callers do:
    import sys; sys.path.insert(0, '<repo>/paper')
    from figstyle import apply_style, PALETTE, savefig_pdf
    apply_style()
"""
from __future__ import annotations
import matplotlib as mpl
import matplotlib.pyplot as plt
from types import SimpleNamespace


PALETTE = SimpleNamespace(
    # Canonical 4 — used wherever Oral / HC / Reject / unclustered appear.
    # Picked for accessibility (passes Okabe-Ito proximity checks at typical line-thickness)
    # and consistent semantic mapping with the report's \cblue / \cgold / \cred colors.
    oral="#3B6FB6",          # cool blue
    hc="#E1A33C",            # amber gold
    reject="#C04A4A",        # warm red
    unclustered="#B8B8B8",   # neutral gray (replaces "noise")
    # Auxiliaries
    accent="#6B4FA1",        # purple — sparingly, e.g. delta_OH diamond marker
    neutral="#4A4A4A",       # axis text / spines
    grid="#E5E5E5",
    # 10-class qualitative (Tableau-muted, for top-N methodology lines)
    cat=[
        "#3B6FB6", "#E1A33C", "#5C9E6E", "#C04A4A", "#6B4FA1",
        "#8B6F4E", "#D86FA0", "#7C7C7C", "#B5A93D", "#4FA0AE",
    ],
    # 20-class qualitative (for the 47 sub-patterns / hierarchy outer ring)
    cat_long=[
        "#3B6FB6", "#E1A33C", "#5C9E6E", "#C04A4A", "#6B4FA1",
        "#8B6F4E", "#D86FA0", "#B5A93D", "#4FA0AE", "#A95B98",
        "#7398CB", "#EDC077", "#88BFA0", "#D88080", "#9C85C0",
        "#B19982", "#E89AB8", "#CCC275", "#7FB7C2", "#C28CB7",
    ],
    diverging="RdBu_r",       # >0 blue (Oral-favored), <0 red (Reject-favored)
    sequential="cubehelix",   # for non-bias scalar fields
    heatmap="viridis",        # two-direction heatmap fallback
)


def apply_style() -> None:
    """Apply the project's master matplotlib rcParams."""
    mpl.rcParams.update({
        # Fonts — embedded TrueType so PDFs survive arXiv compilation
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans", "Helvetica", "Arial", "Liberation Sans"],
        "font.size": 9.0,
        "axes.titlesize": 10.0,
        "axes.labelsize": 9.0,
        "xtick.labelsize": 8.0,
        "ytick.labelsize": 8.0,
        "legend.fontsize": 8.0,
        "figure.titlesize": 10.5,
        # Spines / ticks — minimalist
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 0.7,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.direction": "out",
        "ytick.direction": "out",
        # Color
        "axes.edgecolor": PALETTE.neutral,
        "axes.labelcolor": PALETTE.neutral,
        "xtick.color": PALETTE.neutral,
        "ytick.color": PALETTE.neutral,
        "text.color": PALETTE.neutral,
        # Grid (only when ax.grid() is enabled)
        "grid.color": PALETTE.grid,
        "grid.linewidth": 0.5,
        "grid.linestyle": "-",
        # Misc
        "axes.prop_cycle": mpl.cycler(color=PALETTE.cat),
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.04,
        "figure.dpi": 110,
    })


def despine(ax, sides=("top", "right")) -> None:
    for s in sides:
        ax.spines[s].set_visible(False)


def savefig_pdf(fig, path) -> None:
    fig.savefig(path)
    plt.close(fig)
