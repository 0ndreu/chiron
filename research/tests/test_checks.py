"""step 3 checks: the truncation test (gate), the novelty check, failure_if and card intake."""
import numpy as np
import pandas as pd
import pytest

from harness.checks import FIELDS, Refused, check_card, failure_met, idea_checks, novelty, parse_line, truncation_failure
from harness.engine import backtest

TICKERS = ["SPY", "IWM", "EFA", "EEM", "SHY", "IEF", "TLT", "TIP", "LQD", "HYG", "IYR", "GLD", "DBC"]
_idx = pd.bdate_range("2007-04-02", "2011-12-30")
PRICES = pd.DataFrame(100 * np.exp(np.cumsum(np.random.default_rng(0).normal(0.0002, 0.01, (len(_idx), 13)), axis=0)),
                      index=_idx, columns=TICKERS)


def walkthrough_signal(look_at_next_row, centered_vol=False):
    """the example trend signal: v1 has the bug, v2 the fix."""
    def signal(prices, lookback=126, weighting="equal"):
        past_return = prices / prices.shift(lookback) - 1
        held = past_return > 0
        if weighting == "equal":
            raw = held.astype(float)
        else:
            vol = prices.pct_change().rolling(63, center=centered_vol).std()
            raw = held / vol
        weights = raw.div(raw.sum(axis=1), axis=0).fillna(0.0)
        month = pd.Series(prices.index.to_period("M"), index=prices.index)
        is_trade_day = month != month.shift(-1 if look_at_next_row else 1)
        return weights.where(is_trade_day, axis=0)
    return signal


def test_truncation_catches_the_walkthrough_bug_and_passes_the_fix():
    grid = {"lookback": [63, 126, 189, 252], "weighting": ["equal", "inverse_vol"]}
    assert truncation_failure(walkthrough_signal(look_at_next_row=True), PRICES, grid) is not None
    assert truncation_failure(walkthrough_signal(look_at_next_row=False), PRICES, grid) is None
    # a leak in one branch only: the grid center (126, equal) never runs it
    assert truncation_failure(walkthrough_signal(look_at_next_row=False, centered_vol=True), PRICES, grid) is not None


def test_truncation_catches_a_lookahead_that_shows_only_on_order_days():
    def signal(prices):
        tomorrow_up = (prices.shift(-1) > prices).astype(float) / 13  # the leak
        month = pd.Series(prices.index.to_period("M"), index=prices.index)
        return tomorrow_up.where(month != month.shift(1), axis=0)  # rows on ~1 day in 21

    # random days alone would miss it with ~38% chance per run
    assert all(truncation_failure(signal, PRICES, {}, seed=s) is not None for s in range(10))


def train_returns(ticker):
    weights = pd.DataFrame({ticker: 1.0}, index=PRICES.index).reindex(columns=TICKERS)
    return backtest(PRICES, weights)["value"].pct_change().dropna()


def test_novelty_joins_the_same_idea_starts_a_new_family_and_refuses_a_full_one():
    spy = train_returns("SPY")
    assert novelty(spy, {"F-001": (spy, 1)}) == "F-001"
    assert novelty(train_returns("GLD"), {"F-001": (spy, 1)}) is None
    with pytest.raises(Refused, match="full"):
        novelty(spy, {"F-001": (spy, 3)})


@pytest.mark.parametrize("line", ["val_sharpe <= bench", "val_sharpe == 0.5", "sharpe < 1", "val_maxdd > 15%", "val_sharpe < 1 or dsr < 1", ""])
def test_failure_if_refuses_bad_lines(line):
    with pytest.raises(Refused):
        parse_line(line)


def test_failure_if_is_met_when_any_line_holds_and_on_nan():
    report = dict.fromkeys(FIELDS, 0.0) | {"val_sharpe": 0.58, "bench_sharpe": 0.52, "val_maxdd": 0.13, "bench_maxdd": 0.21}
    assert not failure_met(["val_sharpe <= bench_sharpe", "val_maxdd >= bench_maxdd"], report)
    assert failure_met(["val_sharpe <= bench_sharpe", "val_maxdd > 0.1"], report)
    assert failure_met(["val_sharpe < -1"], report | {"val_sharpe": float("nan")})


IDEAS = """\
I-001 | new | user | risk | Hold the calm half | why | checks: orders_per_year > 12; val_maxdd>0.15
I-002 | new | user | risk | Hold bonds when stocks fall | why | checks: val_maxdd > 15%
"""
CARD = {
    "id": "H-2026-11-04-calm-half", "parent": None, "source": "I-001", "idea": "...", "premium": "risk",
    "rationale": "...", "rule": "...", "grid": {"lookback": [63, 126, 252], "top": [0.5, 0.33]}, "expected": "...",
    "failure_if": ["val_sharpe <= bench_sharpe", "orders_per_year > 12", "val_maxdd > 0.15"], "libraries": [],
}


def test_intake_enforces_the_users_checks():
    checks = idea_checks(IDEAS, "I-001")
    check_card(CARD, checks)  # copied with other spacing: still the same check
    with pytest.raises(Refused, match="dropped the user's checks"):
        check_card(CARD | {"failure_if": ["val_sharpe <= bench_sharpe", "orders_per_year > 12"]}, checks)
    with pytest.raises(Refused, match="the user must fix it"):
        idea_checks(IDEAS, "I-002")


@pytest.mark.parametrize("change, error", [
    ({"id": "../harness/engine"}, "id must look like"),
    ({"grid": {"a": [1, 2, 3, 4], "b": [1, 2, 3, 4]}}, "at most 12"),
    ({"failure_if": []}, "non-empty"),
    ({"failure_if": ["dsr < 0.8"] * 7}, "at most 6 lines"),  # a longer report breaks the 20-line rule
    ({"libraries": ["sklearn"]}, "approval"),
])
def test_intake_refuses_a_bad_card(change, error):
    with pytest.raises(Refused, match=error):
        check_card(CARD | change)
