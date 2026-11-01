"""the budget check before each Hermes job, the 80% alert and the weekly usage report. host only.

    python -m scripts.budget check lab|user     the pre-run --script of a Hermes cron job: prints
                                                {"wakeAgent": false} to skip the job, {"wakeAgent": true} to run it
                                                (Hermes skips the AI call on empty output too)
    python -m scripts.budget alert              daily script-only job: one line when the week passes 80%, once a week
    python -m scripts.budget report             Sunday script-only job: the usage report

the spend comes from Hermes's own ledger, ~/.hermes/state.db (one source, no second store). Hermes has no budget limit of its own;
/insights 7 and /topup in Telegram show the details and the real Nous balance.
"""
import calendar
import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
# the one place that knows the state.db schema. the column names are from the docs and our notes, not from a real
# install: confirm them on the first install (sqlite3 ~/.hermes/state.db .schema) and fix this line if needed.
SPEND = ("select model, coalesce(actual_cost_usd, estimated_cost_usd), coalesce(input_tokens, 0), coalesce(output_tokens, 0) "
         "from sessions where started_at >= ?")


def spend(cfg, since):
    """(usd with the margin, models that have tokens but no cost and no price). Hermes estimates are lower bounds."""
    usd, unpriced = 0.0, set()
    with sqlite3.connect(f"file:{Path(cfg['state_db']).expanduser()}?mode=ro", uri=True) as db:  # read only: Hermes owns it
        for model, cost, tokens_in, tokens_out in db.execute(SPEND, [since.timestamp()]):
            if cost:
                usd += cost
            elif tokens_in or tokens_out:  # no cost from Hermes: price the tokens, or fail closed
                if price := cfg["prices"].get(model):
                    usd += (tokens_in * price[0] + tokens_out * price[1]) / 1e6
                else:
                    unpriced.add(model)
    return usd * (1 + cfg["margin"]), unpriced


def cycle(cfg, today):
    """(first day, first day of the next) of the Nous billing cycle that holds `today`.
    billing_day null: the 1st, until the user sets the renewal day."""
    day = cfg.get("billing_day") or 1

    def on(year, month):  # the billing day in that month, or its last day
        year, month = year + (month - 1) // 12, (month - 1) % 12 + 1
        return dt.date(year, month, min(day, calendar.monthrange(year, month)[1]))
    first = on(today.year, today.month)
    if first > today:
        first = on(today.year, today.month - 1)
    return first, on(first.year, first.month + 1)


def limits(cfg, now):
    """money builds up day by day: month x (1 - reserve) / days in the cycle.
    returns (Monday, this week's first and end day inside the cycle, the lab's limit this week,
    the limit for the user's jobs this cycle, the cycle's first day). the lab may use only this week's share;
    the user's jobs may also use the reserve and what earlier weeks left, never the shares of later weeks."""
    first, nxt = cycle(cfg, now.date())
    per_day = cfg["month_usd"] * (1 - cfg["reserve"]) / (nxt - first).days
    monday = now.date() - dt.timedelta(days=now.weekday())
    lo, hi = max(monday, first), min(monday + dt.timedelta(days=7), nxt)
    return monday, lo, hi, per_day * (hi - lo).days, cfg["month_usd"] - per_day * (nxt - hi).days, first


def at(day):
    return dt.datetime.combine(day, dt.time())


def veto(cfg, track, now):
    """the reason to skip the job, or None. a lab job runs only inside the lab allowance: this week's share
    minus the spend so far and the user's jobs still ahead this week. the user's jobs run until their limit.
    an error skips a lab job (fail closed) and never blocks the user's jobs."""
    try:
        monday, lo, hi, week, user, first = limits(cfg, now)
        if track == "user":
            spent, _ = spend(cfg, at(first))
            return f"the limit for your jobs is used: ${spent:.2f} of ${user:.2f} this cycle" if spent >= user else None
        spent, unpriced = spend(cfg, at(lo))
        ahead = [usd for day, usd in cfg["user_jobs"] if now.date() <= monday + dt.timedelta(days=day) < hi]
        if unpriced:
            return f"sessions without a cost or a price: {sorted(unpriced)}"
        if None in ahead:
            return "the cost of the user's jobs isn't measured yet (week-0 measurement)"
        if spent + sum(ahead) >= week:
            return f"lab allowance used: ${spent:.2f} spent + ${sum(ahead):.2f} for the user's jobs ahead >= ${week:.2f}"
        return None
    except Exception as e:
        return None if track == "user" else f"the budget check failed: {e!r}"


