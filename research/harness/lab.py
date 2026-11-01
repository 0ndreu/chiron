"""the lab's scripts between sessions (program.md section 4). runs on the host, never in the agent's sandbox.

    python -m harness.lab run      decisions -> step 6 for candidates -> steps 3-4 for new cards -> families.md
    python -m harness.lab resume   the user resets the stop rule
`run` prints alerts for the user (server errors, missing settings); a Hermes script-only cron job sends them to Telegram.
"""
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import yaml

from harness import sandbox
from harness.checks import NOVELTY, Refused, center, check_card, failure_met, grid_points, idea_checks, novelty, parse_line
from harness.engine import backtest, benchmark, metrics
from harness.evaluate import deflated_sharpe, pick, return_stats, run_from, sharpe_needed, walk_forward

CAP, MAX_SLEEVES, STOP_AFTER, MIN_ORDERS, MIN_DSR, MAX_DD = 3, 3, 5, 30, 0.80, 1.5  # program.md defaults

SCHEMA = """
create table if not exists hypotheses (id text primary key, family text, source text, card text, status text,
    truncation_failures int, report text, reason text, created timestamp, ended timestamp);
create table if not exists train_returns (hypothesis text, day date, ret double);
create table if not exists code_hashes (hypothesis text primary key, sha text);
create table if not exists idea_checks (idea text primary key, checks text);
create table if not exists holdout_runs (family text primary key, hypothesis text, day date, passed bool, sharpe double, maxdd double);
create table if not exists sleeves (id text primary key, hypothesis text, started date, retired date, reason text);
create table if not exists resumes (day timestamp);
"""
# hypotheses.status: fix -> tested -> rejected | refine | candidate -> passed -> promoted


