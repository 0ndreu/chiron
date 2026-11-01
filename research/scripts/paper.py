"""the agent's paper portfolio, forward from week 1 (program.md section 10). runs on the host.

    python -m scripts.paper            daily: update the sleeves, retire by the rules; prints only events
    python -m scripts.paper summary    the weekly summary for the user

both rewrite reports/paper.md for the agent. a Hermes script-only cron job sends what this prints to Telegram.
every run recomputes from the sleeve's start, so a missed day is filled on the next run.
"""
import json
import sys
from pathlib import Path

import pandas as pd

from harness import sandbox
from harness.checks import Refused
from harness.engine import benchmark, metrics, quarterly
from harness.evaluate import run_from, walk_forward
from harness.lab import MAX_DD, Lab, write_file

ROOT = Path(__file__).resolve().parents[1]


def retire_reason(sleeve, bench, bench_val_maxdd):
    """program.md 10: forward drawdown over 1.5 x the benchmark's validation max drawdown,
    or 52 forward weeks with a net Sharpe below the benchmark's over the same days."""
    m = metrics(sleeve)
    if m["maxdd"] > MAX_DD * bench_val_maxdd:
        return f"drawdown {m['maxdd']:.1%} is over the limit {MAX_DD * bench_val_maxdd:.1%}"
    if (sleeve.index[-1] - sleeve.index[0]).days >= 364 and m["sharpe"] < metrics(bench)["sharpe"]:
        return f"52 weeks with sharpe {m['sharpe']:.2f} below the benchmark's {metrics(bench)['sharpe']:.2f}"
    return None


def line(name, result, capital):
    week = result["value"].iloc[-1] / result["value"].iloc[-6] - 1 if len(result) > 5 else float("nan")
    m = metrics(result) if len(result) > 1 else {"maxdd": 0.0}
    return (f"{name}: {result['value'].iloc[-1] / capital - 1:+.1%} since {result.index[0].date()}, this week {week:+.1%}, "
            f"drawdown {m['maxdd']:.1%}, {int(result['orders'].sum())} orders")


def run(root, summary=False, today=None):
    """returns the text to print: events (daily) or the summary (weekly)."""
    lab = Lab(root, today)
    if not lab.periods["week_1"]:
        return ""
    prices, start = lab.prices("2100-01-01"), pd.Timestamp(lab.periods["week_1"])
    if len(prices.loc[start:]) < 2:
        return ""
    bench_weights = benchmark(prices, lab.classes)
    capital = lab.costs["capital"]
    lines = [line("benchmark", run_from(prices, bench_weights, start, **lab.costs), capital),
             line("60/40 SPY/IEF (context only)", run_from(prices, quarterly(prices, {"SPY": 0.6, "IEF": 0.4}), start, **lab.costs), capital)]
    events = []
    for sid, hid, started in lab.db.execute("select id, hypothesis, started from sleeves where retired is null order by id").fetchall():
        begin = max(pd.Timestamp(started), start)
        if len(prices.loc[begin:]) < 2:
            continue  # starts with the next price days
        card, report = (json.loads(v) for v in lab.db.execute("select card, report from hypotheses where id = ?", [hid]).fetchone())
        try:
            _, weights = sandbox.run(lab.archived_code(hid), prices, card["grid"], log=lab.log, name=f"{sid} {hid}")
            result, _, _ = walk_forward(weights, prices, card["grid"], begin, **lab.costs)  # re-picked every 6 months
        except Refused as e:  # the strategy failed (a crash, changed code): it can't trade, so it retires
            reason = f"its code failed ({e})"
        except Exception:  # the server, not the strategy: try again on the next run
            events.append(f"{sid} ({hid}): paper update waits, server error; see registry/sandbox.log")
            continue
        else:
            bench = run_from(prices, bench_weights, begin, **lab.costs)
            lines.append(line(f"{sid} {hid}", result, capital) + f" · benchmark since then {bench['value'].iloc[-1] / capital - 1:+.1%}")
            reason = retire_reason(result, bench, report["bench_maxdd"])  # no params shown: picked with holdout data
        if reason:
            lab.db.execute("update sleeves set retired = ?, reason = ? where id = ?", [lab.today, reason, sid])
            lab.note(f"{sid} ({hid}) retired: {reason}")
            events.append(f"paper sleeve {sid} ({hid}) retired: {reason}")
    head = f"Paper portfolio to {prices.index[-1].date()} (€5,000 each, after costs)"
    write_file(lab.root / "reports" / "paper.md", "\n".join([f"# {head}", *[f"- {x}" for x in lines]]) + "\n")
    return "\n".join([head, *lines, *events]) if summary else "\n".join(events)


if __name__ == "__main__":
    if text := run(ROOT, summary=sys.argv[1:] == ["summary"]):
        print(text)
