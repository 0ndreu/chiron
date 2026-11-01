"""backtest engine: a daily loop over holdings.

a signal row with any number is an order (NaN in it = 0); a row of only NaN means hold.
an order from the close of day t fills at the close of day t+1.
each traded ETF costs fee + spread_bps of the traded amount.
on an order day, an ETF whose gap to its target is under min_trade of the portfolio is not traded.
"""
import numpy as np
import pandas as pd

DAYS = 252


def backtest(prices, weights, capital=5000.0, fee=1.0, spread_bps=0.0, min_trade=0.01):
    """prices: adjusted closes. weights: signal output, same index and columns.
    returns one row per day: value, cost, orders."""
    if prices.isna().any().any():
        raise ValueError("prices have gaps")
    w = weights.reindex(index=prices.index, columns=prices.columns).to_numpy(dtype=float)
    order = ~np.isnan(w).all(axis=1)
    w = np.nan_to_num(w)
    if (w < 0).any() or (w.sum(axis=1) > 1 + 1e-9).any():
        raise ValueError("weights must be >= 0 with row sum <= 1")

    growth = (prices / prices.shift(1)).fillna(1.0).to_numpy()
    pos = np.zeros(w.shape[1])  # money in each ETF
    cash = capital
    rows = []
    for t in range(len(growth)):
        pos *= growth[t]
        cost, orders = 0.0, 0
        if t > 0 and order[t - 1]:
            value = cash + pos.sum()
            trade = w[t - 1] * value - pos
            trade[np.abs(trade) < min_trade * value] = 0.0
            orders = np.count_nonzero(trade)
            cost = orders * fee + np.abs(trade).sum() * spread_bps / 1e4
            pos += trade
            cash -= trade.sum() + cost  # fees come out of cash: it can dip below 0 by the last fees
        rows.append((cash + pos.sum(), cost, orders))
    return pd.DataFrame(rows, index=prices.index, columns=["value", "cost", "orders"])


def daily_sharpe(ret):
    """mean / std of daily returns, 0% risk-free. all cash -> 0, not NaN."""
    sd = ret.std()
    return ret.mean() / sd if sd > 0 else 0.0


def metrics(result):
    """report numbers for a backtest result. sharpe is yearly; drawdown is a positive fraction."""
    value = result["value"]
    ret = value.pct_change().dropna()
    years = len(ret) / DAYS
    vol = ret.std() * np.sqrt(DAYS)
    return {
        "sharpe": daily_sharpe(ret) * np.sqrt(DAYS),
        "cagr": (value.iloc[-1] / value.iloc[0]) ** (1 / years) - 1,
        "vol": vol,
        "maxdd": (1 - value / value.cummax()).max(),
        "orders_per_year": result["orders"].sum() / years,
        "cost_per_year": result["cost"].sum() / value.mean() / years,
    }


def benchmark(prices, classes):
    """1/3 per asset class, equal weight inside each class, rebalanced quarterly."""
    return quarterly(prices, {t: 1 / len(classes) / len(ts) for ts in classes.values() for t in ts})


def quarterly(prices, target):
    """an order to the `target` weights on the first trading day of each quarter; other rows hold."""
    target = pd.Series(target)
    quarter = pd.Series(prices.index.to_period("Q"), index=prices.index)
    new_quarter = (quarter != quarter.shift(1)).to_numpy()
    w = pd.DataFrame(np.nan, index=prices.index, columns=prices.columns)
    w.loc[new_quarter] = target.reindex(prices.columns).to_numpy()
    return w
