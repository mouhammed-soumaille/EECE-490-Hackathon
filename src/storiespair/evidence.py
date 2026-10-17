"""Statistical evidence for (and against) pairing signals.

Two questions are kept separate:
1. Market-basket view: do specific drink x food pairs co-occur more than chance?
2. Conditional view: once an order is going to get a second item, does the
   first item (or the time of day) change *which* item is added?
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def bh_qvalues(p: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg false-discovery-rate adjusted p-values."""
    p = np.asarray(p, dtype=float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order] * n / np.arange(1, n + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    q = np.empty(n)
    q[order] = np.clip(ranked, 0, 1)
    return q


def pair_table(lines: pd.DataFrame, level: str = "product") -> pd.DataFrame:
    """Classic market-basket table for every drink x food pair.

    level: "product" or "category". The universe is all orders.
    p_value is a one-sided hypergeometric test for co-occurring MORE than
    independence predicts; q_value is BH-adjusted across all pairs.
    """
    col = "product" if level == "product" else "category"
    items = lines[["transaction_id", col, "side"]].drop_duplicates(["transaction_id", col])
    n_orders = lines.transaction_id.nunique()
    drinks = items[items.side == "drink"][["transaction_id", col]].rename(columns={col: "drink"})
    foods = items[items.side == "food"][["transaction_id", col]].rename(columns={col: "food"})
    n_drink = drinks.drink.value_counts()
    n_food = foods.food.value_counts()
    both = drinks.merge(foods, on="transaction_id").groupby(["drink", "food"]).size()
    grid = pd.MultiIndex.from_product([n_drink.index, n_food.index], names=["drink", "food"])
    t = both.reindex(grid, fill_value=0).rename("n_both").reset_index()
    t["n_drink"] = t.drink.map(n_drink)
    t["n_food"] = t.food.map(n_food)
    t["support"] = t.n_both / n_orders
    t["confidence"] = t.n_both / t.n_drink
    t["lift"] = t.n_both * n_orders / (t.n_drink * t.n_food)
    t["p_value"] = stats.hypergeom.sf(t.n_both - 1, n_orders, t.n_drink, t.n_food)
    t["q_value"] = bh_qvalues(t.p_value.values)
    return t.sort_values("lift", ascending=False).reset_index(drop=True)


def cramers_v(ct: pd.DataFrame) -> float:
    chi2 = stats.chi2_contingency(ct)[0]
    n = ct.values.sum()
    k = min(ct.shape) - 1
    return float(np.sqrt(chi2 / (n * k))) if k > 0 else np.nan


def chi2_test(df: pd.DataFrame, a: str, b: str, label: str) -> dict:
    ct = pd.crosstab(df[a], df[b])
    ct = ct.loc[ct.sum(axis=1) > 0, ct.sum(axis=0) > 0]
    chi2, p, dof, _ = stats.chi2_contingency(ct)
    return {"test": label, "n": int(ct.values.sum()), "chi2": round(chi2, 1), "dof": dof,
            "p_value": p, "cramers_v": round(cramers_v(ct), 3)}


def paired_orders(lines: pd.DataFrame) -> pd.DataFrame:
    """Orders containing both sides: first drink line and first food line."""
    first = lines.sort_values(["transaction_id", "line_pos"]).groupby(["transaction_id", "side"]).first()
    d = first.xs("drink", level="side")[["product", "category", "branch", "daypart", "month", "hour", "order_type"]]
    f = first.xs("food", level="side")[["product", "category"]]
    out = d.join(f, how="inner", lsuffix="_drink", rsuffix="_food")
    return out.rename(columns={"product_drink": "drink", "category_drink": "drink_cat",
                               "product_food": "food", "category_food": "food_cat"}).reset_index()


def conditional_tests(pairs: pd.DataFrame, min_n: int = 300) -> pd.DataFrame:
    """Does the first item / time of day change WHICH item is added?

    Category-level tests come first. Product-level tests are run within
    categories (so they measure signal beyond the category effect) and are
    Bonferroni-corrected as a family.
    """
    rows = [
        chi2_test(pairs, "drink_cat", "food_cat", "Drink category -> food category"),
        chi2_test(pairs, "daypart", "food_cat", "Daypart -> food category"),
        chi2_test(pairs, "branch", "food_cat", "Branch -> food category"),
        chi2_test(pairs, "order_type", "food_cat", "Order type -> food category"),
        chi2_test(pairs, "daypart", "drink_cat", "Daypart -> drink category"),
    ]
    family = []
    for cat, g in pairs.groupby("drink_cat"):
        family.append(chi2_test(g, "drink", "food_cat", f"Within {cat}: drink product -> food category"))
    for cat, g in pairs.groupby("food_cat"):
        family.append(chi2_test(g, "drink_cat", "food", f"Within {cat}: drink category -> food product"))
    for (dc, fc), g in pairs.groupby(["drink_cat", "food_cat"]):
        if len(g) >= min_n:
            family.append(chi2_test(g, "drink", "food", f"{dc} x {fc}: drink product -> food product"))
    fam = pd.DataFrame(family)
    fam["p_bonferroni"] = np.minimum(fam.p_value * len(fam), 1.0)
    fam["level"] = "product (within category)"
    top = pd.DataFrame(rows)
    top["p_bonferroni"] = np.minimum(top.p_value * len(top), 1.0)
    top["level"] = "category / context"
    out = pd.concat([top, fam], ignore_index=True)
    out["significant_5pct"] = out.p_bonferroni < 0.05
    return out


# --------------------------------------------------------------------------
# Held-out comparison of "which item will be added" predictors
# --------------------------------------------------------------------------

def _rank_metrics(prob: pd.DataFrame, truth: pd.Series, ks=(1, 3)) -> dict:
    """prob: rows = test orders, columns = candidate items (probabilities)."""
    p = prob.values
    cols = list(prob.columns)
    idx = np.array([cols.index(t) for t in truth])
    out = {}
    order = np.argsort(-p, axis=1)
    for k in ks:
        out[f"hit@{k}"] = float(np.mean([idx[i] in order[i, :k] for i in range(len(idx))]))
    pt = np.clip(p[np.arange(len(idx)), idx], 1e-12, 1)
    out["log_loss"] = float(-np.mean(np.log(pt)))
    return out


def next_item_benchmark(train: pd.DataFrame, test: pd.DataFrame, alpha: float = 1.0) -> pd.DataFrame:
    """Predict the food item added to a drink order, trained on `train`, scored on `test`.

    Predictors
    ----------
    global popularity            P(food)
    branch x daypart popularity  P(food | branch, daypart)
    product association rules    P(food | drink product)              (classic market basket)
    category-aware (Stories Pair) P(food cat | drink cat, daypart) x P(food | food cat)
    """
    foods = sorted(train.food.unique())
    food_cat = train.drop_duplicates("food").set_index("food").food_cat.reindex(foods)

    def smoothed(counts: pd.DataFrame) -> pd.DataFrame:
        c = counts.reindex(columns=foods, fill_value=0) + alpha
        return c.div(c.sum(axis=1), axis=0)

    glob = smoothed(train.food.value_counts().to_frame().T)
    p_glob = pd.DataFrame(np.repeat(glob.values, len(test), axis=0), columns=foods)

    bd = smoothed(pd.crosstab([train.branch, train.daypart], train.food))
    p_bd = bd.reindex(pd.MultiIndex.from_frame(test[["branch", "daypart"]])).fillna(glob.iloc[0]).reset_index(drop=True)

    ar = smoothed(pd.crosstab(train.drink, train.food))
    p_ar = ar.reindex(test.drink).fillna(glob.iloc[0]).reset_index(drop=True)

    cats = sorted(train.food_cat.unique())
    cc = pd.crosstab([train.drink_cat, train.daypart], train.food_cat).reindex(columns=cats, fill_value=0) + alpha
    cc = cc.div(cc.sum(axis=1), axis=0)
    within = train.groupby("food_cat").food.value_counts(normalize=True)
    p_cat = cc.reindex(pd.MultiIndex.from_frame(test[["drink_cat", "daypart"]])).reset_index(drop=True)
    p_ca = pd.DataFrame({f: p_cat[food_cat[f]].values * within[(food_cat[f], f)] for f in foods})

    res = []
    for name, p in [("Global popularity", p_glob), ("Branch x daypart popularity", p_bd),
                    ("Product association rules", p_ar), ("Category-aware (Stories Pair)", p_ca)]:
        p = p[foods]
        p = p.div(p.sum(axis=1), axis=0)
        res.append({"predictor": name, **_rank_metrics(p, test.food.reset_index(drop=True))})
    out = pd.DataFrame(res)
    out["n_test"] = len(test)
    return out
