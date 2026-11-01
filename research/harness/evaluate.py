"""step 4 walk-forward and the Deflated Sharpe (builder notes)."""
import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm

from harness.checks import center, grid_points
from harness.engine import DAYS, backtest, daily_sharpe

EULER = 0.5772156649


def pick(runs, grid, before):
    """index of the grid point with the best net Sharpe on the days before `before`; ties -> nearest the center."""
    points, mid = grid_points(grid), center(grid)
    dist = [sum(abs(grid[k].index(p[k]) - grid[k].index(mid[k])) for k in grid) for p in points]
    sharpe = [daily_sharpe(r["value"].pct_change()[r.index < before].dropna()) for r in runs]
    return max(range(len(points)), key=lambda j: (sharpe[j], -dist[j]))


def run_from(prices, weights, start, **costs):
    """a backtest that starts at `start` with fresh capital: on the day before start it orders
    the weights' last order row up to then, so day one holds the strategy's current target."""
    i = prices.index.searchsorted(start)
    w = weights.reindex(index=prices.index, columns=prices.columns).iloc[i - 1:].copy()
    before = weights.reindex(index=prices.index[:i], columns=prices.columns).dropna(how="all")
    if len(before):
        w.iloc[0] = before.iloc[-1]
    return backtest(prices.iloc[i - 1:], w, **costs).iloc[1:]


def walk_forward(weights, prices, grid, start, months=6, **costs):
    """weights: one frame per grid point (grid_points order), computed on all prices.
    every `months` from start, pick a grid point on all earlier days and trade its weights until the next pick.
    on each pick day the portfolio moves to the pick's current target, as `run_from` does on the first day,
    and the stitched weights run through the engine once, so a switch pays its trades.
    returns (result from start with fresh capital, picks as [(day, params)], one full run per grid point)."""
    runs = [backtest(prices, w, **costs) for w in weights]
    dates = pd.date_range(start, prices.index[-1], freq=pd.DateOffset(months=months))
    cuts = prices.index[prices.index.searchsorted(dates)]
    picked = [pick(runs, grid, c) for c in cuts]
    choice = np.full(len(prices), picked[0])
    for c, j in zip(cuts, picked):
        choice[prices.index >= c] = j
    full = [w.reindex(index=prices.index, columns=prices.columns) for w in weights]
    stitched = pd.DataFrame(np.stack([w.to_numpy(float) for w in full])[choice, np.arange(len(prices))],
                            index=prices.index, columns=prices.columns)
    for c, j in zip(cuts, picked):
        i = prices.index.get_loc(c)
        before = full[j].iloc[:i].dropna(how="all")
        if len(before):  # an order on the day before the pick fills on the pick day
            stitched.iloc[i - 1] = before.iloc[-1]
    return run_from(prices, stitched, cuts[0], **costs), [(c, grid_points(grid)[j]) for c, j in zip(cuts, picked)], runs


def return_stats(ret):
    """what the Deflated Sharpe needs from daily returns. kurt is non-excess."""
    return {"sr": daily_sharpe(ret), "skew": ret.skew(), "kurt": ret.kurt() + 3, "t": len(ret)}


def expected_max_sharpe(n, var):
    """SR*: the best daily Sharpe that n independent tries reach by luck (Bailey & López de Prado, 2014)."""
    if n <= 1:
        return 0.0
    return np.sqrt(var) * ((1 - EULER) * norm.ppf(1 - 1 / n) + EULER * norm.ppf(1 - 1 / (n * np.e)))


def deflated_sharpe(stats, n, var=None):
    """probability that the true Sharpe is above SR*. n: families. var: None -> 1/T."""
    sr, t = stats["sr"], stats["t"]
    sr0 = expected_max_sharpe(n, 1 / t if var is None else var)
    return norm.cdf((sr - sr0) * np.sqrt(t - 1) / np.sqrt(1 - stats["skew"] * sr + (stats["kurt"] - 1) / 4 * sr**2))


def sharpe_needed(n, t, var=None, threshold=0.80):
    """the yearly Sharpe that reaches the threshold with n families over t days (normal returns)."""
    sr0 = expected_max_sharpe(n, 1 / t if var is None else var)
    return brentq(lambda sr: deflated_sharpe({"sr": sr, "skew": 0, "kurt": 3, "t": t}, n, var) - threshold, sr0, 1) * np.sqrt(DAYS)
