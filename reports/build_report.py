"""Build reports/Stories_Pair_Report.pdf from the notebooks' saved figures and tables.

Usage (from the repo root): python reports/build_report.py
Run the notebooks first; this script only lays out their outputs.
"""

from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "outputs" / "figures"
TAB = ROOT / "outputs" / "tables"
OUT = ROOT / "reports" / "Stories_Pair_Report.pdf"

TEAM = "Mouhammed Soumaille · Wassim Shams"

# ---------- fonts and styles ----------
F = "/usr/share/fonts/truetype"
for name, path in [("Body", f"{F}/crosextra/Carlito-Regular.ttf"), ("Body-B", f"{F}/crosextra/Carlito-Bold.ttf"),
                   ("Body-I", f"{F}/crosextra/Carlito-Italic.ttf"), ("Head", f"{F}/google-fonts/Poppins-Bold.ttf"),
                   ("Head-M", f"{F}/google-fonts/Poppins-Medium.ttf"), ("Mono", f"{F}/liberation/LiberationMono-Regular.ttf")]:
    pdfmetrics.registerFont(TTFont(name, path))
pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-B", italic="Body-I", boldItalic="Body-B")

INK, INK2, INK3 = colors.HexColor("#1c1b18"), colors.HexColor("#5d5a52"), colors.HexColor("#8b877c")
ACCENT, ACCENT_SOFT, LINE, PAPER = (colors.HexColor("#3f6b2f"), colors.HexColor("#e6eedf"),
                                     colors.HexColor("#e2dfd6"), colors.HexColor("#f6f5f1"))

st = {
    "h1": ParagraphStyle("h1", fontName="Head", fontSize=19, leading=24, textColor=INK, spaceBefore=4, spaceAfter=8),
    "h2": ParagraphStyle("h2", fontName="Head", fontSize=13, leading=17, textColor=INK, spaceBefore=12, spaceAfter=5),
    "eyebrow": ParagraphStyle("eb", fontName="Head-M", fontSize=8, leading=10, textColor=ACCENT, spaceAfter=2),
    "body": ParagraphStyle("body", fontName="Body", fontSize=10.5, leading=15, textColor=INK, spaceAfter=6, alignment=TA_LEFT),
    "lead": ParagraphStyle("lead", fontName="Body", fontSize=12.5, leading=18, textColor=INK, spaceAfter=8),
    "small": ParagraphStyle("small", fontName="Body", fontSize=8.8, leading=12, textColor=INK2, spaceAfter=4),
    "cap": ParagraphStyle("cap", fontName="Body-I", fontSize=8.8, leading=12, textColor=INK2, spaceAfter=10),
    "cell": ParagraphStyle("cell", fontName="Body", fontSize=9, leading=12, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Body-B", fontSize=9, leading=12, textColor=INK),
    "bullet": ParagraphStyle("bullet", fontName="Body", fontSize=10.5, leading=15, textColor=INK, leftIndent=12, bulletIndent=2, spaceAfter=3),
    "mono": ParagraphStyle("mono", fontName="Mono", fontSize=8.6, leading=12, textColor=INK, backColor=PAPER,
                           borderPadding=(6, 6, 6, 6), spaceBefore=4, spaceAfter=10),
}
W = A4[0] - 36 * mm


def P(t, s="body"):
    return Paragraph(t, st[s])


def bullets(items):
    return [Paragraph(t, st["bullet"], bulletText="•") for t in items]


def fig(name, caption, width=W, max_h=105 * mm):
    path = FIG / f"{name}.png"
    img = Image(str(path))
    ratio = img.imageHeight / img.imageWidth
    w = width
    h = w * ratio
    if h > max_h:
        h, w = max_h, max_h / ratio
    img.drawWidth, img.drawHeight = w, h
    return KeepTogether([img, Spacer(1, 3), P(caption, "cap")])


def table(rows, widths, header=True, zebra=True, align_right_from=None):
    data = [[Paragraph(str(c), st["cellb" if (header and i == 0) else "cell"]) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
             ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK), ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINE)]
    if zebra:
        for i in range(1, len(rows)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), PAPER))
    t.setStyle(TableStyle(style))
    return t


