"""Stories Pair: a margin-aware pairing engine built on Stories Coffee transactions.

Modules
-------
data      load the CSV, run the data contract, rebuild one-row-per-order tables
evidence  statistical tests for product- and category-level pairing
models    receptiveness (attach) model and category-choice model
engine    candidate generation, expected-profit scoring, combo pricing, guardrails
simulate  policy replay, sensitivity analysis, pilot power analysis
viz       shared chart style
"""

__version__ = "1.0.0"
