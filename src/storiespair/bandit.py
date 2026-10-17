"""Stories Pair v2: an engine that learns from every accept / decline.

The v1 engine (engine.py) is right about what history can measure (who pairs,
with which category, what each item earns at each branch) but has to ASSUME how
often customers accept a suggestion. v2 replaces that assumption with a
Thompson-sampling bandit:

* An *arm* is (first-item category, suggested item, discount).
* Each arm keeps a Beta posterior over its *take rate*: P(the suggested item ends
  up in the basket | it was suggested). It starts at the v1 engine's estimate
  (worth `prior_strength` pseudo-suggestions), so day one behaves exactly like v1.
* For each order the engine draws a take rate from every allowed arm's posterior,
  values it with the measured branch economics, and suggests the best draw.
  Uncertain arms sometimes win the draw, so the engine keeps testing them;
  arms that keep failing stop being drawn. Exploration and exploitation in one rule.
* Posteriors update nightly from the day's accept/decline log, so the till's
  lookup table can be refreshed every morning.

Acceptance is shared across branches because notebook 01 shows behaviour does
not differ by branch; profit is always computed with each branch's own prices
and costs.

The simulator below creates "worlds" in which true acceptance differs from the
assumption, item by item, then measures how much profit each policy earns.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .engine import Assumptions, PairEngine


@dataclass
class SideData:
    """Everything about one direction (drink->food or food->drink) for a pool of orders."""
    items: list
    cat_idx: np.ndarray        # first-item category index per order
    cats: list
    Q: np.ndarray              # (n,)    P(pairs anyway)
    s: np.ndarray              # (n, M)  P(added item = i | pairs)
    gp_d: np.ndarray           # (n, M, D) gross profit at each discount
    gp_full: np.ndarray        # (n, M)
    allowed: np.ndarray        # (n, M, D) guardrails
    branch: np.ndarray


def side_data(engine: PairEngine, orders: pd.DataFrame, target: str) -> SideData:
    sc = engine.score(orders, target)
    cats = sorted(orders.first_category.unique())
    return SideData(items=sc["items"], cat_idx=orders.first_category.map({c: i for i, c in enumerate(cats)}).values,
                    cats=cats, Q=sc["Q"], s=sc["s"], gp_d=sc["gp_d"], gp_full=sc["price"] - sc["cost"],
                    allowed=sc["valid"], branch=orders.branch.values)


def take_rate(Q, s, accept_new, w):
    """P(suggested item ends up in basket) = organic i + switchers + new acceptors."""
    return Q * s + Q * (1 - s) * w + (1 - Q) * accept_new


def prior_take(sd: SideData, a: Assumptions, discounts: np.ndarray) -> np.ndarray:
    """v1 engine's take-rate estimate per (category, item, discount): shape (C, M, D)."""
    C, M, D = len(sd.cats), len(sd.items), len(discounts)
    out = np.zeros((C, M, D))
    for c in range(C):
        j = np.flatnonzero(sd.cat_idx == c)[0]  # Q and s depend only on the first-item category
        Q, s = sd.Q[j], sd.s[j]
        acc = np.clip(a.base_acceptance * (M * s)[:, None] * (1 + a.discount_lift_per_10pct * discounts[None, :] / 0.10), 0, 1)
        out[c] = take_rate(Q, s[:, None], acc, a.switch_rate)
    return out


@dataclass
class World:
    """A hypothetical truth about customers: acceptance differs from the assumption."""
    base_acceptance: float
    discount_lift: float
    switch_rate: float
    item_multiplier: np.ndarray  # (C, M) item-level deviation from "acceptance proportional to popularity"

    @classmethod
    def draw(cls, rng, C, M, cfg_assumptions: dict, sigma: float = 0.6):
        a = cfg_assumptions
        return cls(base_acceptance=rng.uniform(a["base_acceptance"]["low"], a["base_acceptance"]["high"]),
                   discount_lift=rng.uniform(a["discount_lift_per_10pct"]["low"], a["discount_lift_per_10pct"]["high"]),
                   switch_rate=rng.uniform(a["switch_rate"]["low"], a["switch_rate"]["high"]),
                   item_multiplier=rng.lognormal(-sigma ** 2 / 2, sigma, size=(C, M)))

    def true_take(self, sd: SideData, discounts: np.ndarray) -> np.ndarray:
        C, M = len(sd.cats), len(sd.items)
        out = np.zeros((C, M, len(discounts)))
        for c in range(C):
            j = np.flatnonzero(sd.cat_idx == c)[0]
            Q, s = sd.Q[j], sd.s[j]
            acc = np.clip(self.base_acceptance * (M * s * self.item_multiplier[c])[:, None]
                          * (1 + self.discount_lift * discounts[None, :] / 0.10), 0, 1)
            out[c] = take_rate(Q, s[:, None], acc, self.switch_rate)
        return out


