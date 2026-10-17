"""Value sizing, sensitivity analysis and pilot design.

Everything here is an ESTIMATE built on the measured models plus the explicit
assumptions in config/assumptions.json. Measured facts live in notebooks 00-03.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
from scipy import stats

from .engine import Assumptions, PairEngine

POLICIES = {
    "most_popular": "Suggest the best-seller (full price)",
    "highest_margin": "Suggest the highest-profit item (full price)",
    "fixed_combo_10": "Classic combo: best-seller at 10% off",
    "stories_pair_nodisc": "Stories Pair, no discounts",
    "stories_pair": "Stories Pair (item + discount optimised)",
}


class Replay:
    """Holds a batch of historical orders and the engine's model predictions for them."""

    def __init__(self, engine: PairEngine, orders: pd.DataFrame, annual_orders: float):
        self.engine = engine
        self.orders = orders
        self.annual_orders = annual_orders
        self.parts = {}
        for side, target in [("drink", "food"), ("food", "drink")]:
            ctx = orders[orders.first_side == side]
            self.parts[target] = (ctx, engine.prepare(ctx, target))

    def run(self, policy: str, a: Assumptions) -> dict:
        tot = {"orders": 0, "offers": 0.0, "new_items": 0.0, "gain": 0.0, "discount_cost": 0.0}
        for target, (ctx, arrays) in self.parts.items():
            d = self.engine.decide(ctx, target, policy, a, arrays=arrays)
            tot["orders"] += len(d)
            tot["offers"] += d.offer.sum() * a.offer_rate
            tot["new_items"] += ((1 - d.Q_organic_attach) * d.acceptance_new).sum() * a.offer_rate
            tot["gain"] += d.expected_gain.sum() * a.offer_rate
            tot["discount_cost"] += d.discount_cost.sum() * a.offer_rate
        scale = self.annual_orders / tot["orders"]
        return {
            "annual_incremental_gp": tot["gain"] * scale,
            "annual_offers": tot["offers"] * scale,
            "annual_extra_items": tot["new_items"] * scale,
            "annual_discount_given": tot["discount_cost"] * scale,
            "gain_per_offer": tot["gain"] / max(tot["offers"], 1e-9),
        }

    def compare(self, a: Assumptions) -> pd.DataFrame:
        rows = [{"policy": label, "key": key, **self.run(key, a)} for key, label in POLICIES.items()]
        return pd.DataFrame(rows)

    def acceptance_curve(self, a: Assumptions, grid=None) -> pd.DataFrame:
        grid = np.linspace(0, 0.15, 16) if grid is None else grid
        rows = []
        for r0 in grid:
            aa = replace(a, base_acceptance=float(r0))
            for key, label in POLICIES.items():
                rows.append({"base_acceptance": r0, "policy": label, "key": key,
                             "annual_incremental_gp": self.run(key, aa)["annual_incremental_gp"]})
        return pd.DataFrame(rows)

    def break_even_acceptance(self, policy: str, a: Assumptions, lo=0.0, hi=0.5) -> float:
        """Smallest base acceptance at which a policy stops losing money."""
        f = lambda r: self.run(policy, replace(a, base_acceptance=r))["annual_incremental_gp"]
        if f(lo) >= 0:
            return 0.0
        if f(hi) < 0:
            return np.nan
        for _ in range(30):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
        return hi

    def monte_carlo(self, cfg_assumptions: dict, n: int = 400, seed: int = 0, policy="stories_pair") -> pd.DataFrame:
        """Sample every assumption from a triangular(low, base, high) distribution."""
        rng = np.random.default_rng(seed)
        keys = ["base_acceptance", "discount_lift_per_10pct", "switch_rate", "offer_rate"]
        rows = []
        for _ in range(n):
            draw = {}
            for k in keys:
                lo, mode, hi = (cfg_assumptions[k][x] for x in ["low", "base", "high"])
                draw[k] = rng.triangular(lo, mode, hi) if hi > lo else mode
            res = self.run(policy, Assumptions(**draw))
            rows.append({**draw, **res})
        return pd.DataFrame(rows)

    def tornado(self, cfg_assumptions: dict, policy="stories_pair") -> pd.DataFrame:
        base = Assumptions(**{k: cfg_assumptions[k]["base"] for k in
                              ["base_acceptance", "discount_lift_per_10pct", "switch_rate", "offer_rate"]})
        base_val = self.run(policy, base)["annual_incremental_gp"]
        rows = []
        for k in ["base_acceptance", "discount_lift_per_10pct", "switch_rate", "offer_rate"]:
            lo = self.run(policy, replace(base, **{k: cfg_assumptions[k]["low"]}))["annual_incremental_gp"]
            hi = self.run(policy, replace(base, **{k: cfg_assumptions[k]["high"]}))["annual_incremental_gp"]
            rows.append({"assumption": k, "low_value": cfg_assumptions[k]["low"], "high_value": cfg_assumptions[k]["high"],
                         "annual_gp_at_low": lo, "annual_gp_at_high": hi, "base": base_val})
        t = pd.DataFrame(rows)
        t["swing"] = (t.annual_gp_at_high - t.annual_gp_at_low).abs()
        return t.sort_values("swing", ascending=False).reset_index(drop=True)


def power_per_arm(sd: float, delta: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Orders per arm for a two-sample comparison of means (normal approximation)."""
    z = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    return int(np.ceil(2 * (z * sd / delta) ** 2))


def pilot_table(orders: pd.DataFrame, effects_usd=(0.05, 0.10, 0.15, 0.25), branches=None) -> pd.DataFrame:
    """How many days a 50/50 split (odd vs even receipt numbers) needs per effect size."""
    sd = float(orders.gp.std())
    days = orders.day.nunique()
    branches = branches or sorted(orders.branch.unique())
    daily = orders.groupby("branch").size() / days
    rows = []
    for e in effects_usd:
        n = power_per_arm(sd, e)
        row = {"detectable_gain_per_order_usd": e, "orders_per_arm": n, "all_branches_days": int(np.ceil(2 * n / daily.sum()))}
        for b in branches:
            row[f"{b}_only_days"] = int(np.ceil(2 * n / daily[b]))
        rows.append(row)
    return pd.DataFrame(rows), sd, daily