def callout(text):
    t = Table([[Paragraph(text, st["lead"])]], colWidths=[W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ACCENT_SOFT), ("LEFTPADDING", (0, 0), (-1, -1), 12),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 12), ("TOPPADDING", (0, 0), (-1, -1), 10),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("LINEBEFORE", (0, 0), (0, -1), 3, ACCENT)]))
    return t


def kpis(items):
    cells = [[Paragraph(f"<font name='Head' size='20' color='#3f6b2f'>{v}</font><br/><font size='8.8' color='#5d5a52'>{l}</font>", st["cell"]) for v, l in items]]
    t = Table(cells, colWidths=[W / len(items)] * len(items))
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PAPER), ("LINEAFTER", (0, 0), (-2, -1), 0.6, colors.white),
                           ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def on_page(c, doc):
    c.saveState()
    c.setFont("Body", 8)
    c.setFillColor(INK3)
    if doc.page > 1:
        c.drawString(18 * mm, 12 * mm, "Stories Pair · EECE 490 Hackathon · Stories Coffee")
        c.drawRightString(A4[0] - 18 * mm, 12 * mm, f"{doc.page}")
    c.restoreState()


def cover(c, doc):
    c.saveState()
    c.setFillColor(colors.HexColor("#1f2a1a"))
    c.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#8fbd6c"))
    c.setFont("Head-M", 10)
    c.drawString(22 * mm, A4[1] - 40 * mm, "EECE 490 HACKATHON · STORIES COFFEE")
    c.setFillColor(colors.white)
    c.setFont("Head", 40)
    c.drawString(22 * mm, A4[1] - 70 * mm, "Stories Pair")
    c.setFont("Body", 17)
    c.setFillColor(colors.HexColor("#e9efe3"))
    y = A4[1] - 86 * mm
    for line in ["Turning half-orders into profitable pairs,", "one till suggestion at a time."]:
        c.drawString(22 * mm, y, line)
        y -= 8 * mm
    c.setFont("Body", 11)
    c.setFillColor(colors.HexColor("#c9d4bf"))
    y = 92 * mm
    for line in ["Project report: data, models, decision engine, learning engine, value and pilot plan",
                 "Data: 51,177 product lines · 33,887 orders · Harbour, Garden, Uptown · Jan–Jun 2026",
                 f"Team: {TEAM}",
                 "Repository: github.com/mouhammed-soumaille/EECE-490-Hackathon"]:
        c.drawString(22 * mm, y, line)
        y -= 7 * mm
    # big number
    c.setFillColor(colors.HexColor("#8fbd6c"))
    c.setFont("Head", 64)
    c.drawRightString(A4[0] - 22 * mm, 140 * mm, "72%")
    c.setFont("Body", 11)
    c.setFillColor(colors.HexColor("#c9d4bf"))
    c.drawRightString(A4[0] - 22 * mm, 131 * mm, "of Stories orders are half a pair")
    c.restoreState()


def money(v):
    return f"${v:,.0f}"