def _other_term(sd: SideData, idx, w):
    """Expected profit from organic buyers of OTHER items who do not switch: (n, M)."""
    Q, s, g = sd.Q[idx], sd.s[idx], sd.gp_full[idx]
    e_all = (s * g).sum(axis=1, keepdims=True)
    g_other = (e_all - s * g) / np.clip(1 - s, 1e-9, None)
    return Q[:, None] * (1 - s) * (1 - w) * g_other


def simulate(sd: SideData, world: World, prior: np.ndarray, discounts: np.ndarray, days: int = 56,
             orders_per_day: int = 94, prior_strength: float = 30.0, w_assumed: float = 0.10,
             seed: int = 0, policies=("oracle", "thompson", "static", "most_popular", "fixed_combo_10")):
    """Run every policy on the same stream of orders. Returns daily incremental profit per policy."""
    rng = np.random.default_rng(seed)
    C, M, D = prior.shape
    truth = world.true_take(sd, discounts)
    d10 = int(np.argmin(abs(discounts - 0.10)))
    alpha = {p: prior * prior_strength for p in policies}
    beta = {p: (1 - prior) * prior_strength for p in policies}
    pop_rank = np.argsort(-sd.s.mean(axis=0))
    rows, picks = [], []
    for day in range(days):
        idx = rng.integers(0, len(sd.Q), orders_per_day)
        c = sd.cat_idx[idx]
        gp_d, allowed = sd.gp_d[idx], sd.allowed[idx]
        other_true = _other_term(sd, idx, world.switch_rate)
        other_ass = _other_term(sd, idx, w_assumed)
        baseline = (sd.Q[idx][:, None] * sd.s[idx] * sd.gp_full[idx]).sum(axis=1)  # no suggestion at all
        u = rng.random(orders_per_day)
        for p in policies:
            if p == "oracle":
                val = truth[c] * gp_d + other_true[:, :, None]
            elif p == "static":
                val = prior[c] * gp_d + other_ass[:, :, None]
            elif p == "thompson":
                theta = rng.beta(alpha[p][c], beta[p][c])
                val = theta * gp_d + other_ass[:, :, None]
            else:
                val = None
            if val is not None:
                val = np.where(allowed, val, -np.inf).reshape(orders_per_day, -1)
                flat = val.argmax(axis=1)
                ii, dd = np.unravel_index(flat, (M, D))
            else:  # best-seller among allowed items, full price or 10% off
                ok = allowed[:, :, 0]
                ii = np.array([next(m for m in pop_rank if ok[n, m]) for n in range(orders_per_day)])
                dd = np.full(orders_per_day, d10 if p == "fixed_combo_10" else 0)
            r_ = np.arange(orders_per_day)
            pt = truth[c, ii, dd]
            taken = u < pt
            # taken -> the suggested item's profit; not taken -> expected profit of organic buyers of other items
            reward = np.where(taken, gp_d[r_, ii, dd], other_true[r_, ii] / np.clip(1 - pt, 1e-9, None))
            rows.append({"day": day, "policy": p, "incremental_gp": float((reward - baseline).sum()),
                         "expected_incremental_gp": float((pt * gp_d[r_, ii, dd] + other_true[r_, ii] - baseline).sum()),
                         "discount_share": float((discounts[dd] > 0).mean())})
            if p == "thompson":
                # nightly update from the day's accept / decline log
                np.add.at(alpha[p], (c, ii, dd), taken.astype(float))
                np.add.at(beta[p], (c, ii, dd), (~taken).astype(float))
            if p in ("thompson", "oracle", "static"):
                picks.append(pd.DataFrame({"day": day, "policy": p, "cat": c, "item": ii, "disc": dd}))
    return pd.DataFrame(rows), pd.concat(picks, ignore_index=True), (alpha, beta, truth)