def read_agent_file(path):
    """the text of a file the agent wrote. refuses a link or anything but one plain file:
    a link could make the scripts read a host-only file and show it to the agent."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise Refused(f"{path.name} is missing") from None
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise Refused(f"{path.name} must be a plain file, not a link")
    return path.read_text()


def write_file(path, text):
    """replace a file through a new temp file: a link someone put in its place is replaced, not followed."""
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def append_file(path, text):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o644), "a") as f:
        f.write(text)


class Lab:
    def __init__(self, root, today=None):
        self.root, self.today = Path(root), today or dt.date.today()
        cfg = yaml.safe_load((self.root / "lab.yaml").read_text())
        self.periods, self.costs, self.approved = cfg["periods"], cfg["costs"], cfg.get("approved_libraries") or []
        self.classes = yaml.safe_load((self.root / "universe.yaml").read_text())
        for d in ("strategies/inbox", "strategies/decisions", "strategies/fix", "strategies/refused",
                  "strategies/archive", "reports", "journal", "registry"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        self.db = duckdb.connect(str(self.root / "registry" / "lab.duckdb"))
        self.log = self.root / "registry" / "sandbox.log"  # crash texts: host only, never shown to the agent
        self.alerts = []  # for the user, printed by `run`
        self.db.execute(SCHEMA)

    def run(self):
        self.save_checks()
        self.record_decisions()
        self.promote()
        for path in sorted((self.root / "strategies" / "inbox").glob("*.yaml")):
            self.test(path)
        self.write_families()
        return self.alerts

    def resume(self):
        self.db.execute("insert into resumes values (?)", [dt.datetime.now()])
        self.note("the user reset the stop rule")
        self.write_families()

    # --- steps 3 and 4 ---

    def test(self, path):
        hid = path.stem
        row = self.db.execute("select status, truncation_failures from hypotheses where id = ?", [hid]).fetchone()
        try:
            if row and row[0] != "fix":
                raise Refused(f"the id {hid} is already used")
            if self.rejections_in_a_row() >= STOP_AFTER:
                raise Refused("stop rule: open nothing until the user answers")
            card = yaml.safe_load(read_agent_file(path))
            if not isinstance(card, dict) or card.get("id") != hid:
                raise Refused("the file name must be the card id")
            check_card(card, self.checks(card.get("source")), self.approved)
            code = read_agent_file(path.with_suffix(".py"))
            prices = self.prices(self.periods["holdout"])
            train = prices[prices.index < pd.Timestamp(self.periods["validation"])]
            failure, weights = sandbox.run(code, prices, card["grid"], train=train, log=self.log, name=hid)
            if failure:
                return self.truncation_failed(path, card, failure, (row[1] if row else 0) + 1)
            mid = grid_points(card["grid"]).index(center(card["grid"]))
            train_ret = backtest(train, weights[mid], **self.costs)["value"].pct_change().dropna()
            families = self.families()
            family = self.parent_family(card, families)
            # a refine unlike its family keeps the family's one holdout run, but counts as its own idea in N
            independent = bool(family) and not train_ret.corr(families[family][0]) > NOVELTY
            family = family or novelty(train_ret, families) or f"F-{len(families) + 1:03d}"
            if self.holdout_gate(family) == "spent":
                raise Refused(f"family {family} already used its holdout run; it can't be promoted again")
            report = self.evaluate(card, weights, prices, family, hid if independent else family)
            report["independent"] = independent
        except (Refused, ValueError, yaml.YAMLError) as e:  # ValueError: the engine refused the weights
            self.note(f"{hid} refused (not a trial): {e}")
            return self.move(path, "refused")
        except RuntimeError as e:  # the server, not the card: the card stays in the inbox for the next run
            return self.alerts.append(f"lab: {hid} waits, server error: {e}")
        new = family not in families
        self.db.execute("insert or replace into hypotheses values (?, ?, ?, ?, 'tested', ?, ?, null, ?, null)",
                        [hid, family, card["source"], json.dumps(card), row[1] if row else 0, json.dumps(report), dt.datetime.now()])
        self.db.execute("insert or replace into code_hashes values (?, ?)", [hid, hashlib.sha256(code.encode()).hexdigest()])
        returns = pd.DataFrame({"day": train_ret.index.date, "ret": train_ret.to_numpy()})
        self.db.execute("insert into train_returns select ?, day, ret from returns", [hid])
        self.write_report(hid, card, family, new, report)
        self.move(path, "archive")

    def parent_family(self, card, families):
        """a refine stays in its parent's family, whatever the novelty check says."""
        if not card.get("parent"):
            return None
        row = self.db.execute("select family from hypotheses where id = ?", [card["parent"]]).fetchone()
        if not row or not row[0]:
            raise Refused(f"parent {card['parent']} never reached step 4")
        if families[row[0]][1] >= CAP:
            raise Refused(f"family {row[0]} is full ({CAP} hypotheses)")
        return row[0]

    def truncation_failed(self, path, card, failure, fails):
        params, day = failure
        status = "rejected" if fails >= 2 else "fix"
        reason = f"truncation test failed on {day.date()} with {params}"
        now = dt.datetime.now()
        self.db.execute("insert or replace into hypotheses values (?, null, ?, ?, ?, ?, null, ?, ?, ?)",
                        [path.stem, card["source"], json.dumps(card), status, fails, reason, now, now if status == "rejected" else None])
        self.note(f"{path.stem}: {reason}; " + ("second failure: rejected" if status == "rejected" else "one fix allowed, the code is in strategies/fix/"))
        self.move(path, "archive" if status == "rejected" else "fix")

    def evaluate(self, card, weights, prices, family, idea):
        """step 4: walk-forward on validation and the report fields (program.md 6). idea: its key in the DSR's N."""
        result, picks, runs = walk_forward(weights, prices, card["grid"], pd.Timestamp(self.periods["validation"]), **self.costs)
        start = result.index[0]
        val = metrics(result)
        bench = metrics(run_from(prices, benchmark(prices, self.classes), start, **self.costs))
        first = runs[grid_points(card["grid"]).index(picks[0][1])]
        grid_sharpes = [metrics(run_from(prices, w, start, **self.costs))["sharpe"] for w in weights]
        stats = return_stats(result["value"].pct_change().dropna())
        dsr, n = self.dsr(stats, (idea, stats["sr"]))
        report = {
            "val_sharpe": val["sharpe"], "bench_sharpe": bench["sharpe"], "val_cagr": val["cagr"], "bench_cagr": bench["cagr"],
            "val_vol": val["vol"], "val_maxdd": val["maxdd"], "bench_maxdd": bench["maxdd"],
            "orders_per_year": val["orders_per_year"], "cost_per_year": val["cost_per_year"],
            "train_sharpe": metrics(first[first.index < start])["sharpe"],
            "grid_sharpe_min": min(grid_sharpes), "grid_sharpe_median": float(np.median(grid_sharpes)), "grid_sharpe_max": max(grid_sharpes),
            "dsr": dsr, "trials_total": self.db.execute("select count(*) from hypotheses where report is not null").fetchone()[0] + 1,
            "families_total": n, "val_orders": int(result["orders"].sum()), "stats": stats,
            "picks": [[str(day.date()), params] for day, params in picks],
        }
        report["failure_if"] = "MET" if failure_met(card["failure_if"], report) else "NOT MET"
        return report

    def write_report(self, hid, card, family, new, r):
        """the <= 20-line report the close session reads."""
        def fields(*keys):
            return " · ".join(f"{k} {r[k]:.3f}" for k in keys)
        lines = [f"# {hid} · validation report",
                 f"family: {family} ({'new' if new else 'existing'}) · trials_total {r['trials_total']} · families_total {r['families_total']}",
                 f"failure_if: {r['failure_if']}"]
        for line in card["failure_if"]:
            field, op, right = parse_line(line)
            value = r[right] if isinstance(right, str) else right
            lines.append(f"- {line}: {r[field]:.3f} {op} {value:.3f} → {'yes' if failure_met([line], r) else 'no'}")
        lines += [fields("val_sharpe", "bench_sharpe", "train_sharpe"), fields("grid_sharpe_min", "grid_sharpe_median", "grid_sharpe_max"),
                  fields("val_cagr", "bench_cagr", "val_vol"), fields("val_maxdd", "bench_maxdd"), fields("orders_per_year", "cost_per_year"),
                  f"dsr {r['dsr']:.3f} (step 6 needs {MIN_DSR}) · validation days {r['stats']['t']}"]
        segments = [p for i, p in enumerate(r["picks"]) if i == 0 or p[1] != r["picks"][i - 1][1]]
        lines.append(f"walk-forward picks ({len(segments) - 1} switches), last ones:")
        lines += [f"- from {day}: {params}" for day, params in segments[-4:]]
        write_file(self.root / "reports" / f"{hid}.md", "\n".join(lines) + "\n")

    # --- step 5 decisions, step 6 promotion ---

    def record_decisions(self):
        """the close session's decisions (program.md 4). the script keeps them inside the rules."""
        for path in sorted((self.root / "strategies" / "decisions").glob("*.yaml")):
            row = self.db.execute("select family, report from hypotheses where id = ? and status = 'tested'", [path.stem]).fetchone()
            if not row:
                continue
            try:
                d = yaml.safe_load(read_agent_file(path))
            except (Refused, ValueError, yaml.YAMLError):
                d = None
            d = d if isinstance(d, dict) else {}
            met = json.loads(row[1])["failure_if"] == "MET"
            members = self.db.execute("select count(*) from hypotheses where family = ?", [row[0]]).fetchone()[0]
            allowed = ({"reject", "refine"} if members < CAP else {"reject"}) if met else {"candidate"}
            decision = d.get("decision")
            if decision not in allowed:
                fixed = "reject" if met else "candidate"
                self.note(f"{path.stem}: decision {decision!r} isn't allowed here; recorded {fixed}")
                decision = fixed
            status = {"reject": "rejected", "refine": "refine", "candidate": "candidate"}[decision]
            self.end(path.stem, status, str(d.get("reason", "")), quiet=True)

    def promote(self):
        """step 6 for each candidate, in queue order (program.md 4)."""
        rows = self.db.execute("select id, family, card, report, status from hypotheses "
                               "where status in ('candidate', 'passed') order by ended").fetchall()
        if rows and not (self.periods["holdout"] and self.periods["week_1"]):
            return self.alerts.append("lab: step 6 waits until lab.yaml has the holdout and week_1 dates")
        for hid, family, card, report, status in rows:
            if status == "candidate":
                gate = self.holdout_gate(family)
                fails = ["the family's holdout run is already used"] if gate == "spent" else self.promotion_fails(json.loads(report))
                if fails:
                    self.end(hid, "rejected", "step 6: " + "; ".join(fails))
                    continue
                if gate == "wait":
                    continue
                try:
                    passed = self.holdout(hid, family, json.loads(card), json.loads(report))
                except Exception as e:  # the server, not the strategy: the candidate waits, the family keeps its run
                    self.alerts.append(f"lab: {hid} holdout waits, server error: {e}")
                    continue
                if not passed:
                    self.end(hid, "rejected", "step 6: holdout fail")
                    continue
                self.db.execute("update hypotheses set status = 'passed' where id = ?", [hid])
            if self.db.execute("select count(*) from sleeves where retired is null").fetchone()[0] >= MAX_SLEEVES:
                continue  # passed, waits for a free slot
            sid = f"S-{self.db.execute('select count(*) from sleeves').fetchone()[0] + 1}"
            self.db.execute("insert into sleeves values (?, ?, ?, null, null)", [sid, hid, self.today])
            self.end(hid, "promoted", f"holdout pass, paper sleeve {sid}")

    def promotion_fails(self, r):
        dsr, n = self.dsr(r["stats"])
        checks = [(r["val_orders"] >= MIN_ORDERS, f"{r['val_orders']} orders < {MIN_ORDERS}"),
                  (dsr >= MIN_DSR, f"dsr {dsr:.2f} < {MIN_DSR} with {n} families"),
                  (r["val_sharpe"] >= r["bench_sharpe"], "sharpe below the benchmark's"),
                  (r["val_maxdd"] <= MAX_DD * r["bench_maxdd"], f"drawdown over {MAX_DD} x the benchmark's")]
        return [msg for ok, msg in checks if not ok]  # NaN fails every check

    def holdout_gate(self, family):
        """'spent': the family used its one holdout run; 'wait': a holdout ran this week; else 'go'."""
        if self.db.execute("select 1 from holdout_runs where family = ?", [family]).fetchone():
            return "spent"
        monday = self.today - dt.timedelta(days=self.today.weekday())
        return "wait" if self.db.execute("select 1 from holdout_runs where day >= ?", [monday]).fetchone() else "go"

    def holdout(self, hid, family, card, report):
        """the one holdout run of a family, with the grid point picked before the holdout.
        returns pass/fail only: the numbers stay in holdout_runs on the host.
        the strategy's own failure (a crash, bad weights, changed code) is a fail; a server error raises and changes nothing."""
        start, grid = pd.Timestamp(self.periods["holdout"]), card["grid"]
        prices = self.prices(self.periods["week_1"])
        sharpe = maxdd = np.nan
        try:
            _, weights = sandbox.run(self.archived_code(hid), prices, grid, log=self.log, name=f"{hid} holdout")
            runs = [backtest(prices, w, **self.costs) for w in weights]
            part = metrics(run_from(prices, weights[pick(runs, grid, start)], start, **self.costs))
            sharpe, maxdd = part["sharpe"], part["maxdd"]
        except (Refused, ValueError) as e:
            append_file(self.log, f"--- {hid} holdout: {e!r}\n")
        passed = bool(sharpe >= 0 and maxdd <= MAX_DD * report["bench_maxdd"])
        self.db.execute("insert into holdout_runs values (?, ?, ?, ?, ?, ?)", [family, hid, self.today, passed, sharpe, maxdd])
        return passed

    # --- registry helpers ---

    def archived_code(self, hid):
        """the strategy code step 4 tested. a link or a changed file is the strategy's failure."""
        text = read_agent_file(self.root / "strategies" / "archive" / f"{hid}.py")
        sha = self.db.execute("select sha from code_hashes where hypothesis = ?", [hid]).fetchone()
        if not sha or hashlib.sha256(text.encode()).hexdigest() != sha[0]:
            raise Refused("the code changed after step 4")
        return text

    def prices(self, until):
        """adjusted closes from the train start up to (not incl.) `until`. the agent never sees this store."""
        if until is None:
            raise RuntimeError("period dates are not set in lab.yaml (set them when the models are picked)")
        p = pd.read_csv(self.root / "data" / "all" / "prices.csv", index_col=0, parse_dates=True)
        return p[(p.index >= pd.Timestamp(self.periods["train"])) & (p.index < pd.Timestamp(until))]

    def save_checks(self):
        """save the user's checks every run, so the agent can't remove one before its first card."""
        try:
            text = read_agent_file(self.root / "journal" / "ideas.md")
        except Refused as e:
            return self.alerts.append(f"lab: ideas.md: {e}")
        for idea in {m[1] for m in re.finditer(r"^\s*(I-\d+)\s*\|", text, re.M)}:
            try:
                self.checks(idea)
            except Refused:
                pass  # a bad check is reported when a card uses the idea

    def checks(self, idea):
        """the user's checks: the ideas.md line plus every copy saved before."""
        current = idea_checks(read_agent_file(self.root / "journal" / "ideas.md"), str(idea))
        row = self.db.execute("select checks from idea_checks where idea = ?", [idea]).fetchone()
        saved = json.loads(row[0]) if row else []
        merged = saved + [c for c in current if parse_line(c) not in {parse_line(s) for s in saved}]
        self.db.execute("insert or replace into idea_checks values (?, ?)", [idea, json.dumps(merged)])
        return merged

    def families(self):
        """{family: (its first member's train returns, members)} for the novelty check."""
        out = {}
        for family, first, n in self.db.execute("select family, arg_min(id, created), count(*) from hypotheses "
                                                "where family is not null group by family").fetchall():
            r = self.db.execute("select day, ret from train_returns where hypothesis = ? order by day", [first]).df()
            out[family] = (pd.Series(r["ret"].to_numpy(), index=pd.to_datetime(r["day"])), n)
        return out

    def dsr(self, stats, extra=None):
        """Deflated Sharpe with N = independent ideas. extra: (idea key, daily sharpe) of a result not saved yet."""
        var, n = self.sharpe_var(stats["t"], extra)
        return deflated_sharpe(stats, n, var), n

    def sharpe_var(self, t, extra=None):
        """(V, N). N = independent ideas: the families, plus each refine the correlation check would call new.
        V = max(1/T, the variance of the ideas' best daily Sharpes) from 5 ideas on, else 1/T
        (the bar never gets easier than the 1/T table)."""
        rows = [(hid if r.get("independent") else f, r["stats"]["sr"]) for hid, f, r in
                ((hid, f, json.loads(r)) for hid, f, r in
                 self.db.execute("select id, family, report from hypotheses where report is not null").fetchall())]
        best = {}
        for family, sr in rows + ([extra] if extra else []):
            best[family] = max(best.get(family, -np.inf), sr)
        return (max(1 / t, np.var(list(best.values()), ddof=1)) if len(best) >= 5 else 1 / t), len(best)

    def rejections_in_a_row(self):
        """rejections since the last promotion or the user's resume; refines don't count (program.md 8)."""
        rows = self.db.execute("select status from hypotheses where status in ('rejected', 'promoted') and ended > "
                               "coalesce((select max(day) from resumes), timestamp '1970-01-01') order by ended desc").fetchall()
        n = 0
        for (status,) in rows:
            if status == "promoted":
                break
            n += 1
        return n

    def end(self, hid, status, reason, quiet=False):
        self.db.execute("update hypotheses set status = ?, reason = ?, ended = ? where id = ?", [status, reason, dt.datetime.now(), hid])
        if not quiet:
            self.note(f"{hid} {status}: {reason}")

    def note(self, text):
        append_file(self.root / "reports" / "outbox.md", f"- {self.today} lab: {text}\n")

    def move(self, card, to):
        for f in (card, card.with_suffix(".py")):
            if f.exists() or f.is_symlink():
                shutil.move(f, self.root / "strategies" / to / f.name)

    def write_families(self):
        """reports/families.md: the lab's memory of old ideas (program.md 6)."""
        rows = self.db.execute("select id, family, card, status, report, reason from hypotheses "
                               "where family is not null order by created").fetchall()
        sleeves = dict(self.db.execute("select hypothesis, retired from sleeves").fetchall())
        families = {}
        for row in rows:
            families.setdefault(row[1], []).append(row)
        k = self.rejections_in_a_row()
        lines = ["# Idea families", "Scripts rewrite this file after every run. Don't edit it.",
                 f"Rejections in a row: {k} of {STOP_AFTER}" + (" · STOP RULE ACTIVE: open nothing, the user decides" if k >= STOP_AFTER else "")]
        if rows:
            t = json.loads(rows[-1][4])["stats"]["t"]
            var, n = self.sharpe_var(t)
            lines.append(f"Sharpe bar now ≈ {sharpe_needed(n, t, var):.2f}; with one more family ≈ {sharpe_needed(n + 1, t, var):.2f} (yearly, net)")
        lines.append("")
        for family, members in families.items():
            in_sleeve = [sleeves[m[0]] for m in members if m[0] in sleeves]
            status = ("promoted" if any(r is None for r in in_sleeve) else "retired" if in_sleeve else "full" if len(members) >= CAP
                      else "rejected" if all(m[3] == "rejected" for m in members) else "open")
            best = max((json.loads(m[4]) for m in members), key=lambda r: r["val_sharpe"])
            idea = " ".join(json.loads(members[0][2])["idea"].split())
            lines.append(f"{family} | {status} | tries {len(members)}/{CAP} | {idea} | val_sharpe {best['val_sharpe']:.2f} vs "
                         f"{best['bench_sharpe']:.2f}, maxdd {best['val_maxdd']:.2f} vs {best['bench_maxdd']:.2f} | {members[-1][5] or '-'}")
        write_file(self.root / "reports" / "families.md", "\n".join(lines) + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("run", "resume"):
        sys.exit("usage: python -m harness.lab run | resume")
    if alerts := getattr(Lab(Path(__file__).resolve().parents[1]), sys.argv[1])():
        print("\n".join(alerts))
