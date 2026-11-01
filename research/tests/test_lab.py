"""steps 4-6 and the registry: the walkthrough end to end, walk-forward, the DSR, step 6, the stop rule, the user's checks."""
import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from harness import sandbox
from harness.engine import benchmark, metrics
from harness.evaluate import deflated_sharpe, expected_max_sharpe, return_stats, run_from, sharpe_needed, walk_forward
from harness.lab import Lab

RESEARCH = Path(__file__).resolve().parents[1]
HID = "H-2026-11-04-trend-monthly"
CARD = {
    "id": HID, "parent": None, "source": "I-001", "idea": "Hold what trends up.", "premium": "behavioral",
    "rationale": "investors under-react", "rule": "monthly: hold the ETFs with a positive lookback return",
    "grid": {"lookback": [63, 126, 189, 252], "weighting": ["equal", "inverse_vol"]}, "expected": "...",
    "failure_if": ["val_sharpe <= bench_sharpe", "val_maxdd >= bench_maxdd", "orders_per_year > 60"], "libraries": [],
}
TREND = '''import pandas as pd

def signal(prices, lookback=126, weighting="equal"):
    past_return = prices / prices.shift(lookback) - 1
    held = past_return > 0
    if weighting == "equal":
        raw = held.astype(float)
    else:
        vol = prices.pct_change().rolling(63).std()
        raw = held / vol
    weights = raw.div(raw.sum(axis=1), axis=0).fillna(0.0)
    month = pd.Series(prices.index.to_period("M"), index=prices.index)
    is_trade_day = month != month.shift(LOOK)
    return weights.where(is_trade_day, axis=0)
'''
FIXED, BUGGY = TREND.replace("LOOK", "1"), TREND.replace("LOOK", "-1")


