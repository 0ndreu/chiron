"""the budget check: money builds up daily in the billing cycle; the lab gets this week's
share; the user's jobs also get the reserve and what earlier weeks left; fail closed for the lab; the 80% alert."""
import datetime as dt
import sqlite3

import pytest

from scripts.budget import alert, check, cycle, limits, report, veto

# November 2026 has 30 days: 22 x 0.90 / 30 = $0.66 a day, $4.62 a full week
TUESDAY = dt.datetime(2026, 11, 3, 10, 0)


@pytest.fixture
def cfg(tmp_path):
    db = sqlite3.connect(tmp_path / "state.db")
    db.execute("create table sessions (model text, actual_cost_usd real, estimated_cost_usd real, "
               "input_tokens int, output_tokens int, started_at real)")
    db.commit()
    return {"state_db": str(tmp_path / "state.db"), "month_usd": 22, "billing_day": 1, "reserve": 0.10, "margin": 0.20,
            "user_jobs": [[0, 0.2], [2, 0.2], [5, 2.0], [6, 0.2]], "prices": {}}


def session(cfg, when, cost=None, model="m", tokens=(1000, 100)):
    with sqlite3.connect(cfg["state_db"]) as db:
        db.execute("insert into sessions values (?, null, ?, ?, ?, ?)", [model, cost, *tokens, when.timestamp()])


def test_the_weekly_shares_add_up_to_the_month_in_a_five_monday_cycle(cfg):
    mondays = [dt.datetime(2026, 11, 1)] + [dt.datetime(2026, 11, d) for d in (2, 9, 16, 23, 30)]  # Nov 1 is a Sunday
    assert sum(limits(cfg, m)[3] for m in mondays) == pytest.approx(22 * 0.90)
    assert cycle({"billing_day": 31}, dt.date(2026, 11, 15)) == (dt.date(2026, 10, 31), dt.date(2026, 11, 30))
    assert cycle({"billing_day": 15}, dt.date(2027, 1, 3)) == (dt.date(2026, 12, 15), dt.date(2027, 1, 15))


def test_a_lab_job_runs_only_inside_this_weeks_share(cfg):
    session(cfg, dt.datetime(2026, 10, 30), cost=9.0)  # the last cycle: not this cycle's money
    session(cfg, TUESDAY - dt.timedelta(hours=20), cost=1.0)  # Monday: $1.20 with the margin
    assert veto(cfg, "lab", TUESDAY) is None  # 1.20 + 2.40 for the user's jobs ahead (Wed, Sat, Sun) < 4.62
    session(cfg, TUESDAY - dt.timedelta(hours=1), cost=1.0)
    assert "lab allowance used" in veto(cfg, "lab", TUESDAY)  # 2.40 + 2.40 >= 4.62
    assert veto(cfg, "user", TUESDAY) is None


def test_the_users_job_today_still_counts_as_ahead(cfg):
    wednesday = TUESDAY + dt.timedelta(days=1)
    session(cfg, wednesday - dt.timedelta(days=2), cost=1.9)  # x 1.2 = 2.28
    assert "lab allowance used" in veto(cfg, "lab", wednesday)  # 2.28 + 2.40 (today's quiz included) >= 4.62


def test_the_users_jobs_use_the_reserve_but_never_later_weeks(cfg):
    session(cfg, TUESDAY - dt.timedelta(hours=20), cost=6.5)  # x 1.2 = 7.80
    assert "limit for your jobs" in veto(cfg, "user", TUESDAY)  # 22 - 0.66 x 22 later days = 7.48
    assert veto(cfg, "user", dt.datetime(2026, 11, 30, 10)) is None  # the last week: no later shares to protect


@pytest.mark.parametrize("problem, reason", [("no cost, no price", "without a cost or a price"),
                                             ("job cost not measured", "isn't measured"), ("no state.db", "check failed")])
def test_the_lab_fails_closed_and_the_users_jobs_still_run(cfg, problem, reason):
    if problem == "no cost, no price":
        session(cfg, TUESDAY - dt.timedelta(hours=1), cost=None, model="new-model")
    elif problem == "job cost not measured":
        cfg["user_jobs"][1][1] = None
    else:
        cfg["state_db"] = "/nonexistent/dir/state.db"
    assert reason in veto(cfg, "lab", TUESDAY)
    assert veto(cfg, "user", TUESDAY) is None


def test_a_session_without_a_cost_is_priced_from_its_tokens(cfg):
    cfg["prices"] = {"m": [2.0, 10.0]}  # usd per million tokens
    session(cfg, TUESDAY - dt.timedelta(hours=1), cost=0.0, tokens=(1_000_000, 100_000))  # $2 + $1 = $3, x 1.2 = 3.60
    assert "lab allowance used" in veto(cfg, "lab", TUESDAY)  # 3.60 + 2.40 >= 4.62


def test_the_80_percent_alert_comes_once_a_week_and_unpriced_sessions_every_day(cfg, tmp_path):
    session(cfg, TUESDAY - dt.timedelta(hours=1), cost=3.2)  # x 1.2 = 3.84 = 83% of 4.62
    assert "83%" in alert(cfg, tmp_path, TUESDAY)
    assert alert(cfg, tmp_path, TUESDAY + dt.timedelta(days=1)) == ""
    next_tuesday = TUESDAY + dt.timedelta(days=7)
    session(cfg, next_tuesday - dt.timedelta(hours=1), cost=3.2)
    session(cfg, next_tuesday - dt.timedelta(hours=1), cost=None, model="new-model")
    text = alert(cfg, tmp_path, next_tuesday)
    assert "83%" in text and "without a cost or a price (new-model)" in text


def test_the_report_counts_only_this_weeks_skipped_lab_jobs(cfg, tmp_path):
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry/budget.log").write_text("2026-10-29 10:00 lab skipped: x\n2026-11-03 09:00 lab skipped: x\n"
                                                  "2026-11-03 09:30 user skipped: x\n")
    text = report(cfg, tmp_path, TUESDAY)
    assert "lab jobs skipped by the budget this week: 1" in text and "your jobs may still use $7.48" in text


def test_the_check_always_prints_a_gate_line_and_logs_each_skip(cfg, tmp_path):
    # Hermes skips the AI call when a pre-run script prints nothing, so "run" must be printed too
    assert check(cfg, tmp_path, "lab", TUESDAY) == '{"wakeAgent": true}'
    session(cfg, TUESDAY - dt.timedelta(hours=1), cost=4.0)
    assert check(cfg, tmp_path, "lab", TUESDAY) == '{"wakeAgent": false}'
    assert check(cfg, tmp_path, "user", TUESDAY) == '{"wakeAgent": true}'
    assert " lab skipped: lab allowance used" in (tmp_path / "registry/budget.log").read_text()


def test_the_report_shows_skipped_user_jobs_and_the_last_lab_reason(cfg, tmp_path):
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry/budget.log").write_text("2026-11-03 08:00 lab skipped: old\n2026-11-03 09:00 lab skipped: newest\n"
                                                  "2026-11-03 09:30 user skipped: x\n")
    text = report(cfg, tmp_path, TUESDAY)
    assert "lab jobs skipped by the budget this week: 2 (last: newest)" in text
    assert "your jobs skipped by the budget this week: 1 — a problem" in text
