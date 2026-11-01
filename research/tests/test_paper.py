"""the paper portfolio: forward from week 1 with fresh capital, the retirement rules (program.md 10)."""
import datetime as dt
import json

import numpy as np
import pandas as pd

from harness.engine import quarterly
from harness.evaluate import run_from
from harness.lab import Lab
from scripts.paper import line, retire_reason, run
from tests.test_lab import HID, decide, make_root, submit


def values(daily_returns, start="2026-01-01"):
    idx = pd.bdate_range(start, periods=len(daily_returns) + 1)
    value = 5000 * np.cumprod(np.r_[1, 1 + np.asarray(daily_returns)])
    return pd.DataFrame({"value": value, "cost": 0.0, "orders": 0}, index=idx)


def test_a_sleeve_retires_on_a_deep_drawdown_or_after_52_weak_weeks():
    calm = values([0.001, -0.001] * 150)
    assert retire_reason(values([0.001] * 20 + [-0.02] * 20), calm, bench_val_maxdd=0.2) is not None  # ~33% > 30%
    assert retire_reason(values([0.001] * 20 + [-0.01] * 20), calm, bench_val_maxdd=0.2) is None  # ~18% < 30%
    weak = values([0.0005, -0.0005] * 135)  # 54 weeks, sharpe ~0
    strong = values([0.002, -0.0005] * 135)
    assert "52 weeks" in retire_reason(weak, strong, bench_val_maxdd=0.2)
    assert retire_reason(weak.iloc[:200], strong.iloc[:200], bench_val_maxdd=0.2) is None  # under 52 weeks: too early


def test_the_paper_portfolio_runs_forward_and_retires_by_the_rules(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_SANDBOX", "local")
    root = make_root(tmp_path)
    submit(root)
    Lab(root, dt.date(2026, 11, 4)).run()
    decide(root, "decision: candidate\nreason: not met\n")
    lab = Lab(root, dt.date(2026, 11, 6))
    lab.run()
    lab.db.execute("update sleeves set started = date '2026-09-01'")  # as if promoted two months after week 1
    prices, week_1 = lab.prices("2100-01-01"), pd.Timestamp("2026-07-01")
    sixty_forty = line("60/40 SPY/IEF (context only)", run_from(prices, quarterly(prices, {"SPY": 0.6, "IEF": 0.4}), week_1, **lab.costs), 5000)
    lab.db.close()

    summary = run(root, summary=True, today=dt.date(2026, 11, 6)).splitlines()
    assert summary[1].startswith("benchmark: ") and "since 2026-07-01" in summary[1]
    assert summary[2] == sixty_forty
    assert summary[3].startswith(f"S-1 {HID}: ") and "since 2026-09-01" in summary[3] and "benchmark since then" in summary[3]
    assert "lookback" not in (root / "reports/paper.md").read_text()  # no params: picked with holdout data

    lab = Lab(root, dt.date(2026, 11, 9))  # make the drawdown limit tiny: the sleeve must retire
    report = json.loads(lab.db.execute("select report from hypotheses where id = ?", [HID]).fetchone()[0])
    lab.db.execute("update hypotheses set report = ? where id = ?", [json.dumps(report | {"bench_maxdd": 1e-4}), HID])
    lab.db.close()
    assert "S-1" in run(root, today=dt.date(2026, 11, 9)) and "retired" in (root / "journal/outbox.md").read_text()
    lab = Lab(root, dt.date(2026, 11, 9))
    assert lab.db.execute("select retired from sleeves").fetchone()[0] == dt.date(2026, 11, 9)
