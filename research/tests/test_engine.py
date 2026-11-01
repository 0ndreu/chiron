"""known-answer tests for the engine (its ship gate). expected values are hand formulas from the cost model."""
import numpy as np
import pandas as pd
import pytest

from harness.engine import backtest, metrics

CAPITAL, FEE, BPS = 5000.0, 1.0, 10.0
HOLD = [np.nan, np.nan]


def frame(rows):
    return pd.DataFrame(rows, index=pd.bdate_range("2020-01-01", periods=len(rows)), columns=["A", "B"], dtype=float)


def run(prices, weights):
    return backtest(prices, weights, capital=CAPITAL, fee=FEE, spread_bps=BPS)


@pytest.mark.parametrize("then", ["hold", "repeat the order"])
def test_buy_and_hold_earns_the_return_from_the_fill_minus_the_entry_cost(then):
    # A jumps 10% on the fill day; a same-day fill would wrongly earn that jump
    prices = frame([[100, 50], [110, 50], [99, 50], [121, 50]])
    later = HOLD if then == "hold" else [1, 0]
    result = run(prices, frame([[1, 0]] + [later] * 3))

    entry_cost = FEE + CAPITAL * BPS / 1e4
    assert result["value"].iloc[-1] == pytest.approx(CAPITAL * 121 / 110 - entry_cost)
    assert result["orders"].tolist() == [0, 1, 0, 0]  # drift after the fill stays under 1%


@pytest.mark.parametrize("weight", [0.0, np.nan])
def test_zero_weights_give_zero_return_and_zero_cost(weight):
    prices = frame([[100, 50], [110, 40], [90, 60]])
    result = run(prices, frame([[weight, weight]] * 3))

    assert (result["value"] == CAPITAL).all()
    assert result["cost"].sum() == 0


def test_a_rebalance_costs_exactly_fee_per_order_plus_spread():
    prices = frame([[100, 100]] * 6)
    result = run(prices, frame([[0.5, 0.5], HOLD, HOLD, [0.52, 0.48], HOLD, HOLD]))

    entry_cost = 2 * FEE + CAPITAL * BPS / 1e4
    value = CAPITAL - entry_cost
    traded = abs(0.52 * value - 2500) + abs(0.48 * value - 2500)  # ~€200: the €1 fees dominate
    rebalance_cost = 2 * FEE + traded * BPS / 1e4
    assert result["cost"].tolist() == pytest.approx([0, entry_cost, 0, 0, rebalance_cost, 0])
    assert result["value"].iloc[-1] == pytest.approx(value - rebalance_cost)


def test_a_gap_under_1pct_of_the_portfolio_is_not_traded():
    prices = frame([[100, 100]] * 6)
    # A's gap is 0.5% of the portfolio (skipped), B's is ~5% (traded)
    result = run(prices, frame([[0.5, 0.5], HOLD, HOLD, [0.505, 0.45], HOLD, HOLD]))

    value = CAPITAL - (2 * FEE + CAPITAL * BPS / 1e4)
    assert result["orders"].iloc[4] == 1
    assert result["cost"].iloc[4] == pytest.approx(FEE + abs(0.45 * value - 2500) * BPS / 1e4)


def test_metrics_known_answer():
    result = pd.DataFrame({"value": [100.0, 110, 99, 121], "cost": [0, 1.0, 0, 0], "orders": [0, 1, 0, 0]},
                          index=pd.bdate_range("2020-01-01", periods=4))
    r, years = np.array([0.1, -0.1, 22 / 99]), 3 / 252
    m = metrics(result)
    assert m["sharpe"] == pytest.approx(r.mean() / r.std(ddof=1) * np.sqrt(252))  # yearly: x sqrt(252), not x 252
    assert m["maxdd"] == pytest.approx(0.1)  # 110 -> 99
    assert m["orders_per_year"] == pytest.approx(1 / years)
    assert m["cost_per_year"] == pytest.approx(1 / np.mean([100, 110, 99, 121]) / years)  # a fraction, not euros
