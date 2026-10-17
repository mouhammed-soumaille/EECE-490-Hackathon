"""Automated checks that the engine keeps its promises.

Run from the repo root with either:
    python tests/test_engine.py        (no extra packages needed)
    pytest tests/                      (if pytest is installed)

What is checked
1. Data: rebuilding orders from line items loses no revenue, and every order has one first item.
2. No leakage: the deployed models are fitted on January-May only, so June stays unseen.
3. Guardrails: every one of the 135 playbook rows obeys every business rule in config/guardrails.json.
4. Determinism: the engine gives the same answer twice, and the published playbook matches the code.
5. Sanity: an add-on is always from the other side (drink -> food, food -> drink).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

import numpy as np
import pandas as pd
from storiespair import data, models, engine as E

_cache = {}


def _setup():
    if not _cache:
        lines = data.load_lines()
        orders = data.build_orders(lines)
        added = data.other_side_first_item(lines, orders)
        ue = data.unit_economics(lines)
        cfg = E.load_config()
        pm = models.PairModels.fit(orders, lines, added)  # default months = Jan-May
        eng = E.PairEngine(pm, ue, cfg["compatibility"], E.Assumptions.from_config(cfg), E.Guardrails.from_config(cfg))
        _cache.update(lines=lines, orders=orders, ue=ue, cfg=cfg, eng=eng, pb=eng.playbook())
    return _cache


def test_orders_rebuild_without_loss():
    c = _setup()
    assert np.isclose(c["orders"].revenue.sum(), c["lines"].line_revenue.sum(), rtol=1e-9)
    assert c["orders"].transaction_id.is_unique
    assert (c["lines"].line_pos == 0).sum() == len(c["orders"])


def test_models_never_see_june():
    import inspect
    default_months = inspect.signature(models.PairModels.fit).parameters["months"].default
    assert 6 not in default_months, "June is the test month and must not be used for fitting"


def test_playbook_obeys_every_guardrail():
    c = _setup()
    g, pb, ue = c["cfg"]["guardrails"], c["pb"], c["ue"].set_index(["branch", "product"])
    offers = pb[pb.suggest != "(no offer)"]
    assert len(pb) == 135
    assert len(offers) > 0
    for r in offers.itertuples():
        cost = ue.loc[(r.branch, r.suggest), "cost"]
        assert r.discount <= max(g["discount_grid"]) + 1e-9, r
        assert (r.suggested_price - cost) / r.suggested_price >= g["min_margin_after_discount"] - 1e-9, r
        assert r.suggested_price <= g["max_addon_price_ratio"] * r.first_price + 1e-9, r
        assert r.expected_gain_per_order >= g["min_expected_gain_usd"] - 1e-9, r
        if r.discount > 0:  # list prices are Stories' own; only discounted prices are rounded
            cents = round(r.suggested_price * 100)
            assert cents % round(g["price_rounding_usd"] * 100) == 0, r
        assert r.suggest not in g["never_suggest"], r


def test_addon_is_from_the_other_side():
    c = _setup()
    side = c["ue"].drop_duplicates("product").set_index("product").side
    offers = c["pb"][c["pb"].suggest != "(no offer)"]
    assert (offers.first_item.map(side) != offers.suggest.map(side)).all()


def test_engine_is_deterministic_and_matches_published_playbook():
    c = _setup()
    again = c["eng"].playbook()
    pd.testing.assert_frame_equal(c["pb"], again)
    published = pd.read_csv("outputs/playbook.csv")
    assert (published.suggest.values == c["pb"].suggest.values).all(), "outputs/playbook.csv is stale"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS  {t.__name__}")
    print(f"\nAll {len(tests)} checks passed.")
