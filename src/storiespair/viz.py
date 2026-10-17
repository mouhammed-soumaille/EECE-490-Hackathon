"""Shared chart style so every figure reads as one system."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from .data import find_repo_root

# Categorical slots in fixed order (validated colour-blind-safe order)
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
SERIES = [BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED]
GREY = "#9a9893"
INK, INK_2, SURFACE = "#0b0b0b", "#52514e", "#fcfcfb"
BLUES = "Blues"
DIVERGING = "RdBu_r"


def style():
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": "#d6d4ce", "axes.labelcolor": INK_2, "axes.titlecolor": INK,
        "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.titlepad": 12,
        "axes.labelsize": 10.5, "xtick.color": INK_2, "ytick.color": INK_2,
        "xtick.labelsize": 9.5, "ytick.labelsize": 9.5,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": "#ebe9e4", "grid.linewidth": 0.8, "axes.axisbelow": True,
        "axes.prop_cycle": plt.cycler(color=SERIES),
        "legend.frameon": False, "legend.fontsize": 9.5,
        "lines.linewidth": 2.0, "figure.dpi": 110, "savefig.dpi": 150, "savefig.bbox": "tight",
        "font.size": 10,
    })


def savefig(fig, name: str) -> Path:
    out = find_repo_root() / "outputs" / "figures"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.png"
    fig.savefig(path)
    return path


def savetable(df, name: str) -> Path:
    out = find_repo_root() / "outputs" / "tables"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.csv"
    df.to_csv(path, index=False)
    return path