def build():
    pol = pd.read_csv(TAB / "05_policy_comparison.csv")
    mc = pd.read_csv(TAB / "05_monte_carlo.csv").annual_incremental_gp
    yr = pd.read_csv(TAB / "07_year_profit_by_policy.csv")
    lc = pd.read_csv(TAB / "07_learning_curve_share_of_oracle.csv").set_index("policy")
    att = pd.read_csv(TAB / "03_attach_model_benchmark.csv")
    cho = pd.read_csv(TAB / "03_category_model_benchmark.csv")
    bench = pd.read_csv(TAB / "02_next_item_benchmark.csv")
    pilot = pd.read_csv(TAB / "05_pilot_power.csv")
    pb = pd.read_csv(ROOT / "outputs" / "playbook.csv")
    g = lambda key: float(pol.loc[pol.key == key, "annual_incremental_gp"].iloc[0])
    v1, pop, combo, hm = g("stories_pair"), g("most_popular"), g("fixed_combo_10"), g("highest_margin")
    combo_disc = float(pol.loc[pol.key == "fixed_combo_10", "annual_discount_given"].iloc[0])
    p10, p50, p90 = mc.quantile([0.1, 0.5, 0.9])
    yv = yr.set_index("policy")
    v2y, v1y = yv.loc["Stories Pair v2 (learning)", "mean"], yv.loc["Stories Pair v1 (assumption only)", "mean"]

    s = [Spacer(1, 1), PageBreak()]

    # ---------------- 1. Executive summary ----------------
    s += [P("SUMMARY", "eyebrow"), P("The opportunity in one page", "h1")]
    s += [callout(
        "<b>72% of Stories' orders contain only a drink or only food.</b> Stories Pair is a till engine that, when the first "
        "item is rung, suggests the item from the other side of the pair with the highest <i>expected extra gross profit</i> "
        "at that branch, net of customers who would have bought it anyway. It is built only on what the data supports, "
        "starts as a 135-row lookup table any POS can use, and then learns from every accept and decline.")]
    s += [Spacer(1, 8), kpis([("72%", "of orders are half a pair<br/>(measured)"), (f"${v1/1000:.0f}k", "extra gross profit a year,<br/>base case (estimate)"),
                              (f"+{(v2y / v1y - 1) * 100:.0f}%", "more with the learning<br/>engine (simulation)"),
                              ("$0", "discount given away<br/>at base assumptions")]), Spacer(1, 10)]
    s += bullets([
        "<b>What the data supports.</b> Classic market-basket analysis finds no significant product pairs. Among orders that "
        "do pair, the <i>category</i> of the add-on is strongly predictable from the first item: a matcha or tea rung first is "
        "followed by bakery 78% of the time; a sandwich or meal by a cold drink 41% of the time (cold drinks are 18% of drink lines).",
        "<b>What it does not support.</b> Product-level pairs, personal preferences behind loyalty IDs, and context-heavy "
        "machine learning all fail held-out tests. Discounted drinks were not associated with more pairing (an observational result).",
        f"<b>Value.</b> At base assumptions Stories Pair adds about {money(v1)} of gross profit a year (P10–P90 "
        f"{money(p10)}–{money(p90)}), 15% more than suggesting the best-seller and 37% more than a classic 10% combo, which would "
        f"also hand out {money(combo_disc)} a year in discounts.",
        f"<b>Learning.</b> The v2 engine (Thompson-sampling bandit) earns about {money(v2y)} vs {money(v1y)} for v1 in its first "
        "year across 30 simulated customer truths, and beats the best-seller rule and classic combo in all of them.",
        "<b>Next step.</b> Two weeks of accept/decline logging, then a six-week odd/even receipt A/B test, measure the one "
        "number history cannot: how often customers accept.",
    ])
    s += [PageBreak()]

    # ---------------- 2. Problem and data ----------------
    s += [P("1 · PROBLEM AND DATA", "eyebrow"), P("Most orders stop at one item", "h1")]
    s += [P("The file has one row per product line: 51,177 lines forming 33,887 orders at three branches between 1 January "
            "and 30 June 2026. Before analysis we ran a data contract: line revenue and gross profit reconcile exactly (0 "
            "mismatches), each Transaction ID belongs to one branch, timestamp, customer and order type, and every product "
            "has one price and one cost per branch. 132 repeated lines (0.26%) were kept; removing them does not change the "
            "order mix.")]
    s += [fig("00_order_mix", "Figure 1. Order composition. 40.9% drink-only, 30.9% food-only, 28.2% both.", max_h=45 * mm)]
    s += [P("What counts as an order", "h2"),
          P("We tested merging receipts that share a branch and the exact second (a group paying separately). There are 30 "
            "such collisions, close to the ~21 expected by pure chance, and the same customer appears twice at a branch on "
            "the same day in under 1% of customer-days. We keep the Transaction ID as the order. We treat the first line of "
            "an order as the item rung first; the export does not record ring order, but section 2 shows the add-on is associated "
            "more strongly with the first line than in the pooled view, which is what an anchor item would produce."),
          P("From the till's point of view, when a drink is rung first only 25.6% of orders go on to include food; when a "
            "food is rung first, 31.4% go on to include a drink. The remaining 69–74% are the audience for a suggestion.")]
    s += [PageBreak()]

    # ---------------- 3. Evidence ----------------
    s += [P("2 · WHAT THE DATA SUPPORTS", "eyebrow"), P("Pairs live at the category level", "h1")]
    s += [P("<b>Whether</b> an order pairs barely moves with branch, hour, weekday, order type or loyalty (Cramér's V ≤ 0.03); "
            "it moves with what is rung first (V 0.08–0.18). Rates are flat month to month (25–27% drink-first).")]
    s += [fig("01_paired_rate_by_first_category", "Figure 2. Share of orders that end up paired, by the first item's category (95% CI).", max_h=78 * mm)]
    s += [P("<b>Which</b> category is added varies strongly with the first item. Daypart, branch and order type are "
            "statistically significant but weak.")]
    s += [fig("01_what_gets_added", "Figure 3. Among orders that paired: the category added, by the first item's category, in each direction.", max_h=72 * mm)]
    s += [P("Below the category, nothing", "h2"),
          P("Across all orders no drink × food product pair is significant after a Benjamini–Hochberg correction (0 of 506), "
            "and even every category lift is at or below 1, because most orders are single-sided. Restricting to orders that "
            "pair reveals strong category pairs (cold drinks with sandwiches, lift 1.8; with meals, 1.7; matcha/tea with "
            "bakery, 1.2; all q < 0.001). Some product pairs look significant there too, but every one sits inside a "
            "significant category pair, and none of 20 within-category tests survives a Bonferroni correction: once the "
            "categories are known, the specific drink says nothing about the specific food.")]
    s += [fig("02_product_pairs_volcano", "Figure 4. Classic market basket over all orders: no product pair clears the multiple-testing bar.", max_h=62 * mm)]
    s += [P("Loyalty IDs carry no personal preference", "h2"),
          P("3,494 IDs appear a median of 6 times; 94% appear at more than one branch. A returning customer repeats their "
            "previous food choice 5.0% of the time against 5.2% expected by chance (z = −0.85). Personalisation would add "
            "privacy exposure and complexity for no measurable gain, so we rejected it.")]
    b = bench.set_index("predictor")
    s += [P("Held-out benchmark: which method predicts the add-on?", "h2"),
          table([["Predictor (trained Jan–May, tested on June)", "hit@1", "hit@3", "log loss"]] +
                [[i, f"{r['hit@1']:.3f}", f"{r['hit@3']:.3f}", f"{r['log_loss']:.3f}"] for i, r in b.iterrows()],
                [W * 0.55, W * 0.15, W * 0.15, W * 0.15]),
          P("Product association rules are no better than plain popularity on unseen orders. The category-aware structure "
            "gives the best probabilities (lowest log loss), which is what the engine multiplies by profit.", "small")]
    s += [PageBreak()]

    # ---------------- 4. Models ----------------
    s += [P("3 · MODELS VS BASELINES", "eyebrow"), P("Simple wins when it ties", "h1")]
    s += [P("The engine needs two measured probabilities when the first item is rung: <b>Q</b>, the chance the order pairs "
            "anyway, and the chance each category is added if it does. Protocol: train January–April, choose on May, refit "
            "January–May, report June, which no decision touched.")]
    s += [table([["Model for Q (will the order pair?)", "May AUC", "June AUC", "June log loss"]] +
                [[r.model, f"{r['valid_auc (May)']:.3f}", f"{r['test_auc (June)']:.3f}", f"{r.test_log_loss:.4f}"] for _, r in att.iterrows()],
                [W * 0.52, W * 0.16, W * 0.16, W * 0.16])]
    s += [Spacer(1, 6), P("A paired bootstrap on June shows logistic regression is no better than the one-line baseline "
                          "(AUC difference −0.004, 95% CI −0.009 to +0.001) and gradient boosting is worse (−0.010, CI −0.017 "
                          "to −0.005). <b>The engine uses the baseline</b>: same accuracy, nothing to maintain.")]
    s += [fig("03_attach_calibration_lift", "Figure 5. The chosen model is calibrated on unseen June orders and separates them modestly.", max_h=62 * mm)]
    c1 = cho[cho.direction == "drink"]
    s += [table([["Category model, drink rung first", "May log loss", "June log loss", "vs global"]] +
                [[r.model, f"{r['valid_log_loss (May)']:.4f}", f"{r['test_log_loss (June)']:.4f}", f"{r.log_loss_improvement_vs_global:+.1%}"] for _, r in c1.iterrows()],
                [W * 0.52, W * 0.16, W * 0.16, W * 0.16]),
          P("Selection rule fixed before looking at June: best May log loss, simplest model within 0.5%. "
            "\"Shares by first-item category\" wins in both directions. Daypart is statistically significant (p < 1e-30) yet "
            "does not improve prediction on unseen months: significance is not usefulness.", "small")]
    s += [PageBreak()]

    # ---------------- 5. Engine ----------------
    s += [P("4 · THE DECISION ENGINE", "eyebrow"), P("Score profit, not popularity", "h1")]
    s += [fig("08_how_it_works", "Figure 6. How Stories Pair works end to end.", max_h=62 * mm)]
    s += [P("For each candidate add-on <i>i</i> and discount <i>d</i> (0, 5, 10 or 15%), the engine computes:"),
          Paragraph("gain = (1 − Q) · a<sub>i</sub>(d) · gp<sub>i</sub>(d)   new sales from people who would not have added anything<br/>"
                    "     − Q · s<sub>i</sub> · (p<sub>i</sub> − p<sub>i</sub>(d))   discount handed to people who would buy i anyway<br/>"
                    "     + w · Q · (1 − s<sub>i</sub>) · (gp<sub>i</sub>(d) − gp<sub>other</sub>)   people who switch to the suggestion", st["mono"]),
          P("Q, s<sub>i</sub>, prices and costs are measured. Acceptance a<sub>i</sub>(d) is assumed in v1 (6% for an "
            "average-appeal item, proportional to how often the item is chosen organically, +10% per 10% off) and learned in "
            "v2. Guardrails: discount ≤ 15% (the deepest in Stories' data), ≥ 40% margin after discount, the add-on costs at "
            "most 2.5× the first item, no suggestion worth under $0.05, never repeat a declined offer.")]
    s += [P("What the engine decides", "h2")]
    s += bullets([
        "<b>No discounts at base assumptions.</b> Discounting pays only if 10% off raises acceptance by about a quarter or "
        "more. The data shows none: when the first drink was discounted, pairing was 25.1% vs 25.7% at full price (p = 0.65). "
        "The naive comparison (34% vs 25%) is a counting artifact of bigger orders.",
        "<b>Branch-aware.</b> Garden pays 1.43× Harbour's unit cost on all 45 products. At Garden, iced coffees and cold "
        "drinks are paired with an Egg Sandwich; at Harbour and Uptown with a Chicken Pesto Sandwich, which earns $3.36 a "
        "unit at Garden vs $6.12 at Harbour.",
        "<b>A 135-row playbook.</b> The chosen models depend only on branch and first item, so the whole v1 engine compiles "
        "to a lookup table (outputs/playbook.csv) a POS can load on day one.",
    ])
    ex = (pb[pb.branch == "Harbour"].sort_values("expected_gain_per_order", ascending=False)
          .drop_duplicates("first_category").head(8))
    s += [KeepTogether([table([["First item (Harbour)", "Suggest", "Pair total", "Pairs anyway", "Expected gain"]] +
                [[r.first_item, r.suggest, f"${r.pair_total:.2f}", f"{r.Q_pairs_anyway:.0%}", f"${r.expected_gain_per_order:.2f}"] for _, r in ex.iterrows()],
                [W * 0.28, W * 0.28, W * 0.14, W * 0.14, W * 0.16]),
          P("Excerpt from the playbook: the best suggestion for one item of each category at Harbour.", "cap")])]
    s += [PageBreak()]

    # ---------------- 6. Value ----------------
    s += [P("5 · VALUE (ESTIMATES)", "eyebrow"), P("What it is worth, and what could change it", "h1")]
    s += [P("The engine was trained on January–May and replayed on all 6,906 June orders it never saw; every policy is scored "
            "with the same acceptance model, then scaled to a year using the six-month average volume (68,336 orders).")]
    s += [table([["Policy", "Extra gross profit / yr", "Discount given / yr", "Gain per suggestion"]] +
                [[r.policy, money(r.annual_incremental_gp), money(r.annual_discount_given), f"${r.gain_per_offer:.2f}"]
                 for _, r in pol.sort_values("annual_incremental_gp", ascending=False).drop_duplicates("annual_incremental_gp").iterrows()],
                [W * 0.46, W * 0.2, W * 0.18, W * 0.16])]
    s += [Spacer(1, 6), fig("05_acceptance_curve", "Figure 7. Value scales with acceptance; each percentage point is worth about $2,650 a year.", max_h=70 * mm)]
    s += [fig("05_uncertainty", f"Figure 8. Varying every assumption at once: P10 {money(p10)}, median {money(p50)}, P90 {money(p90)}; no draw loses money. Acceptance is the dominant driver.", max_h=62 * mm)]
    s += [PageBreak()]

    # ---------------- 6b. Costs, assumptions, decision rules ----------------
    costs = pd.read_csv(TAB / "05_costs.csv")
    flips = pd.read_csv(TAB / "05_decision_flips.csv")
    base_c = costs[costs["staff-cost case"] == "base"].iloc[0]
    s += [P("5b · COSTS AND DECISIONS", "eyebrow"), P("What it costs, and what would change our advice", "h1")]
    s += [P(f"Staff time is the only running cost we can estimate: about {base_c['staff hours / yr']:.0f} hours a year "
            f"({money(base_c['staff cost / yr'])} at an assumed $4 an hour and 5 seconds a suggestion; "
            f"{money(costs['staff cost / yr'].min())}–{money(costs['staff cost / yr'].max())} across the ranges), leaving about "
            f"{money(base_c['net gain / yr (base acceptance)'])} a year of net gain. POS integration cost is unknown; at that net "
            "gain, a $1k, $3k, $5k or $10k integration pays back in about 0.7, 2.2, 3.6 or 7.3 months.")]
    s += [table([["Assumption", "Base (range)", "Effect on the answer"],
                 ["Acceptance of an average suggestion", "6% (3–12%)", "Largest: each point ≈ $2,650 / yr; $8.9k at 3%, $33.1k at 12%"],
                 ["Extra acceptance per 10% off", "+10% (0–50%)", "Decides whether discounts are used; flips at ~+25%"],
                 ["Organic buyers who switch", "10% (0–25%)", "$16.3k–$18.7k / yr"],
                 ["Orders where staff make the suggestion", "80% (50–100%)", "$10.5k–$21.0k / yr"],
                 ["First line = item rung first", "–", "Supported by the line-order evidence; category pairs hold either way"],
                 ["Staff time and wage", "5 s, $4/h (3–8 s, $2.5–6/h)", "$114–$729 / yr"]],
                [W * 0.36, W * 0.22, W * 0.42])]
    s += [P("What would change the recommendation", "h2"),
          table([["Recommendation", "Changes if", "How we will know"]] +
                [[r.recommendation, r["changes if"], r["how we will know"]] for _, r in flips.iterrows()],
                [W * 0.24, W * 0.52, W * 0.24])]
    s += [P("Tradeoffs we cannot price", "h2")]
    s += bullets([
        "Customer annoyance: limited by one suggestion per order, none on a complete pair, no repeat after a decline, and "
        "staff may skip. The pilot tracks declines and complaints.",
        "Demand concentrates on a few items (Butter Croissant, Egg Sandwich, Iced Latte); stock and waste are not in the data.",
        "Missing information: suggestion logs, POS ring order, labour cost, waste and stock, integration cost, complaints, "
        "and the reason for Garden's unit costs.",
    ])
    s += [PageBreak()]

    # ---------------- 7. Learning engine ----------------
    s += [P("6 · STORIES PAIR v2", "eyebrow"), P("An engine that learns at the till", "h1")]
    s += [P("v2 replaces the acceptance assumption with a Thompson-sampling bandit. Each arm (first-item category, suggested "
            "item, discount) keeps a Beta belief about its take rate, warm-started at v1's estimate with the weight of 30 "
            "suggestions. For each order the engine draws from every allowed arm's belief, values the draw with that branch's "
            "economics, and suggests the best draw; each night the day's accepts and declines update the beliefs. Acceptance "
            "is learned jointly across branches because behaviour does not differ by branch; profit always uses each branch's "
            "own prices and costs.")]
    s += [P("We tested it against 30 simulated truths drawn from the assumption ranges, each with item-level deviations of "
            "about ±60% from v1's \"acceptance follows popularity\" rule, over a year of orders resampled from real April–June "
            "orders, against an oracle that knows the truth.")]
    s += [fig("07_learning_curve", "Figure 9. Share of the oracle's profit captured, averaged over 30 truths.", max_h=58 * mm)]
    s += [table([["Policy (first year, 80% of orders shown a suggestion)", "Mean", "P10", "P90", "v2 wins in"]] +
                [[r.policy, money(r["mean"]), money(r.P10), money(r.P90),
                  "–" if pd.isna(r["v2 beats it in % of truths"]) else f"{r['v2 beats it in % of truths']:.0f}% of truths"] for _, r in yr.iterrows()],
                [W * 0.42, W * 0.13, W * 0.13, W * 0.13, W * 0.19])]
    wk = lc.loc["Stories Pair v2 (learning)"]
    s += [Spacer(1, 6), P(f"v2 pays a short exploration cost (51% of the oracle in week 1 vs 64% for v1), overtakes v1 by "
                          f"week 3, and reaches {wk['week 52']:.0f}% of the oracle by week 52; v1 never moves. Its discount use "
                          "rises with the true discount effect (r = 0.72) without being told. These figures span the whole "
                          "assumption range, so compare policies within this table rather than with section 5.")]
    s += [fig("07_discount_discovery", "Figure 10. v2 learns how much discounting pays in each simulated truth.", width=W * 0.62, max_h=50 * mm)]
    s += [PageBreak()]

    # ---------------- 8. Product ----------------
    s += [P("7 · PRODUCT", "eyebrow"), P("From notebook to till", "h1")]
    s += bullets([
        "<b>Till app</b> (app/index.html): a browser till with no server. Staff ring the first item, see the suggested pairing "
        "with its price and a one-line script, and tap accept or decline. A staff-only panel shows the options the engine "
        "scored, the chance the order pairs anyway, and the engine's live belief about the suggestion. A second tab runs a "
        "four-week simulated service of v2 against v1 and a classic combo. Its JavaScript engine reproduces the Python "
        "engine's decisions exactly.",
        "<b>Colab demo</b> (notebook 06): the same flow as a Gradio app with a public link for presentations.",
        "<b>Integration path.</b> Day one: load outputs/playbook.csv into the POS as a lookup. With the pilot: log accept/"
        "decline per suggestion. With v2: a nightly job updates two counts per arm and republishes the table; the till "
        "does one random draw per arm. No GPU, no retraining, no customer data.",
        "<b>Business-editable.</b> Assumptions, guardrails and category compatibility live in config/*.json, so Stories can "
        "change a rule without touching code.",
    ])
    s += [P("Pilot plan and decision rules", "h2")]
    s += bullets([
        "<b>Step 1 · Acceptance logging, 2 weeks, all branches.</b> About 2,200 suggestions estimate a ~6% acceptance rate to "
        "within ±1 point. If acceptance is below ~2%, stop.",
        "<b>Step 2 · Odd/even receipt A/B test, 6 weeks.</b> Even Transaction IDs get the suggestion, odd ones do not. "
        "Primary metric: gross profit per order; secondary: pairing rate, acceptance, discount spend, complaints.",
        "<b>Step 3 · Switch on v2</b> on the logged data; test a discounted variant on one branch only if step 2 succeeds.",
    ])
    s += [table([["Detectable gain per order", "Orders per arm", "Days, all branches", "Days, Harbour only"]] +
                [[f"${r.detectable_gain_per_order_usd:.2f}", f"{int(r.orders_per_arm):,}", f"{int(r.all_branches_days)}", f"{int(r.Harbour_only_days)}"] for _, r in pilot.iterrows()],
                [W * 0.28, W * 0.24, W * 0.24, W * 0.24]),
          P("80% power, 5% significance, order-level gross-profit SD $2.79. The base case predicts $0.25 per order.", "cap")]
    s += [PageBreak()]

    # ---------------- 9. Rigor ----------------
    s += [P("8 · RIGOUR", "eyebrow"), P("Measured, estimated, rejected", "h1")]
    s += [table([["Statement", "Status"],
                 ["72% of orders are single-sided", "Measured"],
                 ["Pairing varies with the first item's category, not with branch, hour or order type", "Measured (tested, held-out)"],
                 ["Which category is added varies with the first item's category", "Measured (tested, held-out)"],
                 ["No product-level pairing beyond the category", "Measured (multiple-testing corrected)"],
                 ["Loyalty IDs show no personal preference", "Measured"],
                 ["Garden unit costs are 1.43× Harbour on all 45 products", "Measured"],
                 ["A discounted first drink was not associated with more pairing", "Measured (observational)"],
                 ["The first line of an order is the item rung first", "Assumed (supported by evidence)"],
                 ["Acceptance 6%, switching 10%, staff compliance 80%, +10% per 10% off", "Assumed (pilot measures)"],
                 [f"~{money(v1)}/yr (P10–P90 {money(p10)}–{money(p90)})", "Estimated"],
                 ["v2 +27% over v1 in year one", "Simulated"]],
                [W * 0.68, W * 0.32])]
    s += [P("Approaches we rejected", "h2")]
    s += [table([["Approach", "Why not"],
                 ["Product-level market basket / association rules", "No significant pairs; no better than popularity on June data"],
                 ["Customer-level personalisation", "No personal preference behind loyalty IDs; privacy cost"],
                 ["Gradient boosting / context-heavy ML for Q", "Ties or loses to a one-line baseline on unseen months"],
                 ["Blanket combo discounts", "Costs more margin than the small extra uptake it buys; no association between discounts and pairing in the data"],
                 ["Merging same-second receipts", "Collisions at chance level"],
                 ["\"Breakfast only before noon\" rule", "56% of breakfast items sell after 3 pm"]],
                [W * 0.42, W * 0.58])]
    s += [P("Limitations", "h2")]
    s += bullets([
        "Acceptance is the dominant unknown; every value figure scales with it. The pilot exists to measure it.",
        "Ring order is inferred, not recorded. Discount evidence is observational, and a discount shown upfront on an add-on "
        "is a different intervention.",
        "Six months of data: no full-year seasonality check. Gross profit is not net profit (no labour, waste or integration cost).",
        "The bandit simulation shares our model's structure; real customers may show effects it does not cover, such as "
        "suggestion fatigue or staff tone.",
        "Garden's cost gap is unexplained (supplier terms, recipe, waste or allocation). Bringing it to Harbour's unit costs "
        "would be worth up to ~$32k a year on its own, an upper bound.",
    ])
    s += [P("Reproducibility", "h2"),
          P("Every number in this report comes from the notebooks in the repository (00–07), which run top to bottom in Google "
            "Colab and are committed with their outputs. Shared code lives in src/storiespair; this report is rebuilt with "
            "python reports/build_report.py.", "small")]

    doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=18 * mm, title="Stories Pair — Project Report", author=TEAM.replace("‹", "").replace("›", ""))
    doc.build(s, onFirstPage=cover, onLaterPages=on_page)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    build()
