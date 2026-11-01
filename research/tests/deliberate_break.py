"""deliberate breaks: each one puts one known bug into a temporary copy of the code, then runs the tests.
a break that no test catches is a rule the tests don't protect. run it from research/:

    uv run python -m tests.deliberate_break          every break
    uv run python -m tests.deliberate_break E1 L3    only these

first the unbroken copy must pass, then every break must fail at least one test; else the exit code is 1.
not a test file (no test_ prefix): pytest doesn't collect it.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RESEARCH = Path(__file__).resolve().parents[1]
REPO = RESEARCH.parent
E, C, W = "research/harness/engine.py", "research/harness/checks.py", "research/harness/evaluate.py"
L, S = "research/harness/lab.py", "research/harness/sandbox.py"
D, B, P = "research/scripts/data.py", "research/scripts/budget.py", "research/scripts/paper.py"

# (id, the rule the tests must protect, file, the exact text, the broken text)
BREAKS = [
    # the engine
    ("E1", "an order fills at the next day's close, not at the close it was computed on", E,
     "        if t > 0 and order[t - 1]:\n            value = cash + pos.sum()\n            trade = w[t - 1] * value - pos",
     "        if order[t]:\n            value = cash + pos.sum()\n            trade = w[t] * value - pos"),
    ("E2", "every order pays the fee", E,
     "cost = orders * fee + np.abs(trade).sum()", "cost = np.abs(trade).sum()"),
    ("E3", "a gap under 1% of the portfolio isn't traded", E,
     "            trade[np.abs(trade) < min_trade * value] = 0.0\n", ""),
    ("E4", "no leverage: weights sum to at most 1", E,
     "if (w < 0).any() or (w.sum(axis=1) > 1 + 1e-9).any():", "if (w < 0).any():"),
    # step 3: the checks
    ("C1", "a NaN in a failure_if line counts as MET (fail closed)", C,
     "if np.isnan(a) or np.isnan(b) or OPS[op](a, b):", "if OPS[op](a, b):"),
    ("C2", "the truncation test checks the order days, where a lookahead hides", C,
     "        days = set(rng.choice(order_days, min(k, len(order_days)), replace=False))\n", "        days = set()\n"),
    ("C3", "a card that correlates > 0.7 with a family joins it, so small changes can't dodge the family rules", C,
     "if c > threshold}", "if c > 1}"),
    ("C4", "a family takes at most 3 hypotheses", C,
     "    if families[fid][1] >= cap:", "    if False:"),
    ("C5", "a card keeps every check the user wrote", C,
     "    if dropped := [c for c in checks if parse_line(c) not in rules]:", "    if dropped := []:"),
    ("C6", "a library needs the user's approval first", C,
     '    if unapproved := set(card.get("libraries") or []) - set(approved):', "    if unapproved := set():"),
    # step 4: walk-forward and the Deflated Sharpe
    ("W1", "a walk-forward pick sees only the days before it", W,
     'sharpe = [daily_sharpe(r["value"].pct_change()[r.index < before].dropna()) for r in runs]',
     'sharpe = [daily_sharpe(r["value"].pct_change().dropna()) for r in runs]'),
    ("W2", "the Deflated Sharpe bar rises with every family", W,
     "    if n <= 1:\n        return 0.0", "    if True:\n        return 0.0"),
    # the lab: decisions, promotion, the holdout, the registry
    ("L1", "a family gets one holdout run", L,
     '        if self.db.execute("select 1 from holdout_runs where family = ?", [family]).fetchone():', "        if False:"),
    ("L2", "at most one holdout run per week", L,
     '        return "wait" if self.db.execute("select 1 from holdout_runs where day >= ?", [monday]).fetchone() else "go"',
     '        return "go"'),
    ("L3", "the holdout fails on a drawdown over 1.5 x the benchmark's", L,
     'passed = bool(sharpe >= 0 and maxdd <= MAX_DD * report["bench_maxdd"])', "passed = bool(sharpe >= 0)"),
    ("L4", "promotion needs a Deflated Sharpe of at least 0.80", L,
     '(dsr >= MIN_DSR, f"dsr', '(True, f"dsr'),
    ("L5", "the script keeps the agent's decision inside the rules", L,
     "            if decision not in allowed:", "            if False:"),
    ("L6", "the stop rule: after 5 rejections in a row, no new cards until the user answers", L,
     "            if self.rejections_in_a_row() >= STOP_AFTER:", "            if False:"),
    ("L7", "the holdout and the paper run refuse code that changed after step 4", L,
     "        if not sha or hashlib.sha256(text.encode()).hexdigest() != sha[0]:", "        if not sha:"),
    ("L8", "the user's checks are saved, so the agent can't delete one before its first card", L,
     "        return merged", "        return current"),
    ("L9", "a refine that trades unlike its family counts as its own idea in the Deflated Sharpe", L,
     'rows = [(hid if r.get("independent") else f, r["stats"]["sr"])', 'rows = [(f, r["stats"]["sr"])'),
    ("L10", "the scripts read only plain files the agent wrote, never links", L,
     "    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:", "    if False:"),
    ("L11", "a server error never costs an idea: the card waits in the inbox", L,
     '            return self.alerts.append(f"lab: {hid} waits, server error: {e}")', '            return self.move(path, "refused")'),
    # the strategy sandbox
    ("S1", "the agent's code never runs on the host", S,
     "        raise RuntimeError(\"LAB_SANDBOX is not set: never run the agent's code on the host\")", '        template = "local"'),
    # the data
    ("D1", "a spike that reverses the next day is bad data", D,
     "SPIKE, BACK, FROZEN = 0.15, 0.05, 5", "SPIKE, BACK, FROZEN = 9.0, 0.05, 5"),
    ("D2", "the agent's copy ends before the validation period", D,
     '("train", prices[prices.index < pd.Timestamp(periods["validation"])])', '("train", prices)'),
    ("D3", "bad data writes nothing: the last good stores stay", D,
     "    if found := problems(prices, volume):\n        return found\n", "    found = problems(prices, volume)\n"),
    # the budget
    ("B1", "a broken budget check skips the lab (fail closed)", B,
     'return None if track == "user" else f"the budget check failed: {e!r}"', "return None"),
    ("B2", "the spend gets the safety margin: Hermes estimates are lower bounds", B,
     'return usd * (1 + cfg["margin"]), unpriced', "return usd, unpriced"),
    ("B3", "sessions with no cost and no price stop the lab", B,
     "        if unpriced:\n            return f\"sessions", "        if False:\n            return f\"sessions"),
    ("B4", "the lab leaves the money for the user's jobs still ahead this week", B,
     "if spent + sum(ahead) >= week:", "if spent >= week:"),
    ("B5", "the lab's budget gate fails closed when the check command breaks", "deploy/scripts/budget-lab.sh",
     "echo '{\"wakeAgent\": false}'", "echo '{\"wakeAgent\": true}'"),
    # the paper portfolio
    ("P1", "a sleeve retires on a drawdown over 1.5 x the benchmark's", P,
     '    if m["maxdd"] > MAX_DD * bench_val_maxdd:', "    if False:"),
]


def copy_code(root):
    """the code and the tests, without the virtual env, the data and the lab state."""
    skip = shutil.ignore_patterns(".venv", "data", "registry", "journal", "reports", "books", "strategies",
                                  ".pytest_cache", "__pycache__")
    shutil.copytree(RESEARCH, root / "research", ignore=skip)
    shutil.copytree(REPO / "deploy" / "scripts", root / "deploy" / "scripts")


def run_tests(root):
    """(passed, the first failed test). -x stops at the first failure; each copy has its own temp folder."""
    out = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", f"--basetemp={root / 'tmp'}"],
                         cwd=root / "research", capture_output=True, text=True)
    failed = next((line.split()[1] for line in out.stdout.splitlines() if line.startswith(("FAILED", "ERROR"))), "")
    return out.returncode == 0, failed


def try_break(work, brk):
    """the result line of one break, and whether a test caught it."""
    bid, rule, file, old, new = brk
    root = work / bid
    copy_code(root)
    path = root / file
    text = path.read_text()
    if text.count(old) != 1:  # the code changed: the break must change with it
        return f"{bid:4} STALE   {rule}: the text to break isn't in {file} exactly once", False
    path.write_text(text.replace(old, new))
    passed, failed = run_tests(root)
    return (f"{bid:4} MISSED  {rule}", False) if passed else (f"{bid:4} caught  {rule}\n          by {failed}", True)


def main(only):
    breaks = [b for b in BREAKS if not only or b[0] in only]
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        copy_code(work / "unbroken")
        passed, failed = run_tests(work / "unbroken")
        print("the unbroken code passes" if passed else f"the unbroken code fails ({failed}): fix that first")
        if not passed:
            return 1
        with ThreadPoolExecutor(max(1, (os.cpu_count() or 2) // 2)) as pool:
            results = list(pool.map(lambda b: try_break(work, b), breaks))
    for line, _ in results:
        print(line)
    missed = sum(not caught for _, caught in results)
    print(f"\n{len(results) - missed} of {len(results)} breaks caught")
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