def alert(cfg, root, now):
    """one line when this week's spend passes 80% of the week's share (once a week),
    and every day while sessions have no cost and no price."""
    _, lo, _, week, _, _ = limits(cfg, now)
    spent, unpriced = spend(cfg, at(lo))
    marker = root / "registry" / f"budget-alert-{lo}"
    lines = []
    if spent >= 0.8 * week and not marker.exists():
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        lines.append(f"Budget: {spent / week:.0%} of this week's ${week:.2f} is used (${spent:.2f}). The lab waits when its share is gone; your lessons don't.")
    if unpriced:
        lines.append(f"Budget: sessions without a cost or a price ({', '.join(sorted(unpriced))}): lab jobs wait until lab.yaml has their prices.")
    return "\n".join(lines)


def report(cfg, root, now):
    _, lo, hi, week, user, first = limits(cfg, now)
    nxt = cycle(cfg, now.date())[1]
    spent_week, _ = spend(cfg, at(lo))
    spent_cycle, _ = spend(cfg, at(first))
    projection = spent_cycle / ((now.date() - first).days + 1) * (nxt - first).days
    log = root / "registry" / "budget.log"
    week_lines = [x for x in log.read_text().splitlines() if x >= f"{lo:%Y-%m-%d}"] if log.exists() else []
    lab_skips = [x for x in week_lines if " lab skipped" in x]
    skipped, user_skipped = len(lab_skips), sum(" user skipped" in x for x in week_lines)
    why = f" (last: {lab_skips[-1].split('skipped: ', 1)[-1]})" if lab_skips else ""
    return "\n".join([
        f"Usage, week of {lo} (Hermes estimates + {cfg['margin']:.0%})" + ("" if cfg.get("billing_day") else " · billing day not set: cycles start on the 1st"),
        f"this week ${spent_week:.2f} of the lab's ${week:.2f} · cycle since {first}: ${spent_cycle:.2f} of ${cfg['month_usd']:.2f}, "
        f"projection to {nxt}: ${projection:.2f}",
        f"your jobs may still use ${max(user - spent_cycle, 0):.2f} this cycle · lab jobs skipped by the budget this week: {skipped}{why}",
        f"your jobs skipped by the budget this week: {user_skipped}" + (" — a problem: tell someone" if user_skipped else ""),
        "details: /insights 7 · real Nous balance: /topup (a big gap to the numbers above means the margin is wrong)",
    ])


def check(cfg, root, track, now):
    """the line a Hermes pre-run script prints: skip or run. a skip is logged with its reason."""
    if reason := veto(cfg, track, now):
        (root / "registry").mkdir(exist_ok=True)
        with open(root / "registry" / "budget.log", "a") as f:
            f.write(f"{now:%Y-%m-%d %H:%M} {track} skipped: {reason}\n")
        return json.dumps({"wakeAgent": False})
    return json.dumps({"wakeAgent": True})  # never empty: Hermes skips the AI call on empty output


if __name__ == "__main__":
    now, cmd = dt.datetime.now(), sys.argv[1:]
    try:
        cfg = yaml.safe_load((ROOT / "lab.yaml").read_text())["budget"]
    except Exception:
        cfg = None  # veto() then skips lab jobs and lets the user's jobs run
    if len(cmd) == 2 and cmd[0] == "check" and cmd[1] in ("lab", "user"):
        print(check(cfg, ROOT, cmd[1], now))
    elif cmd == ["alert"]:
        if text := alert(cfg, ROOT, now):
            print(text)
    elif cmd == ["report"]:
        print(report(cfg, ROOT, now))
    else:
        sys.exit("usage: python -m scripts.budget check lab|user | alert | report")
