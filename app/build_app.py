"""Export the engine's measured parameters and build the standalone till app.

Usage (from the repo root):  python app/build_app.py
Writes app/engine_params.json and app/index.html (template.html + parameters).
The app re-implements the engine formula in JavaScript, so it runs in any
browser with no server.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from storiespair import data, engine as E, models  # noqa: E402


def build():
    lines = data.load_lines(ROOT / "data" / "stories_transactions.csv")
    orders = data.build_orders(lines)
    added = data.other_side_first_item(lines, orders)
    ue = data.unit_economics(lines)
    cfg = E.load_config(ROOT)
    pm = models.PairModels.fit(orders, lines, added)
    eng = E.PairEngine(pm, ue, cfg["compatibility"], E.Assumptions.from_config(cfg), E.Guardrails.from_config(cfg))

    items = []
    for side in ["drink", "food"]:
        for p in eng.items[side]:
            items.append({"name": p, "cat": eng.cat_of[p], "side": side,
                          "price": {b: round(float(eng.price_tbl.loc[b, p]), 2) for b in eng.price_tbl.index},
                          "cost": {b: round(float(eng.cost_tbl.loc[b, p]), 2) for b in eng.cost_tbl.index},
                          "units": int(ue[ue["product"] == p].units.sum())})

    by_cat = {}
    for cat in data.DRINK_CATEGORIES + data.FOOD_CATEGORIES:
        rep = ue[(ue.category == cat)].groupby("product").units.sum().idxmax()
        ctx = eng.context("Harbour", "2026-06-03 13:00", rep)
        target = "food" if cat in data.DRINK_CATEGORIES else "drink"
        its, Q, s, *_ = eng.prepare(ctx, target)
        by_cat[cat] = {"Q": round(float(Q[0]), 4), "s": {i: round(float(v), 5) for i, v in zip(its, s[0])}}

    a = cfg["assumptions"]
    params = {
        "items": items,
        "byCat": by_cat,
        "assumptions": {k: a[k]["base"] for k in ["base_acceptance", "discount_lift_per_10pct", "switch_rate", "offer_rate"]},
        "guardrails": {k: cfg["guardrails"][k] for k in ["discount_grid", "min_margin_after_discount", "min_expected_gain_usd",
                                                          "price_rounding_usd", "max_addon_price_ratio"]},
        "priorStrength": 30,
        "facts": {
            "orders": int(len(orders)),
            "drink_only": float((orders.composition == "drink only").mean()),
            "food_only": float((orders.composition == "food only").mean()),
            "annual_orders": float(len(orders) * 365 / orders.day.nunique()),
        },
    }
    (ROOT / "app" / "engine_params.json").write_text(json.dumps(params, indent=1))
    html = (ROOT / "app" / "template.html").read_text().replace("/*__PARAMS__*/null", json.dumps(params))
    (ROOT / "app" / "index.html").write_text(html)
    print(f"Wrote app/index.html ({len(html) / 1024:.0f} KB) and app/engine_params.json")


if __name__ == "__main__":
    build()
