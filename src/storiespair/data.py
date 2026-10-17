"""Load the Stories transaction file and rebuild orders.

One row in the raw file is one product line. A Transaction ID that repeats
across rows is a multi-line order. Every notebook imports from here so the
data contract lives in one place.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

RAW_COLUMNS = {
    "Transaction ID": "transaction_id",
    "Date": "date",
    "Time": "time",
    "Branch": "branch",
    "Customer ID": "customer_id",
    "Order Type": "order_type",
    "Product": "product",
    "Category": "category",
    "Quantity": "quantity",
    "Unit Price (USD)": "unit_price",
    "Discount Rate": "discount_rate",
    "Unit Cost (USD)": "unit_cost",
    "Line Revenue (USD)": "line_revenue",
    "Line Gross Profit (USD)": "line_gp",
}

DRINK_CATEGORIES = ["Hot Coffee", "Cold Coffee", "Matcha & Tea", "Cold Drinks"]
FOOD_CATEGORIES = ["Bakery", "Breakfast", "Desserts", "Sandwiches", "Meals"]
BRANCHES = ["Harbour", "Garden", "Uptown"]

# Dayparts follow the hourly order curve (opening 07:00, evening peak 19-23).
DAYPART_BINS = [0, 11, 15, 19, 24]
DAYPARTS = ["Morning", "Midday", "Afternoon", "Evening"]

DATA_FILE = Path("data") / "stories_transactions.csv"


def find_repo_root(start: str | Path | None = None) -> Path:
    """Walk up from `start` until the folder that holds src/storiespair."""
    here = Path(start or Path.cwd()).resolve()
    for folder in [here, *here.parents]:
        if (folder / "src" / "storiespair").is_dir():
            return folder
    raise FileNotFoundError("Could not find the repository root (src/storiespair).")


def daypart(hour: pd.Series) -> pd.Series:
    return pd.cut(hour, bins=DAYPART_BINS, right=False, labels=DAYPARTS).astype(str)


def load_lines(path: str | Path | None = None) -> pd.DataFrame:
    """Load product lines with clean names and time features."""
    path = Path(path) if path else find_repo_root() / DATA_FILE
    df = pd.read_csv(path).rename(columns=RAW_COLUMNS)
    df["dt"] = pd.to_datetime(df["date"] + " " + df["time"])
    df["day"] = df["dt"].dt.normalize()
    df["month"] = df["dt"].dt.month
    df["hour"] = df["dt"].dt.hour
    df["dow"] = df["dt"].dt.dayofweek
    df["daypart"] = daypart(df["hour"])
    df["side"] = np.where(df["category"].isin(DRINK_CATEGORIES), "drink", "food")
    df["known_customer"] = df["customer_id"].notna()
    # Position of the line inside its order (file order). Line order is used as
    # the "first item rung at the till" in the engine replay.
    df["line_pos"] = df.groupby("transaction_id").cumcount()
    return df


def audit(lines: pd.DataFrame) -> pd.DataFrame:
    """The data contract: every check returns a value and a pass/flag verdict."""
    rev = (lines.quantity * lines.unit_price * (1 - lines.discount_rate)).round(2)
    gp = (lines.line_revenue - lines.quantity * lines.unit_cost).round(2)
    dup_key = ["transaction_id", "product", "quantity", "unit_price", "discount_rate"]
    per_order = lines.groupby("transaction_id").agg(
        branches=("branch", "nunique"),
        times=("dt", "nunique"),
        customers=("customer_id", "nunique"),
        order_types=("order_type", "nunique"),
    )
    rows = [
        ("Rows (product lines)", len(lines), "info"),
        ("Orders (Transaction IDs)", lines.transaction_id.nunique(), "info"),
        ("Date range", f"{lines.day.min().date()} to {lines.day.max().date()}", "info"),
        ("Days covered", lines.day.nunique(), "info"),
        ("Line revenue formula mismatches (> $0.02)", int((rev - lines.line_revenue).abs().gt(0.02).sum()), "pass if 0"),
        ("Line gross-profit formula mismatches (> $0.02)", int((gp - lines.line_gp).abs().gt(0.02).sum()), "pass if 0"),
        ("Orders spanning >1 branch / time / customer / order type",
         int((per_order[["branches", "times", "customers", "order_types"]] > 1).any(axis=1).sum()), "pass if 0"),
        ("Repeated product lines inside one order", int(lines.duplicated(dup_key).sum()), "flag"),
        ("Revenue on repeated lines (USD)", round(float(lines.loc[lines.duplicated(dup_key), "line_revenue"].sum()), 2), "flag"),
        ("Max distinct prices per product x branch", int(lines.groupby(["product", "branch"]).unit_price.nunique().max()), "info"),
        ("Max distinct costs per product x branch", int(lines.groupby(["product", "branch"]).unit_cost.nunique().max()), "info"),
        ("Lines with a known customer ID", f"{lines.known_customer.mean():.1%}", "info"),
    ]
    out = pd.DataFrame(rows, columns=["check", "value", "rule"])
    return out


def build_orders(lines: pd.DataFrame) -> pd.DataFrame:
    """One row per order with composition, value and the first item rung."""
    first = lines[lines.line_pos == 0].set_index("transaction_id")
    g = lines.groupby("transaction_id")
    orders = pd.DataFrame(
        {
            "branch": first.branch,
            "dt": first.dt,
            "day": first.day,
            "month": first.month,
            "hour": first.hour,
            "dow": first.dow,
            "daypart": first.daypart,
            "order_type": first.order_type,
            "known_customer": first.known_customer,
            "customer_id": first.customer_id,
            "n_lines": g.size(),
            "n_drink_lines": (lines.side == "drink").groupby(lines.transaction_id).sum().astype(int),
            "revenue": g.line_revenue.sum(),
            "gp": g.line_gp.sum(),
            "first_product": first["product"],
            "first_category": first.category,
            "first_side": first.side,
            "first_price": first.unit_price,
            "first_discount": first.discount_rate,
        }
    )
    orders["n_food_lines"] = orders.n_lines - orders.n_drink_lines
    orders["has_drink"] = orders.n_drink_lines > 0
    orders["has_food"] = orders.n_food_lines > 0
    orders["composition"] = np.select(
        [orders.has_drink & ~orders.has_food, orders.has_food & ~orders.has_drink],
        ["drink only", "food only"],
        default="drink + food",
    )
    # Target for the engine: did the order end up with the *other* side of the pair?
    orders["paired"] = np.where(orders.first_side == "drink", orders.has_food, orders.has_drink)
    orders["weekend"] = orders.dow.isin([5, 6])  # Saturday, Sunday
    return orders.reset_index()


def other_side_first_item(lines: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    """For paired orders: the first product/category from the other side."""
    side_of_first = orders.set_index("transaction_id").first_side
    l2 = lines.join(side_of_first.rename("trigger_side"), on="transaction_id")
    other = l2[l2.side != l2.trigger_side].sort_values(["transaction_id", "line_pos"])
    other = other.groupby("transaction_id")[["product", "category"]].first()
    return other.rename(columns={"product": "added_product", "category": "added_category"})


def timestamp_collisions(orders: pd.DataFrame) -> dict:
    """Test the idea of merging orders that share branch + exact second.

    Compares observed collisions with the number expected if orders arrived at
    random within each branch's opening hours on each day (birthday problem).
    """
    observed = int((orders.groupby(["branch", "dt"]).size() > 1).sum())
    per_day = orders.groupby(["branch", "day"]).size()
    seconds_open = 17 * 3600  # 07:00 to 24:00
    expected = float((per_day * (per_day - 1) / 2 / seconds_open).sum())
    return {"observed_collisions": observed, "expected_by_chance": round(expected, 1)}


def unit_economics(lines: pd.DataFrame) -> pd.DataFrame:
    """List price, unit cost and unit gross profit per product x branch."""
    u = (
        lines.groupby(["branch", "product", "category", "side"])
        .agg(price=("unit_price", "first"), cost=("unit_cost", "first"), units=("quantity", "sum"))
        .reset_index()
    )
    u["unit_gp"] = u.price - u.cost
    u["margin"] = u.unit_gp / u.price
    return u
