"""step 3 checks (program.md section 4): card intake, truncation test, novelty check, failure_if."""
import itertools
import operator
import re

import numpy as np

FIELDS = {
    "val_sharpe", "bench_sharpe", "val_cagr", "bench_cagr", "val_vol", "val_maxdd", "bench_maxdd",
    "orders_per_year", "cost_per_year", "train_sharpe", "grid_sharpe_min", "grid_sharpe_median",
    "grid_sharpe_max", "dsr", "trials_total", "families_total",
}
OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}
LINE = re.compile(r"\s*([a-z_]+)\s*(<=|>=|<|>)\s*([a-z_]+|-?\d+(?:\.\d+)?)\s*")
CARD_KEYS = {"id", "parent", "source", "idea", "premium", "rationale", "rule", "grid", "expected", "failure_if", "libraries"}
MAX_GRID, MAX_FAILURE_IF, NOVELTY = 12, 6, 0.7  # 6 keeps the report at <= 20 lines; 0.7: the family correlation


class Refused(Exception):
    """step 3 refuses the card. a refused card is not a trial."""


def parse_line(line):
    """one failure_if line -> (field, op, field or number)."""
    m = LINE.fullmatch(line)
    if not m or m[1] not in FIELDS or (m[3][0].isalpha() and m[3] not in FIELDS):
        raise Refused(f"bad failure_if line: {line!r}")
    return m[1], m[2], m[3] if m[3][0].isalpha() else float(m[3])


def failure_met(lines, report):
    """MET (True) if any line holds. a NaN counts as MET: fail closed."""
    for field, op, right in map(parse_line, lines):
        a, b = report[field], report[right] if isinstance(right, str) else right
        if np.isnan(a) or np.isnan(b) or OPS[op](a, b):
            return True
    return False


def idea_checks(ideas_md, idea_id):
    """the user's `checks:` from one ideas.md line (program.md 5.3)."""
    for line in ideas_md.splitlines():
        cells = [c.strip() for c in line.split("|")]
        if cells[0] != idea_id:
            continue
        if not cells[-1].startswith("checks:"):
            return []
        checks = [c.strip() for c in cells[-1].removeprefix("checks:").split(";") if c.strip()]
        for check in checks:
            try:
                parse_line(check)
            except Refused as e:  # the agent may not edit the check, so only the user can fix it
                raise Refused(f"{idea_id} checks: {e}; the user must fix it") from None
        return checks
    raise Refused(f"source {idea_id} is not in ideas.md")


def check_card(card, checks=(), approved=()):
    """refuse a card with missing keys, a bad id, a bad grid, bad failure_if lines, a dropped check
    or a library the user hasn't approved."""
    errors = []
    if missing := CARD_KEYS - card.keys():
        errors.append(f"missing keys: {sorted(missing)}")
    if not re.fullmatch(r"H-\d{4}-\d{2}-\d{2}-[a-z0-9-]+", str(card.get("id"))):  # the id becomes a file name
        errors.append("id must look like H-YYYY-MM-DD-slug")
    if card.get("premium") not in {"behavioral", "risk", "structural"}:
        errors.append("premium must be behavioral, risk or structural")
    grid = card.get("grid") or {}
    if not isinstance(grid, dict) or not all(isinstance(v, list) and v for v in grid.values()) \
            or np.prod([len(v) for v in grid.values()]) > MAX_GRID:
        errors.append(f"grid must map names to lists, at most {MAX_GRID} combinations")
    lines = card.get("failure_if") or []
    if not isinstance(lines, list) or not 0 < len(lines) <= MAX_FAILURE_IF:
        errors.append(f"failure_if must be a non-empty list of at most {MAX_FAILURE_IF} lines, the user's checks included")
        lines = []
    if unapproved := set(card.get("libraries") or []) - set(approved):
        errors.append(f"libraries need the user's approval first: {sorted(unapproved)}")
    rules = set()
    for line in lines:
        try:
            rules.add(parse_line(line))
        except Refused as e:
            errors.append(str(e))
    if dropped := [c for c in checks if parse_line(c) not in rules]:
        errors.append(f"dropped the user's checks: {dropped}")
    if errors:
        raise Refused("; ".join(errors))


def grid_points(grid):
    """every combination of the grid, as keyword dicts."""
    return [dict(zip(grid, values)) for values in itertools.product(*grid.values())]


def center(grid):
    """the middle value of each grid list (the lower one of two)."""
    return {k: v[(len(v) - 1) // 2] for k, v in grid.items()}


def truncation_failure(signal, prices, grid, k=20, seed=0):
    """lookahead test for every grid point: the row for day t must not change when the days after t are removed.
    checks k order days (a lookahead can hide there) and k random days.
    returns (params, day) of the first failure, else None."""
    rng = np.random.default_rng(seed)
    for params in grid_points(grid):
        full = signal(prices.copy(), **params)
        order_days = full.index[full.notna().any(axis=1)]
        days = set(rng.choice(order_days, min(k, len(order_days)), replace=False))
        days |= set(rng.choice(prices.index, k, replace=False))
        for t in sorted(days):
            row = signal(prices.loc[:t].copy(), **params).iloc[-1]
            if not np.allclose(row.to_numpy(float), full.loc[t].to_numpy(float), atol=1e-9, equal_nan=True):
                return params, t
    return None


def novelty(returns, families, threshold=NOVELTY, cap=3):
    """novelty check. returns: daily net train returns at the grid center.
    families: {family id: (its first member's returns, number of members)}.
    returns the most correlated family above threshold, or None for a new family. refuses a full family."""
    close = {fid: returns.corr(first) for fid, (first, _) in families.items()}
    close = {fid: c for fid, c in close.items() if c > threshold}  # NaN drops out
    if not close:
        return None
    fid = max(close, key=close.get)
    if families[fid][1] >= cap:
        raise Refused(f"family {fid} is full ({cap} hypotheses)")
    return fid
