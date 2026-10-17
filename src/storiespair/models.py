"""Receptiveness models.

Part A  attach model:    P(order gets an item from the other side | first item, context)
Part B  category model:  P(category of the added item | first item, context, it gets added)
Item level:              P(product | category), pooled shares (no product-level pairing
                         signal survives testing, see notebook 02)

Every model is compared with simple baselines on months it never saw.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

from .data import DRINK_CATEGORIES, FOOD_CATEGORIES

CAT_FEATURES = ["first_side", "first_category", "first_product", "branch", "daypart",
                "order_type", "weekend", "known_customer"]
NUM_FEATURES = ["hour_sin", "hour_cos", "first_price"]


def trigger_features(orders: pd.DataFrame) -> pd.DataFrame:
    """Features known at the till when the first item is rung (no look-ahead)."""
    X = pd.DataFrame(index=orders.index)
    for c in CAT_FEATURES:
        X[c] = orders[c].astype(str)
    X["hour_sin"] = np.sin(2 * np.pi * orders.hour / 24)
    X["hour_cos"] = np.cos(2 * np.pi * orders.hour / 24)
    X["first_price"] = orders.first_price.astype(float)
    return X


def time_split(orders: pd.DataFrame, train_months=(1, 2, 3, 4), valid_months=(5,), test_months=(6,)):
    tr = orders[orders.month.isin(train_months)]
    va = orders[orders.month.isin(valid_months)]
    te = orders[orders.month.isin(test_months)]
    return tr, va, te


# --------------------------------------------------------------------------
# Part A: attach model
# --------------------------------------------------------------------------

def _logit_pipeline(cat_cols, num_cols, C=1.0, multiclass=False):
    pre = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=20), cat_cols),
        ("num", StandardScaler(), num_cols),
    ])
    return Pipeline([("pre", pre), ("clf", LogisticRegression(C=C, max_iter=2000))])


def _hgb_pipeline(cat_cols, num_cols):
    pre = ColumnTransformer([
        ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), cat_cols),
        ("num", "passthrough", num_cols),
    ])
    clf = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=80,
        l2_regularization=1.0, categorical_features=list(range(len(cat_cols))), random_state=0,
    )
    return Pipeline([("pre", pre), ("clf", clf)])


class SegmentRate:
    """Smoothed mean of the target inside a segment (the honest baseline)."""

    def __init__(self, cols, prior_strength=50):
        self.cols, self.k = list(cols), prior_strength

    def fit(self, X, y):
        y = pd.Series(np.asarray(y, dtype=float), index=X.index)
        self.base_ = float(y.mean())
        g = y.groupby([X[c] for c in self.cols])
        self.rate_ = (g.sum() + self.k * self.base_) / (g.count() + self.k)
        return self

    def predict_proba(self, X):
        key = pd.MultiIndex.from_frame(X[self.cols]) if len(self.cols) > 1 else X[self.cols[0]]
        p = self.rate_.reindex(key).fillna(self.base_).values
        return np.column_stack([1 - p, p])


class BaseRate:
    def fit(self, X, y):
        self.p_ = float(np.mean(y))
        return self

    def predict_proba(self, X):
        return np.column_stack([np.full(len(X), 1 - self.p_), np.full(len(X), self.p_)])


def attach_candidates():
    return {
        "Base rate (always predict the average)": BaseRate(),
        "Segment rate: first-item category": SegmentRate(["first_category"]),
        "Segment rate: first product": SegmentRate(["first_product"]),
        "Logistic regression (all context)": _logit_pipeline(CAT_FEATURES, NUM_FEATURES, C=0.5),
        "Gradient boosting (all context)": _hgb_pipeline(CAT_FEATURES, NUM_FEATURES),
    }


def binary_metrics(y, p) -> dict:
    return {
        "roc_auc": roc_auc_score(y, p),
        "log_loss": log_loss(y, np.clip(p, 1e-6, 1 - 1e-6)),
        "brier": brier_score_loss(y, p),
        "mean_pred": float(np.mean(p)),
        "actual_rate": float(np.mean(y)),
    }


def benchmark_attach(orders: pd.DataFrame, target: str = "paired"):
    """Fit every candidate on Jan-Apr, compare on May (validation) and June (test).

    Returns the metrics table and the fitted models (refit on Jan-May).
    """
    tr, va, te = time_split(orders)
    rows, fitted = [], {}
    for name, model in attach_candidates().items():
        model.fit(trigger_features(tr), tr[target].astype(int))
        pv = model.predict_proba(trigger_features(va))[:, 1]
        # refit on Jan-May before touching June
        trva = pd.concat([tr, va])
        model.fit(trigger_features(trva), trva[target].astype(int))
        pt = model.predict_proba(trigger_features(te))[:, 1]
        mv, mt = binary_metrics(va[target], pv), binary_metrics(te[target], pt)
        rows.append({"model": name, "valid_auc (May)": mv["roc_auc"], "test_auc (June)": mt["roc_auc"],
                     "test_log_loss": mt["log_loss"], "test_brier": mt["brier"]})
        fitted[name] = model
    return pd.DataFrame(rows), fitted


# --------------------------------------------------------------------------
# Part B: which category gets added
# --------------------------------------------------------------------------

CHOICE_CAT = ["first_category", "daypart", "branch", "order_type", "weekend"]
CHOICE_NUM = ["hour_sin", "hour_cos"]


class TableModel:
    """Smoothed conditional shares P(class | segment)."""

    def __init__(self, cols, alpha=1.0):
        self.cols, self.alpha = list(cols), alpha

    def fit(self, X, y):
        y = pd.Series(np.asarray(y), index=X.index)
        self.classes_ = np.array(sorted(y.unique()))
        glob = y.value_counts().reindex(self.classes_, fill_value=0) + self.alpha
        self.glob_ = glob / glob.sum()
        if not self.cols:
            return self
        ct = pd.crosstab([X[c] for c in self.cols], y).reindex(columns=self.classes_, fill_value=0) + self.alpha
        self.table_ = ct.div(ct.sum(axis=1), axis=0)
        return self

    def predict_proba(self, X):
        if not self.cols:
            return np.repeat(self.glob_.values[None, :], len(X), axis=0)
        key = pd.MultiIndex.from_frame(X[self.cols]) if len(self.cols) > 1 else X[self.cols[0]]
        t = self.table_.reindex(key)
        t = t.fillna(pd.Series(self.glob_.values, index=self.classes_))
        return t.values


def choice_candidates():
    return {
        "Global category shares": TableModel([]),
        "Shares by daypart": TableModel(["daypart"]),
        "Shares by first-item category": TableModel(["first_category"]),
        "Shares by first-item category x daypart": TableModel(["first_category", "daypart"]),
        "Multinomial logistic regression": _logit_pipeline(CHOICE_CAT, CHOICE_NUM, C=0.5),
    }


def multiclass_metrics(y, P, classes) -> dict:
    y = np.asarray(y)
    idx = np.array([list(classes).index(v) for v in y])
    top1 = np.asarray(classes)[P.argmax(axis=1)]
    top2 = np.argsort(-P, axis=1)[:, :2]
    return {
        "log_loss": float(-np.mean(np.log(np.clip(P[np.arange(len(y)), idx], 1e-12, 1)))),
        "top1_acc": accuracy_score(y, top1),
        "top2_acc": float(np.mean([idx[i] in top2[i] for i in range(len(y))])),
    }


def choice_dataset(orders: pd.DataFrame, added: pd.DataFrame, side: str) -> pd.DataFrame:
    """Paired orders whose first item is on `side`, with the category that was added."""
    d = orders[(orders.first_side == side) & orders.paired].join(added, on="transaction_id", how="inner")
    return d


def benchmark_choice(orders: pd.DataFrame, added: pd.DataFrame, side: str = "drink"):
    data = choice_dataset(orders, added, side)
    tr, va, te = time_split(data)
    rows, fitted = [], {}
    for name, model in choice_candidates().items():
        trva = pd.concat([tr, va])
        model.fit(trigger_features(tr), tr.added_category)
        classes = list(model.classes_)
        Pv = model.predict_proba(trigger_features(va))
        model.fit(trigger_features(trva), trva.added_category)
        Pt = model.predict_proba(trigger_features(te))
        mv = multiclass_metrics(va.added_category, Pv, classes)
        mt = multiclass_metrics(te.added_category, Pt, classes)
        rows.append({"model": name, "valid_log_loss (May)": mv["log_loss"], "test_log_loss (June)": mt["log_loss"],
                     "test_top1_acc": mt["top1_acc"], "test_top2_acc": mt["top2_acc"]})
        fitted[name] = model
    return pd.DataFrame(rows), fitted


# --------------------------------------------------------------------------
# Bundle used by the engine
# --------------------------------------------------------------------------

class PairModels:
    """Everything the engine needs to estimate who adds what.

    attach      fitted binary model, P(paired | context)
    choice      {"drink": model, "food": model}, P(added category | context)
    item_share  P(product | category), pooled over branches
    """

    def __init__(self, attach, choice: dict, item_share: pd.Series):
        self.attach, self.choice, self.item_share = attach, choice, item_share

    @classmethod
    def fit(cls, orders: pd.DataFrame, lines: pd.DataFrame, added: pd.DataFrame,
            months=(1, 2, 3, 4, 5), attach_name="Segment rate: first-item category",
            choice_name="Shares by first-item category"):
        o = orders[orders.month.isin(months)]
        attach = attach_candidates()[attach_name].fit(trigger_features(o), o.paired.astype(int))
        choice = {}
        for side in ["drink", "food"]:
            d = choice_dataset(o, added, side)
            choice[side] = choice_candidates()[choice_name].fit(trigger_features(d), d.added_category)
        ln = lines[lines.month.isin(months)]
        share = ln.groupby(["category", "product"]).quantity.sum()
        share = share / share.groupby(level=0).transform("sum")
        return cls(attach, choice, share)

    def attach_prob(self, X: pd.DataFrame) -> np.ndarray:
        return self.attach.predict_proba(X)[:, 1]

    def category_probs(self, X: pd.DataFrame, side: str) -> pd.DataFrame:
        m = self.choice[side]
        cats = FOOD_CATEGORIES if side == "drink" else DRINK_CATEGORIES
        P = pd.DataFrame(m.predict_proba(X), columns=list(m.classes_), index=X.index)
        return P.reindex(columns=cats, fill_value=0.0)
