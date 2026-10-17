"""The Stories Pair decision engine.

For an order whose first item is on one side (drink or food), score every item
on the other side at every allowed discount and offer the one with the highest
expected *incremental* gross profit, or nothing.

Expected incremental gross profit of offering item i at discount d
-------------------------------------------------------------------
    dGP = (1 - Q) * a_i(d) * gp_i(d)                    new sales from people who would not have added anything
          - Q * s_i * (p_i - price_i(d))                discount given away to people who would have bought i anyway
          + w * Q * (1 - s_i) * (gp_i(d) - gp_other)     people who would have bought another item switch to i

    Q        P(order gets an item from the other side anyway)        measured (attach model)
    s_i      P(that item is i | it gets added)                        measured (category model x within-category share)
    a_i(d)   acceptance among people who would not have added an item  ASSUMED: r0 * (K * s_i) * (1 + lift * d / 10%)
    w        share of organic buyers who switch to the suggested item  ASSUMED
    gp_i(d)  offer price minus unit cost at this branch                measured (unit economics)

The measured parts come from history. The assumed parts are explicit inputs
(config/assumptions.json) that a pilot replaces with real numbers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .data import DAYPARTS, DRINK_CATEGORIES, FOOD_CATEGORIES, daypart, find_repo_root
from .models import PairModels, trigger_features

PAIRING_NAMES = {"Morning": "Morning Pairing", "Midday": "Lunch Pairing",
                 "Afternoon": "Afternoon Pairing", "Evening": "Evening Pairing"}


def load_config(root: str | Path | None = None) -> dict:
    root = Path(root) if root else find_repo_root()
    cfg = {}
    for name in ["assumptions", "guardrails", "compatibility"]:
        with open(root / "config" / f"{name}.json") as f:
            cfg[name] = json.load(f)
    return cfg


@dataclass
class Assumptions:
    base_acceptance: float = 0.06       # r0: acceptance of an average-appeal item, full price
    discount_lift_per_10pct: float = 0.10  # relative acceptance gain per 10% off
    switch_rate: float = 0.10           # w
    offer_rate: float = 0.80            # share of eligible orders where staff actually make the offer

    @classmethod
    def from_config(cls, cfg: dict, scenario: str = "base") -> "Assumptions":
        a = cfg["assumptions"]
        return cls(**{k: a[k][scenario] for k in ["base_acceptance", "discount_lift_per_10pct", "switch_rate", "offer_rate"]})


@dataclass
class Guardrails:
    discount_grid: list = field(default_factory=lambda: [0.0, 0.05, 0.10, 0.15])
    min_margin_after_discount: float = 0.40
    min_expected_gain_usd: float = 0.05
    price_rounding_usd: float = 0.05
    never_suggest: list = field(default_factory=list)
    max_addon_price_ratio: float = 2.5

    @classmethod
    def from_config(cls, cfg: dict) -> "Guardrails":
        g = cfg["guardrails"]
        return cls(**{k: g[k] for k in cls.__dataclass_fields__ if k in g})


class PairEngine:
    def __init__(self, models: PairModels, unit_econ: pd.DataFrame, compatibility: dict,
                 assumptions: Assumptions | None = None, guardrails: Guardrails | None = None):
        self.models = models
        self.ue = unit_econ.set_index(["branch", "product"])
        self.compat = compatibility
        self.a = assumptions or Assumptions()
        self.g = guardrails or Guardrails()
        cat_of = unit_econ.drop_duplicates("product").set_index("product").category
        self.items = {
            "food": [p for c in FOOD_CATEGORIES for p in sorted(cat_of[cat_of == c].index)],
            "drink": [p for c in DRINK_CATEGORIES for p in sorted(cat_of[cat_of == c].index)],
        }
        self.cat_of = cat_of
        self.price_tbl = unit_econ.pivot(index="branch", columns="product", values="price")
        self.cost_tbl = unit_econ.pivot(index="branch", columns="product", values="cost")

    # ------------------------------------------------------------------
    def _side_arrays(self, ctx: pd.DataFrame, target_side: str):
        """Arrays (n_orders x n_items) of s_i, price, cost for the target side."""
        trig_side = "drink" if target_side == "food" else "food"
        items = self.items[target_side]
        X = trigger_features(ctx)
        Q = self.models.attach_prob(X)
        Pc = self.models.category_probs(X, trig_side)
        share = self.models.item_share
        s = np.column_stack([Pc[self.cat_of[i]].values * share.get((self.cat_of[i], i), 0.0) for i in items])
        s = s / s.sum(axis=1, keepdims=True)
        price = self.price_tbl.loc[ctx.branch.values, items].values
        cost = self.cost_tbl.loc[ctx.branch.values, items].values
        # compatibility: category of the first item -> allowed categories
        allowed = np.column_stack([
            ctx.first_category.map(lambda c, cat=self.cat_of[i]: cat in self.compat.get(c, [])).values
            for i in items
        ])
        never = np.array([i in self.g.never_suggest for i in items])
        allowed &= ~never[None, :]
        # affordability: the add-on may cost at most N x the first item
        allowed &= price <= self.g.max_addon_price_ratio * ctx.first_price.values[:, None]
        return items, Q, s, price, cost, allowed

    def prepare(self, ctx: pd.DataFrame, target_side: str):
        """Model predictions for a batch; reuse across many assumption scenarios."""
        return self._side_arrays(ctx, target_side)

    def score(self, ctx: pd.DataFrame, target_side: str, assumptions: Assumptions | None = None,
              discounts=None, arrays=None) -> dict:
        """Full expected-gain cube: orders x items x discounts."""
        a = assumptions or self.a
        discounts = np.array(self.g.discount_grid if discounts is None else discounts, dtype=float)
        items, Q, s, price, cost, allowed = arrays if arrays is not None else self._side_arrays(ctx, target_side)
        K = s.shape[1]
        r = self.g.price_rounding_usd
        raw = price[:, :, None] * (1 - discounts[None, None, :])
        # discounted prices are rounded to a till-friendly step; full price stays exact
        offer_price = np.where(discounts[None, None, :] > 0, np.round(raw / r) * r, raw)
        gp_d = offer_price - cost[:, :, None]
        gp_full = (price - cost)
        # expected gp of the item an organic buyer would have picked, excluding i
        e_all = (s * gp_full).sum(axis=1, keepdims=True)
        gp_other = (e_all - s * gp_full) / np.clip(1 - s, 1e-9, None)
        accept = np.clip(a.base_acceptance * (K * s)[:, :, None]
                         * (1 + a.discount_lift_per_10pct * discounts[None, None, :] / 0.10), 0, 1)
        Qb = Q[:, None, None]
        sb = s[:, :, None]
        dgp = ((1 - Qb) * accept * gp_d
               - Qb * sb * (price[:, :, None] - offer_price)
               + a.switch_rate * Qb * (1 - sb) * (gp_d - gp_other[:, :, None]))
        margin_ok = gp_d / np.clip(offer_price, 1e-9, None) >= self.g.min_margin_after_discount
        valid = allowed[:, :, None] & margin_ok
        return {"items": items, "discounts": discounts, "Q": Q, "s": s, "price": price, "cost": cost,
                "offer_price": offer_price, "gp_d": gp_d, "accept": accept, "dgp": dgp, "valid": valid}

    def decide(self, ctx: pd.DataFrame, target_side: str, policy: str = "stories_pair",
               assumptions: Assumptions | None = None, arrays=None) -> pd.DataFrame:
        """One decision per order under a policy.

        Policies
        --------
        stories_pair       best (item, discount) by expected gain, guardrails on, may skip
        stories_pair_nodisc  same, discounts disabled
        most_popular       the side's best-selling item, full price, always offered
        highest_margin     the item with the highest unit gross profit at this branch, full price
        fixed_combo_10     best-selling item at 10% off (classic combo), always offered
        """
        sc = self.score(ctx, target_side, assumptions, arrays=arrays)
        n = len(ctx)
        dgp, valid, disc = sc["dgp"], sc["valid"], sc["discounts"]
        allowed_full = sc["valid"][:, :, 0]
        pop = np.where(allowed_full, sc["s"].mean(axis=0)[None, :], -np.inf)
        pop_idx = pop.argmax(axis=1)  # best-seller among items the guardrails allow for this order
        if policy in ("stories_pair", "stories_pair_nodisc"):
            m = np.where(valid, dgp, -np.inf)
            if policy == "stories_pair_nodisc":
                m[:, :, disc > 0] = -np.inf
            flat = m.reshape(n, -1).argmax(axis=1)
            ii, dd = np.unravel_index(flat, m.shape[1:])
            best = m[np.arange(n), ii, dd]
            offer = best >= self.g.min_expected_gain_usd
        elif policy == "most_popular":
            ii, dd, offer = pop_idx, np.zeros(n, int), np.ones(n, bool)
        elif policy == "highest_margin":
            gp = np.where(allowed_full, sc["price"] - sc["cost"], -np.inf)
            ii, dd, offer = gp.argmax(axis=1), np.zeros(n, int), np.ones(n, bool)
        elif policy == "fixed_combo_10":
            ii, dd, offer = pop_idx, np.full(n, int(np.argmin(abs(disc - 0.10)))), np.ones(n, bool)
        else:
            raise ValueError(policy)
        r = np.arange(n)
        out = pd.DataFrame({
            "item": np.array(sc["items"])[ii],
            "discount": disc[dd],
            "list_price": sc["price"][r, ii],
            "offer_price": sc["offer_price"][r, ii, dd],
            "Q_organic_attach": sc["Q"],
            "s_item_share": sc["s"][r, ii],
            "acceptance_new": sc["accept"][r, ii, dd],
            "gp_if_accepted": sc["gp_d"][r, ii, dd],
            "expected_gain": sc["dgp"][r, ii, dd],
            "offer": offer,
        }, index=ctx.index)
        out.loc[~out.offer, ["expected_gain", "acceptance_new"]] = 0.0
        # discount actually handed out (organic buyers of i + newly accepted), per order
        a = assumptions or self.a
        out["discount_cost"] = np.where(
            out.offer,
            (out.Q_organic_attach * out.s_item_share + (1 - out.Q_organic_attach) * out.acceptance_new
             + a.switch_rate * out.Q_organic_attach * (1 - out.s_item_share)) * (out.list_price - out.offer_price),
            0.0)
        return out

    # ------------------------------------------------------------------
    def context(self, branch: str, when: pd.Timestamp, first_product: str,
                order_type: str = "Dine-in", known_customer: bool = False) -> pd.DataFrame:
        when = pd.Timestamp(when)
        cat = self.cat_of[first_product]
        row = {
            "branch": branch, "dt": when, "hour": when.hour, "dow": when.dayofweek, "month": when.month,
            "daypart": daypart(pd.Series([when.hour])).iloc[0], "order_type": order_type,
            "weekend": when.dayofweek >= 5, "known_customer": known_customer,
            "first_product": first_product, "first_category": cat,
            "first_side": "drink" if cat in DRINK_CATEGORIES else "food",
            "first_price": float(self.ue.loc[(branch, first_product), "price"]),
        }
        return pd.DataFrame([row])

    def recommend(self, branch: str, when, basket: list[str], order_type: str = "Dine-in",
                  declined: list[str] | None = None) -> dict:
        """POS call: what to suggest for this basket, if anything."""
        declined = declined or []
        first = basket[0]
        ctx = self.context(branch, when, first, order_type)
        trig_side = ctx.first_side.iloc[0]
        target = "food" if trig_side == "drink" else "drink"
        sides = {self.cat_of[p] in DRINK_CATEGORIES for p in basket}
        if len(sides) > 1:
            return {"offer": False, "reason": "Basket already has a drink and a food item.", "candidates": None}
        sc = self.score(ctx, target)
        items = sc["items"]
        rows = []
        for j, it in enumerate(items):
            for k, d in enumerate(sc["discounts"]):
                rows.append({"item": it, "category": self.cat_of[it], "discount": d,
                             "offer_price": sc["offer_price"][0, j, k], "list_price": sc["price"][0, j],
                             "gp_if_accepted": sc["gp_d"][0, j, k], "item_share": sc["s"][0, j],
                             "acceptance_new": sc["accept"][0, j, k], "expected_gain": sc["dgp"][0, j, k],
                             "allowed": bool(sc["valid"][0, j, k]) and it not in basket and it not in declined})
        cand = pd.DataFrame(rows)
        ok = cand[cand.allowed].sort_values("expected_gain", ascending=False)
        if ok.empty or ok.expected_gain.iloc[0] < self.g.min_expected_gain_usd:
            return {"offer": False, "reason": "No suggestion clears the expected-gain threshold.",
                    "Q": float(sc["Q"][0]), "candidates": cand}
        b = ok.iloc[0]
        cat_share = cand[cand.discount == 0].groupby("category").item_share.sum()
        first_price = float(ctx.first_price.iloc[0])
        dp = ctx.daypart.iloc[0]
        return {
            "offer": True,
            "pairing_name": PAIRING_NAMES.get(dp, "Pairing"),
            "first_item": first, "suggested_item": b["item"], "category": b["category"],
            "discount": float(b["discount"]), "item_price": float(b["offer_price"]),
            "combo_total": round(first_price + float(b["offer_price"]), 2),
            "saving": round(float(b["list_price"] - b["offer_price"]), 2),
            "expected_gain": float(b["expected_gain"]),
            "Q": float(sc["Q"][0]),
            "reason": (f"After a {first} in the {dp.lower()}, {cat_share[b['category']]:.0%} of customers who add "
                       f"something pick {b['category'].lower()}. The {b['item']} earns ${b['gp_if_accepted']:.2f} gross "
                       f"profit per acceptance at {branch}, the best expected gain once customers who would have "
                       f"added it anyway are accounted for."),
            "candidates": cand,
        }

    def playbook(self, typical_hour=None) -> pd.DataFrame:
        """Branch x daypart x first-item category -> suggested item and price.

        A lookup table a POS can use on day one, without running any model.
        """
        typical_hour = typical_hour or {"Morning": 9, "Midday": 13, "Afternoon": 17, "Evening": 21}
        rows = []
        for branch in sorted(self.ue.index.get_level_values(0).unique()):
            for dp in DAYPARTS:
                for cat in DRINK_CATEGORIES + FOOD_CATEGORIES:
                    prods = [p for p in self.cat_of.index if self.cat_of[p] == cat]
                    # representative first item = the category's best seller at this branch
                    units = self.ue.loc[branch].loc[prods, "units"]
                    rep = units.idxmax()
                    when = pd.Timestamp("2026-06-03") + pd.Timedelta(hours=typical_hour[dp])  # a Wednesday
                    r = self.recommend(branch, when, [rep])
                    rows.append({"branch": branch, "daypart": dp, "first_category": cat, "example_first_item": rep,
                                 "suggest": r.get("suggested_item") if r["offer"] else "(no offer)",
                                 "discount": r.get("discount", np.nan), "item_price": r.get("item_price", np.nan),
                                 "expected_gain_per_order": round(r.get("expected_gain", 0.0), 3)})
        return pd.DataFrame(rows)
