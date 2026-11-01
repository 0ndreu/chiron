"""the data script: the quality check (gate: a planted bad bar is flagged) and the split into the stores."""
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from scripts.data import problems, update

RESEARCH = Path(__file__).resolve().parents[1]
IDX = pd.bdate_range("2007-04-02", "2012-06-29")


def clean():
    """13 random walks with a 2008-like crash: -20% in one day that doesn't come back."""
    returns = np.random.default_rng(0).normal(0, 0.01, (len(IDX), 13))
    returns[IDX == "2008-10-06"] = np.log(0.8)
    tickers = [f"E{i}" for i in range(13)]
    return pd.DataFrame(100 * np.exp(np.cumsum(returns, axis=0)), index=IDX, columns=tickers)


def volume():
    return pd.DataFrame(1e6, index=IDX, columns=[f"E{i}" for i in range(13)])


def plant(kind):
    p = clean()
    day = IDX.get_loc(pd.Timestamp("2010-05-04"))
    if kind == "jump":
        p.iloc[day, 3] *= 1.4  # one wrong bar, the next day is normal again
    elif kind == "zero":
        p.iloc[day, 3] = 0.0
    elif kind in ("frozen", "flat with trades"):
        p.iloc[day:day + 5, 3] = p.iloc[day, 3]
    elif kind == "gap":
        p.iloc[day, 3] = np.nan
    return p


def test_clean_prices_with_a_real_crash_or_a_traded_flat_price_pass():
    assert problems(clean(), volume()) == []
    assert problems(plant("flat with trades"), volume()) == []  # SHY 2012-12-05: 84.45 for 5 days, ~1 M shares a day


@pytest.mark.parametrize("kind, message", [("jump", "jump +"), ("zero", "price 0.0"), ("frozen", "same close"), ("gap", "no price")])
def test_a_planted_bad_bar_is_flagged(kind, message):
    shares = volume()
    if kind == "frozen":
        shares.loc["2010-05-05":"2010-05-10", "E3"] = 0  # stale data: the price repeats and nobody trades
    found = problems(plant(kind), shares)
    assert any(message in line for line in found) and all(line.startswith("E3 2010-05-0") for line in found)


def run_update(tmp_path, prices):
    shutil.copy(RESEARCH / "universe.yaml", tmp_path)
    if not (tmp_path / "lab.yaml").exists():
        shutil.copy(RESEARCH / "lab.yaml", tmp_path)
    tickers = [t for ts in yaml.safe_load((tmp_path / "universe.yaml").read_text()).values() for t in ts]
    prices = prices.set_axis(tickers, axis=1)
    return update(tmp_path, lambda t: pd.DataFrame({"price": prices[t], "volume": 1e6}).dropna())


def test_the_agent_store_ends_before_validation_and_both_start_when_all_etfs_trade(tmp_path):
    prices = clean()
    prices.iloc[:5, 9] = np.nan  # one ETF starts later (like HYG)
    prices.iloc[-1, 0] = np.nan  # one ETF has no price yet for the last day
    assert run_update(tmp_path, prices) == []
    all_days = pd.read_csv(tmp_path / "data/all/prices.csv", index_col=0, parse_dates=True)
    train = pd.read_csv(tmp_path / "data/train/prices.csv", index_col=0, parse_dates=True)
    assert train.index.max() < pd.Timestamp("2012-01-01") and train.index.min() == IDX[5]
    assert all_days.index.min() == IDX[5] and all_days.index.max() == IDX[-2]
    assert not all_days.isna().any().any()


def test_a_period_that_starts_on_a_trading_day_is_not_in_the_agent_store(tmp_path):
    assert run_update(tmp_path, clean()) == []
    (tmp_path / "lab.yaml").write_text((tmp_path / "lab.yaml").read_text().replace("validation: 2012-01-01", "validation: 2012-01-03"))
    assert run_update(tmp_path, clean()) == []
    train = pd.read_csv(tmp_path / "data/train/prices.csv", index_col=0, parse_dates=True)
    assert train.index.max() == pd.Timestamp("2012-01-02")  # a Tuesday start: Monday is the agent's last day


def test_bad_data_writes_nothing(tmp_path):
    assert run_update(tmp_path, plant("zero")) != []
    assert not (tmp_path / "data").exists()