def make_root(path, holdout_drift=None):
    """a lab folder with made-up trending prices: each ETF's drift flips between +-40%/year in ~2-year blocks."""
    shutil.copy(RESEARCH / "universe.yaml", path)
    tickers = [t for ts in yaml.safe_load((path / "universe.yaml").read_text()).values() for t in ts]
    idx = pd.bdate_range("2007-04-02", "2026-10-30")
    rng = np.random.default_rng(1)
    drift = np.where(rng.random((len(idx) // 500 + 1, 13)) < 0.5, 0.4, -0.4)[np.arange(len(idx)) // 500] / 252
    if holdout_drift is not None:
        drift[(idx >= "2026-01-01") & (idx < "2026-07-01")] = holdout_drift / 252
    noise = rng.normal(0, 0.15 / np.sqrt(252), (len(idx), 13))
    (path / "data/all").mkdir(parents=True)
    pd.DataFrame(100 * np.exp(np.cumsum(drift + noise, axis=0)), index=idx, columns=tickers).to_csv(path / "data/all/prices.csv")
    lab_yaml = (RESEARCH / "lab.yaml").read_text()
    (path / "lab.yaml").write_text(lab_yaml.replace("holdout: null", "holdout: 2026-01-01").replace("week_1: null", "week_1: 2026-07-01"))
    (path / "ideas.md").write_text("I-001 | testing H | seed | behavioral | Time-series trend | MOP 2012 | checks: orders_per_year > 60\n")
    return path


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_SANDBOX", "local")
    return make_root(tmp_path)


def submit(root, code=FIXED, hid=HID):
    inbox = root / "strategies/inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / f"{hid}.yaml").write_text(yaml.safe_dump(CARD | {"id": hid}))
    (inbox / f"{hid}.py").write_text(code)


def decide(root, text, hid=HID):
    (root / "strategies/decisions").mkdir(parents=True, exist_ok=True)
    (root / f"strategies/decisions/{hid}.yaml").write_text(text)


def statuses(lab):
    return dict(lab.db.execute("select id, status from hypotheses").fetchall())


def test_sharpe_bar_matches_the_walkthrough_table():
    assert [round(sharpe_needed(n, 14 * 252), 2) for n in (1, 2, 5, 10, 20)] == [0.22, 0.36, 0.54, 0.65, 0.73]


def test_deflated_sharpe_matches_the_papers_example():
    # Bailey & López de Prado (2014), numerical example: SR 2.5 a year, T = 1250 days, skew -3, kurtosis 10,
    # N = 100 trials, V = 0.5 a year. 0.1132 and 0.9004 are the paper's results as remembered: check against the pdf
    var = 0.5 / 250
    assert expected_max_sharpe(100, var) == pytest.approx(0.1132, abs=1e-4)
    assert deflated_sharpe({"sr": 2.5 / np.sqrt(250), "skew": -3, "kurt": 10, "t": 1250}, 100, var) == pytest.approx(0.9004, abs=1e-4)
    normal = return_stats(pd.Series(np.random.default_rng(0).normal(size=100_000)))
    assert normal["kurt"] == pytest.approx(3, abs=0.1)  # non-excess: a normal distribution has 3


def test_walk_forward_picks_from_the_past_only_and_trades_each_pick():
    idx = pd.bdate_range("2010-01-01", "2013-12-31")
    after = idx >= "2012-01-01"
    drift = np.column_stack([np.where(after, 0, 0.3), np.where(after, 0.6, 0)]) / 252  # A rises before 2012, B after
    noise = np.random.default_rng(0).normal(0, 0.001, (len(idx), 2))
    prices = pd.DataFrame(100 * np.exp(np.cumsum(drift + noise, axis=0)), index=idx, columns=["A", "B"])
    hold = [pd.DataFrame({t: 1.0}, index=idx).reindex(columns=["A", "B"]) for t in "AB"]
    result, picks, _ = walk_forward(hold, prices, {"hold": ["A", "B"]}, pd.Timestamp("2012-01-01"))
    assert picks[0][1] == {"hold": "A"} and picks[-1][1] == {"hold": "B"}  # B wins on all data, A on the past
    first_window = result["value"].loc[:"2012-06-29"]
    assert abs(first_window.iloc[-1] / first_window.iloc[0] - 1) < 0.05  # it traded A (flat), not B (+30%)

    _, picks, _ = walk_forward([hold[0]] * 3, prices, {"x": [1, 2, 3]}, pd.Timestamp("2012-01-01"))
    assert all(params == {"x": 2} for _, params in picks)  # equal results: the grid center

    sparse = [w.where(pd.Series(w.index == idx[0], index=idx), axis=0) for w in hold]  # one order, then hold
    result, picks, _ = walk_forward(sparse, prices, {"hold": ["A", "B"]}, pd.Timestamp("2012-01-01"))
    assert result["orders"].iloc[0] == 1  # day one holds the first pick's target
    after = result["value"].loc["2013-07-01":]
    assert picks[-1][1] == {"hold": "B"} and after.iloc[-1] / after.iloc[0] - 1 > 0.2  # it moved to B (+~30%), not A (flat)


def test_each_test_period_starts_with_fresh_capital_holding_the_current_target():
    idx = pd.bdate_range("2020-01-01", periods=8)
    prices = pd.DataFrame({"A": [100, 100, 200, 200, 200, 220, 220, 220], "B": 100.0}, index=idx)
    weights = pd.DataFrame(np.nan, index=idx, columns=["A", "B"])
    weights.iloc[0] = [1, 0]  # the last order was long before the start
    result = run_from(prices, weights, idx[4], capital=5000, fee=1.0)
    assert result.index[0] == idx[4]
    assert result["value"].iloc[0] == pytest.approx(5000 - 1)  # not the ~€10,000 that A grew to after its first fill
    assert result["value"].iloc[-1] == pytest.approx(5000 * 220 / 200 - 1)


def test_the_walkthrough_idea_goes_from_the_inbox_to_a_paper_sleeve(root):
    submit(root)
    Lab(root, dt.date(2026, 11, 4)).run()
    report = (root / f"reports/{HID}.md").read_text().splitlines()
    assert len(report) <= 20 and "failure_if: NOT MET" in report
    lab = Lab(root, dt.date(2026, 11, 4))
    prices = lab.prices("2026-01-01")
    start = prices.index[prices.index >= "2012-01-01"][0]
    bench = metrics(run_from(prices, benchmark(prices, lab.classes), start, **lab.costs))["sharpe"]
    saved = json.loads(lab.db.execute("select report from hypotheses").fetchone()[0])
    assert saved["bench_sharpe"] == pytest.approx(bench)  # measured on validation days, from €5,000
    lab.db.close()
    assert (root / f"strategies/archive/{HID}.py").exists() and not (root / f"strategies/inbox/{HID}.py").exists()

    decide(root, "decision: candidate\nreason: not met\n")
    submit(root, hid="H-2026-11-06-trend-again")  # the same idea again, after its family used the holdout
    lab = Lab(root, dt.date(2026, 11, 6))
    lab.run()
    assert lab.db.execute("select hypothesis from sleeves where retired is null").fetchall() == [(HID,)]
    assert "F-001 | promoted | tries 1/3" in (root / "reports/families.md").read_text()
    outbox = (root / "journal/outbox.md").read_text().splitlines()
    assert f"- 2026-11-06 lab: {HID} promoted: holdout pass, paper sleeve S-1" in outbox  # no numbers, no params
    assert any("H-2026-11-06-trend-again refused" in line and "already used its holdout run" in line for line in outbox)


HOLDOUT_ONLY = {  # lines that change the strategy only when it gets the secret months (2026)
    "the code crashes": 'print("SECRET", prices.tail(1).to_dict())\nif prices.index[-1].year >= 2026: raise ValueError(str(prices.tail(1)))',
    "its weights are invalid": "if prices.index[-1].year >= 2026: weights = weights * 2",
    "the strategy loses": "",
}


@pytest.mark.parametrize("case", HOLDOUT_ONLY)
def test_the_holdout_fails_closed_and_shows_only_pass_or_fail(tmp_path, monkeypatch, case):
    monkeypatch.setenv("LAB_SANDBOX", "local")
    root = make_root(tmp_path, holdout_drift=-0.8 if case == "the strategy loses" else None)
    submit(root, FIXED.replace("    return weights", "    " + HOLDOUT_ONLY[case].replace("\n", "\n    ") + "\n    return weights"))
    Lab(root, dt.date(2026, 11, 4)).run()
    decide(root, "decision: candidate\nreason: not met\n")
    lab = Lab(root, dt.date(2026, 11, 6))
    lab.run()
    assert statuses(lab) == {HID: "rejected"}
    assert lab.db.execute("select passed from holdout_runs").fetchall() == [(False,)]
    agent_sees = (root / "journal/outbox.md").read_text() + (root / "reports/families.md").read_text()
    assert f"{HID} rejected: step 6: holdout fail" in agent_sees
    assert "SECRET" not in agent_sees and "sharpe -" not in agent_sees


def test_a_crash_on_the_validation_data_is_refused_without_its_text(root):
    crash = 'print("SECRET", prices.tail(1).to_dict())\n    if prices.index[-1].year >= 2012: raise ValueError("SECRET")'
    submit(root, FIXED.replace("    return weights", "    " + crash + "\n    return weights"))
    Lab(root, dt.date(2026, 11, 4)).run()
    outbox = (root / "journal/outbox.md").read_text()
    assert f"{HID} refused (not a trial)" in outbox and "SECRET" not in outbox
    assert "SECRET" in (root / "registry/sandbox.log").read_text()  # for the user, on the host


def holdout_lab(root, code, *hids):
    """a lab with archived strategy files whose hashes step 4 saved."""
    lab = Lab(root, dt.date(2026, 11, 4))
    for hid in hids:
        (root / f"strategies/archive/{hid}.py").write_text(code)
        lab.db.execute("insert into code_hashes values (?, ?)", [hid, hashlib.sha256(code.encode()).hexdigest()])
    return lab


def test_the_holdout_uses_the_pick_made_before_it_its_drawdown_limit_and_the_tested_code(root):
    p = pd.read_csv(root / "data/all/prices.csv", index_col=0, parse_dates=True)
    inside = (p.index >= "2026-01-01") & (p.index < "2026-07-01")  # the holdout months
    drift = np.column_stack([np.where(inside, -0.4, 0.02), np.where(inside, 2.0, 0.0)]) / 252  # SPY wins before, GLD inside
    noise = np.random.default_rng(2).normal(0, 0.001, (len(p), 2)) * np.where(inside, 10, 1)[:, None]  # real swings inside
    p[["SPY", "GLD"]] = 100 * np.exp(np.cumsum(drift + noise, axis=0))
    p.to_csv(root / "data/all/prices.csv")
    code = "def signal(prices, hold='SPY'):\n    return (prices * 0).assign(**{hold: 1.0})\n"
    lab = holdout_lab(root, code, "H-a", "H-b", "H-c", "H-d")
    both, gld = {"grid": {"hold": ["SPY", "GLD"]}}, {"grid": {"hold": ["GLD"]}}
    assert not lab.holdout("H-a", "F-001", both, {"bench_maxdd": 1.0})  # SPY: picked before the holdout, it loses inside
    assert lab.holdout("H-b", "F-002", gld, {"bench_maxdd": 1.0})
    assert not lab.holdout("H-c", "F-003", gld, {"bench_maxdd": 1e-4})  # GLD gains, but falls more than the limit
    (root / "strategies/archive/H-d.py").write_text(code + "# changed after step 4\n")
    assert not lab.holdout("H-d", "F-004", gld, {"bench_maxdd": 1.0})


def test_a_refine_stays_in_its_parents_family_and_an_unlike_one_counts_in_n(root):
    submit(root)
    Lab(root, dt.date(2026, 11, 4)).run()
    gold = "def signal(prices):\n    return (prices * 0).assign(GLD=1.0)\n"  # trades nothing like the trend idea
    submit(root, gold, hid="H-2026-11-05-refine")
    (root / "strategies/inbox/H-2026-11-05-refine.yaml").write_text(yaml.safe_dump(CARD | {"id": "H-2026-11-05-refine", "parent": HID, "grid": {}}))
    submit(root, gold, hid="H-2026-11-05-orphan")
    (root / "strategies/inbox/H-2026-11-05-orphan.yaml").write_text(yaml.safe_dump(CARD | {"id": "H-2026-11-05-orphan", "parent": "H-nope", "grid": {}}))
    submit(root, hid="H-2026-11-05-close")  # the trend code again: a refine like its family
    (root / "strategies/inbox/H-2026-11-05-close.yaml").write_text(yaml.safe_dump(CARD | {"id": "H-2026-11-05-close", "parent": HID}))
    lab = Lab(root, dt.date(2026, 11, 5))
    lab.run()
    families = dict(lab.db.execute("select id, family from hypotheses").fetchall())
    assert families == {HID: "F-001", "H-2026-11-05-refine": "F-001", "H-2026-11-05-close": "F-001"}  # one holdout run for all
    assert lab.sharpe_var(3500)[1] == 2  # but the unlike refine counts as its own idea in the DSR's N
    assert "H-2026-11-05-orphan refused (not a trial): parent H-nope never reached step 4" in (root / "journal/outbox.md").read_text()


def test_a_server_error_never_costs_the_idea(root, monkeypatch):
    submit(root)
    monkeypatch.setenv("LAB_SANDBOX", "false")  # a sandbox command that fails, like Docker down
    alerts = Lab(root, dt.date(2026, 11, 4)).run()
    assert "server error" in alerts[0] and (root / f"strategies/inbox/{HID}.yaml").exists()  # the card waits
    monkeypatch.setenv("LAB_SANDBOX", "local")
    Lab(root, dt.date(2026, 11, 4)).run()
    decide(root, "decision: candidate\nreason: not met\n")
    monkeypatch.setenv("LAB_SANDBOX", "false")
    lab = Lab(root, dt.date(2026, 11, 6))
    assert "holdout waits" in lab.run()[0]
    assert statuses(lab) == {HID: "candidate"} and lab.db.execute("select count(*) from holdout_runs").fetchone() == (0,)


def test_the_scripts_never_follow_a_link_the_agent_planted(root):
    secret = root / "data/all/prices.csv"
    size = secret.stat().st_size
    (root / "strategies/inbox").mkdir(parents=True)
    (root / "strategies/inbox/H-2026-11-04-link.yaml").symlink_to(secret)  # to read host data through an error text
    submit(root)
    (root / "reports").mkdir()
    (root / f"reports/{HID}.md").symlink_to(secret)  # to overwrite host data with a report
    Lab(root, dt.date(2026, 11, 4)).run()
    outbox = (root / "journal/outbox.md").read_text()
    assert "H-2026-11-04-link refused (not a trial): H-2026-11-04-link.yaml must be a plain file, not a link" in outbox
    assert "SPY" not in outbox and secret.stat().st_size == size and not (root / f"reports/{HID}.md").is_symlink()


def test_a_second_truncation_failure_rejects_the_idea(root):
    status = []
    for _ in range(2):  # the agent "fixes" it without removing the lookahead
        submit(root, code=BUGGY)
        lab = Lab(root, dt.date(2026, 11, 4))
        lab.run()
        status += lab.db.execute("select status from hypotheses").fetchone()
        lab.db.close()
    assert status == ["fix", "rejected"]
    assert not (root / f"reports/{HID}.md").exists()  # never reached step 4: not a trial


def test_the_sandbox_catches_a_lookahead_hidden_by_a_module_cache(root, tmp_path):
    code = ("_seen = {}\n\ndef signal(prices):\n"
            "    if not _seen:  # the first call gets all the days: keep its answer\n"
            "        _seen[0] = (prices.shift(-1) > prices).astype(float) / 13\n"
            "    return _seen[0].reindex(prices.index)\n")
    prices = pd.read_csv(root / "data/all/prices.csv", index_col=0, parse_dates=True).loc[:"2011-12-31"]
    failure, _ = sandbox.run(code, prices, {}, train=prices)
    assert failure is not None


def test_a_card_that_is_not_valid_yaml_is_refused_and_the_lab_keeps_running(root):
    (root / "strategies/inbox").mkdir(parents=True)
    (root / "strategies/inbox/H-2026-11-04-bad.yaml").write_text("id: H-2026-11-04-bad\nrule: monthly: hold\n")
    submit(root)
    Lab(root, dt.date(2026, 11, 4)).run()
    assert (root / "strategies/refused/H-2026-11-04-bad.yaml").exists()
    assert (root / f"reports/{HID}.md").exists()  # the next card still ran


@pytest.mark.parametrize("met, members, text, recorded", [
    ("MET", 1, "decision: candidate\nreason: looks good\n", "rejected"),
    ("MET", 3, "decision: refine\nreason: hold SHY instead of cash\n", "rejected"),  # a full family can't refine
    ("NOT MET", 1, "decision: refine\nreason: try more\n", "candidate"),
    ("MET", 1, "decision: refine\nreason: hold SHY instead of cash\n", "refine"),
    ("MET", 1, "decision: refine\nreason: not met: sharpe 0.6\n", "rejected"),  # not valid YAML: the rule decides
])
def test_the_script_records_only_decisions_the_rules_allow(root, met, members, text, recorded):
    lab = Lab(root, dt.date(2026, 11, 4))
    for i in range(1, members):
        lab.db.execute("insert into hypotheses values (?, 'F-001', 'I-001', '{}', 'rejected', 0, '{}', null, now(), now())", [f"H-{i}"])
    lab.db.execute("insert into hypotheses values (?, 'F-001', 'I-001', '{}', 'tested', 0, ?, null, now(), null)",
                   [HID, json.dumps({"failure_if": met})])
    decide(root, text)
    lab.record_decisions()
    assert statuses(lab)[HID] == recorded


GOOD = {"failure_if": "NOT MET", "val_orders": 100, "val_sharpe": 0.9, "bench_sharpe": 0.5, "val_maxdd": 0.1, "bench_maxdd": 0.2,
        "stats": {"sr": 0.06, "skew": 0.0, "kurt": 3.0, "t": 3500}}


def candidate(lab, hid, family, report=GOOD):
    lab.db.execute("insert into hypotheses values (?, ?, 'I-001', '{}', 'candidate', 0, ?, null, now(), now())",
                   [hid, family, json.dumps(report)])


@pytest.mark.parametrize("change", [{"val_orders": 29}, {"stats": GOOD["stats"] | {"sr": 0.005}}, {"val_sharpe": 0.4}, {"val_maxdd": 0.31}])
def test_step_6_rejects_a_candidate_that_fails_any_promotion_check(root, change):
    lab = Lab(root, dt.date(2026, 11, 4))
    lab.holdout = lambda *args: pytest.fail("the holdout must not run")
    candidate(lab, "H-a", "F-001", GOOD | change)
    lab.promote()
    assert statuses(lab) == {"H-a": "rejected"}


def test_step_6_keeps_one_holdout_per_family_and_week_and_three_sleeves(root):
    lab = Lab(root, dt.date(2026, 11, 4))  # a Wednesday

    def holdout(hid, family, card, report):  # a passing holdout; the real one needs a strategy file
        lab.db.execute("insert into holdout_runs values (?, ?, ?, true, 1, 0.1)", [family, hid, lab.today])
        return True
    lab.holdout = holdout
    lab.db.execute("insert into sleeves values ('S-1', 'H-x', date '2026-10-01', null, null), "
                   "('S-2', 'H-y', date '2026-10-01', null, null)")
    candidate(lab, "H-a", "F-001")
    candidate(lab, "H-b", "F-002")
    lab.promote()
    assert statuses(lab) == {"H-a": "promoted", "H-b": "candidate"}  # one holdout a week: H-b waits

    lab.today = dt.date(2026, 11, 9)  # next Monday
    candidate(lab, "H-c", "F-001")
    lab.promote()
    assert statuses(lab) == {"H-a": "promoted", "H-b": "passed", "H-c": "rejected"}  # 3 sleeves run; F-001's holdout is spent


def test_dsr_counts_families_and_uses_the_v_rule(root):
    lab = Lab(root, dt.date(2026, 11, 4))
    t = 3500

    def tested(hid, family, sr):
        report = json.dumps({"stats": {"sr": sr, "skew": 0, "kurt": 3, "t": t}, "val_sharpe": 0, "bench_sharpe": 0, "val_maxdd": 0, "bench_maxdd": 0})
        lab.db.execute("insert into hypotheses values (?, ?, 'I-001', '{\"idea\": \"x\"}', 'rejected', 0, ?, null, now(), now())",
                       [hid, family, report])
    for hid, family, sr in [("H-1", "F-001", 0.01), ("H-2", "F-001", 0.02), ("H-3", "F-002", 0.1)]:
        tested(hid, family, sr)
    stats = {"sr": 0.03, "skew": 0, "kurt": 3, "t": t}
    assert lab.dsr(stats) == (pytest.approx(deflated_sharpe(stats, 2, 1 / t)), 2)  # N = families, not trials; V = 1/T below 5
    for i, sr in enumerate([0.0, 0.08, 0.16]):  # 5 families, widely spread: V = their variance
        tested(f"H-{i + 4}", f"F-00{i + 3}", sr)
    spread = np.var([0.02, 0.1, 0.0, 0.08, 0.16], ddof=1)
    assert lab.sharpe_var(t) == (pytest.approx(spread), 5)
    lab.write_families()  # the page shows the bar the DSR really uses, not the 1/T table
    assert f"Sharpe bar now ≈ {sharpe_needed(5, t, spread):.2f}" in (root / "reports/families.md").read_text()
    assert round(sharpe_needed(5, t, spread), 2) != round(sharpe_needed(5, t), 2)
    lab.db.execute("delete from hypotheses where id in ('H-3', 'H-5', 'H-6')")
    for hid, family, sr in [("H-3", "F-002", 0.012), ("H-5", "F-004", 0.011), ("H-6", "F-005", 0.013)]:
        tested(hid, family, sr)  # close together: V never goes below 1/T
    assert lab.sharpe_var(t) == (pytest.approx(1 / t), 5)


def test_holdout_runs_once_per_family_and_once_per_week(root):
    lab = Lab(root, dt.date(2026, 11, 4))  # a Wednesday
    lab.db.execute("insert into holdout_runs values ('F-001', 'H-x', date '2026-11-02', true, 1, 0.1)")
    assert lab.holdout_gate("F-001") == "spent"
    assert lab.holdout_gate("F-002") == "wait"
    lab.today = dt.date(2026, 11, 9)  # next Monday
    assert lab.holdout_gate("F-002") == "go"


def test_stop_rule_counts_rejections_until_a_promotion_or_the_users_resume(root):
    lab = Lab(root, dt.date(2026, 11, 4))
    for i, status in enumerate(["promoted", "rejected", "rejected", "refine", "rejected", "rejected", "rejected"]):
        lab.db.execute("insert into hypotheses values (?, null, null, null, ?, 0, null, null, now(), now() + to_seconds(?))",
                       [f"H-{i}", status, i])
    assert lab.rejections_in_a_row() == 5  # the refine neither counts nor resets
    submit(root)
    lab.run()
    assert "stop rule" in (root / "journal/outbox.md").read_text()
    lab.db.execute("insert into resumes values (now() + to_seconds(60))")  # the user answered
    assert lab.rejections_in_a_row() == 0


def test_the_users_saved_checks_survive_a_damaged_ideas_line(root):
    lab = Lab(root, dt.date(2026, 11, 4))
    assert lab.checks("I-001") == ["orders_per_year > 60"]
    (root / "ideas.md").write_text("I-001 | done F-001 candidate | seed | behavioral | Time-series trend | MOP 2012\n")
    assert lab.checks("I-001") == ["orders_per_year > 60"]
