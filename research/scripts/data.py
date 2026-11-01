"""daily adjusted closes for the 13 ETFs (universe.yaml): Tiingo download, quality check, split into the stores.

    TIINGO_API_KEY=... python -m scripts.data      (host only; the key never goes into the repo)

writes data/all/prices.csv (host only: validation, holdout, forward) and data/train/prices.csv (the agent's copy).
bad data stops the run and writes nothing: the last good stores stay.
"""
import os
import sys
from pathlib import Path

import pandas as pd
import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
TIINGO = "https://api.tiingo.com/tiingo/daily/{}/prices"
SPIKE, BACK, FROZEN = 0.15, 0.05, 5  # a jump over 15% that comes back within 5% the next day; 5 equal closes, no trades


def fetch(ticker, key):
    """the full history of one ticker: adjusted close and volume. full every time: a new dividend rescales the whole
    adjusted history, so new days appended to an old copy would lose that dividend."""
    r = requests.get(TIINGO.format(ticker), params={"startDate": "1990-01-01"},
                     headers={"Authorization": f"Token {key}"}, timeout=60)
    r.raise_for_status()
    rows = r.json()
    return pd.DataFrame({"price": [row["adjClose"] for row in rows], "volume": [row["volume"] for row in rows]},
                        index=pd.to_datetime([row["date"][:10] for row in rows]), dtype=float)


def problems(prices, volume):
    """bad prices: a gap, zero or negative, a frozen run of equal closes with no trades, a spike that reverses
    the next day. a real crash doesn't come back the next day; a flat price with trades is real (SHY at near-zero rates)."""
    found = []
    for ticker, p in prices.items():
        found += [f"{ticker} {d.date()}: no price" for d in p.index[p.isna()]]
        found += [f"{ticker} {d.date()}: price {v}" for d, v in p[p <= 0].items()]
        same = p == p.shift()
        run_id = (~same).cumsum()
        run = p.groupby(run_id).transform("size")
        traded = volume[ticker].where(same, 0).groupby(run_id).transform("sum")  # shares on the repeated days
        found += [f"{ticker} {d.date()}: the same close {FROZEN}+ days, no trades"
                  for d in p.index[(run >= FROZEN) & ~same & (traded <= 0)]]
        jump, back = p / p.shift() - 1, (p.shift(-1) / p.shift() - 1).abs()
        found += [f"{ticker} {d.date()}: jump {j:+.0%} that reverses the next day"
                  for d, j in jump[(jump.abs() > SPIKE) & (back < BACK)].items()]
    return found


def update(root, fetch):
    """download, check, split. returns the problems found (empty: the stores were written)."""
    periods = yaml.safe_load((root / "lab.yaml").read_text())["periods"]
    tickers = [t for ts in yaml.safe_load((root / "universe.yaml").read_text()).values() for t in ts]
    raw = {t: fetch(t) for t in tickers}
    for t, d in raw.items():
        print(f"{t}: first day {d.index.min().date()}, last day {d.index.max().date()}")
    start = max([d.index.min() for d in raw.values()] + [pd.Timestamp(periods["train"])])
    end = min(d.index.max() for d in raw.values())  # the last day every ETF has a price
    prices, volume = (pd.concat({t: d[col] for t, d in raw.items()}, axis=1).sort_index().loc[start:end] for col in ("price", "volume"))
    if found := problems(prices, volume):
        return found
    for name, part in (("all", prices), ("train", prices[prices.index < pd.Timestamp(periods["validation"])])):
        path = root / "data" / name / "prices.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        part.to_csv(path.with_suffix(".tmp"))
        path.with_suffix(".tmp").replace(path)  # a crash mid-write never leaves a broken store
    print(f"stored {start.date()} -> {end.date()}, {len(prices)} days")
    return []


if __name__ == "__main__":
    key = os.environ.get("TIINGO_API_KEY") or sys.exit("set TIINGO_API_KEY")
    if found := update(ROOT, lambda ticker: fetch(ticker, key)):
        sys.exit("bad data, nothing written:\n" + "\n".join(found))
