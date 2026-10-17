"""Draw the Stories Pair system diagram used in the report and the deck."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

from storiespair import viz  # noqa: E402

viz.style()
fig, ax = plt.subplots(figsize=(12, 5.0))
ax.set_xlim(0, 12); ax.set_ylim(0, 5.0); ax.axis("off")

def box(x, y, w, h, title, body, fill, edge, tcolor=viz.INK):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12", fc=fill, ec=edge, lw=1.4))
    ax.text(x + 0.18, y + h - 0.32, title, fontsize=11.5, fontweight="bold", color=tcolor, va="top")
    ax.text(x + 0.18, y + h - 0.72, body, fontsize=9.2, color=viz.INK_2, va="top", linespacing=1.45)

def arrow(x1, y1, x2, y2, label=None, ly=0.18, rad=0.0):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=14, lw=1.4, color=viz.INK_2,
                                 connectionstyle=f"arc3,rad={rad}"))
    if label:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + ly, label, ha="center", fontsize=8.8, color=viz.INK_2)

box(0.1, 2.3, 2.6, 2.55, "Transaction history", "33,887 orders, 3 branches\nrefit monthly\n\nmeasures who pairs, with\nwhich category, and what\neach item earns per branch", "#f1efe9", "#cfcabd")
box(3.3, 2.3, 2.9, 2.55, "Pair engine", "scores every add-on and\ndiscount by expected extra\ngross profit at this branch,\nnet of people who buy\nanyway; guardrails apply", "#e6eedf", viz.GREEN)
box(6.8, 2.3, 2.4, 2.55, "Till", "first item rung\n→ one suggestion\n(or none)\n\nstaff tap accept\nor decline", "#eef4fc", viz.BLUE)
box(9.8, 2.3, 2.1, 2.55, "Result", "extra items sold,\nmostly at full\nprice\n\n~$17k / yr (v1,\nbase case);\nv2 learning: +27%", "#fdf0e6", viz.ORANGE)
box(3.3, 0.1, 5.9, 1.55, "Learning loop (v2)", "each night: add the day's accepts and declines to a Beta belief per\n(category, item, discount); tomorrow's suggestions use the updated\nbeliefs (Thompson sampling). No retraining, no customer data.", "#f4f3ef", "#cfcabd")

arrow(2.7, 3.6, 3.3, 3.6, "priors")
arrow(6.2, 3.6, 6.8, 3.6, "table")
arrow(9.2, 3.6, 9.8, 3.6)
arrow(8.0, 2.3, 8.0, 1.65)
ax.text(8.12, 1.95, "accept / decline log", fontsize=8.8, color=viz.INK_2)
arrow(4.6, 1.65, 4.6, 2.3)
ax.text(4.72, 1.95, "updated beliefs", fontsize=8.8, color=viz.INK_2)
fig.savefig(ROOT / "outputs" / "figures" / "08_how_it_works.png")
print("saved outputs/figures/08_how_it_works.png")
