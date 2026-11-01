# Research protocol (program.md)

You run the lab. The user wrote this protocol. You follow it; you don't change it.
If a rule looks wrong, say so in the journal. Don't break it.

Status: agreed 2026-10-31, updated after the harness was built. Numbers marked (default) are proposals, tuned on real data later.
Values in [BRACKETS] are filled after the model choice and the week-0 measurement.

## 1. Your job

You do:
- Write hypothesis cards and their `signal()` code (open sessions, strong model).
- Read the ≤ 20-line reports and decide reject / refine / candidate (close sessions, cheap model).
- Keep the lab journal.

Scripts do the rest: truncation test, novelty check, backtests, Deflated Sharpe, holdout,
paper portfolio, registry. They run outside your sandbox.

You never:
- Edit `harness/`, `scripts/`, `data/` or the registry. Scripts own the trial count.
- Look for validation or holdout data. You see only `data/train/`. Validation results reach you only as reports.
- Use web search in lab sessions.
- Put a ticker, a date or a hand-picked subset in a rule. Rules apply to the whole universe.
  Grouping by asset class from `universe.yaml` is allowed. A repeating calendar rule is allowed: the month of the year,
  the day of the month, the weekday. A specific date or year never is.
- Call a strategy "working". Before the module-3 gate, every result is "untrusted until the gate", with the reason.

Every new family raises your own bar: the Deflated Sharpe counts independent ideas — the families, and each refine that
trades unlike its family. The bar is at the top of `reports/families.md`.
Refines don't raise it, so they are capped. Submit only ideas you would bet on.

## 2. Words we count with

| Term | Meaning |
|---|---|
| Hypothesis | One card plus its signal file. ID: `H-YYYY-MM-DD-<slug>`. |
| Family | Hypotheses that are the same idea. Scripts assign it, not you: a card with `parent:` joins its parent's family; any other card joins a family whose first member's train returns correlate > 0.7 (default) with its own, else it starts a new one. |
| Refine | A new hypothesis in the same family whose `rule:` text changes. A grid-only change is not a refine: the grid already covers parameters. Max 3 hypotheses per family (default); a 4th is refused at step 3 and is not a trial. |
| Trial | A hypothesis that reached step 4 (it has validation returns). The registry counts trials; the Deflated Sharpe uses the number of independent ideas: the families, plus each refine that trades unlike its family. |
| Rejection | Final outcome "reject": step 3 failed twice, step 5 said reject, or step 6 failed. |
| Candidate | A hypothesis that step 5 marked "candidate". Step 6 decides promotion. |
| Sleeve | A promoted strategy in the agent's paper portfolio. |

"Attempt" in older notes means trial.

## 3. Data and money

- Universe: the 13 ETFs in `universe.yaml`. Equities SPY, IWM, EFA, EEM. Bonds SHY, IEF, TLT, TIP, LQD, HYG. Real assets IYR, GLD, DBC.
- Prices: daily adjusted close only.
- Periods:

  | Period | Dates | Who sees it |
  |---|---|---|
  | Train | 2007-04 → 2011-12 | you (`data/train/`) and scripts |
  | Validation | 2012-01 → [HOLDOUT_START] | scripts only |
  | Holdout | [HOLDOUT_START] → [WEEK_1_START] | one script, pass/fail only |
  | Forward | from [WEEK_1_START] | scripts (paper portfolio) |

  [HOLDOUT_START] = the latest training cutoff of the lab models. Validation start 2012-01 (default) gives ~14 years — a shorter validation can't pass the Deflated Sharpe even with a good idea.
- Benchmark: ⅓ equities, ⅓ bonds, ⅓ real assets, equal weight inside each class, quarterly rebalance.
- Capital: €5,000 simulated (fixed EUR/USD rate), for each sleeve and for the benchmark. Each test period (validation, holdout) starts with €5,000.
- Orders: a row with any number is an order: the engine moves each ETF to its weight (NaN in that row = 0).
  A row of only NaN means hold: no order, the positions drift. Send rows only on the days your rule trades.
- Fill: an order from the close of day t fills at the close of day t+1. The engine does this. Your `signal()` shifts nothing.
- Cost per order: €1.00 + [Y] bps spread (+ FX fee if any). On an order day, an ETF whose gap to its target is
  smaller than 1% of the portfolio value (default) is not traded; it drifts.
  At €5,000, one order is ≈ 0.26% of a full position. Strategies that trade often die here.
- Long only, no leverage: weights ≥ 0, row sum ≤ 1. The rest is cash at 0%.

## 4. The cycle

### Close session (cheap model) — runs first
For each report in `reports/` that has no `strategies/decisions/<id>.yaml` yet (`families.md` and `paper.md` aren't reports):
1. Read the report. You need nothing else.
2. Decide:
   - **reject** if the report says `failure_if: MET`.
   - **candidate** if it says `failure_if: NOT MET`.
   - **refine** only instead of reject, and only if the family has fewer than 3 hypotheses
     and you can name, in one line, a change to the `rule:` that the card's rationale predicts will fix the failure.
     When in doubt, reject.
3. Write `strategies/decisions/<id>.yaml` with `decision:` and `reason:` (one line). For a refine, the reason is the rule change.
4. Append the journal entry (section 7).
5. In `journal/ideas.md`, mark the idea's line `done <F-id> <decision>`. If the entry's `next:` is a new idea (not a refine), add it as a `journal` line.
6. Then read the `reports/outbox.md` lines since your last session. For each card the scripts refused or rejected at step 3,
   write a journal entry (`why:` the outbox reason) and update its `journal/ideas.md` line: a refused card you will fix keeps
   `testing <H-id>` (put the fixed pair into `strategies/inbox/`); a second truncation failure → `done - reject`;
   an idea you give up → `dropped <why>`.

### Open session (strong model)
1. Read the last 20 lines of `reports/outbox.md`, the last 5 entries of `journal/lab.md`, `reports/families.md`, `journal/ideas.md`, and the refine decisions not yet written as cards.
2. If the stop rule is active (section 8), stop here.
3. Write refine cards first. Then take the first `new` line in `journal/ideas.md` by source priority:
   user → journal → seed → agent. Skip `parked` lines. Mark the line `testing <H-id>`.
   Your own idea: add its line with the reason first (template 5.3), then you may test it.
   Each idea needs an economic reason: behavioral, risk or structural.
   Don't repeat a rejected family unless you change its `rule:`.
4. Write `strategies/inbox/<id>.yaml` (template 5.1) and `strategies/inbox/<id>.py` (template 5.2). Grid: at most 12 combinations (default).
5. Smoke-test on `data/train/`: the function runs, the shape matches, weights ≥ 0, row sum ≤ 1.
6. Open more hypotheses only while you have ideas you would bet on and turns left.

### Scripts between sessions
- Step 3: truncation test + novelty check. On a truncation failure, the next open session gets one fix: the files wait in
  `strategies/fix/`; put the fixed pair back into `strategies/inbox/` with the same id. A second failure is a rejection.
  A refused card (bad card, crashing code, full family, a family whose holdout run is used) moves to `strategies/refused/`;
  `reports/outbox.md` says why. It is not a trial.
  Your code runs in a separate strategy sandbox that gets only the prices it is called with: no files, no network.
  If it crashes there, the outbox says only that it crashed. Debug with your smoke test on `data/train/`.
  A hypothesis that lands in a family with 3 members already is refused; it is not a trial.
- Step 4: walk-forward on validation. Every 6 months (default), pick the grid point with the best net Sharpe on all earlier data and trade it for the next 6 months.
  The stitched out-of-sample pieces are the validation result. The script writes the registry and `reports/<id>.md` (section 6).

### Step 6 (scripts, outside your sandbox)
For each candidate, in queue order:
1. Promotion checks on validation, net of costs (defaults):
   - at least 30 orders;
   - Deflated Sharpe ≥ 0.80, with N = number of families (the bar is for a paper slot, not for real money);
   - Sharpe ≥ the benchmark's Sharpe;
   - max drawdown ≤ 1.5 × the benchmark's.
2. Holdout: if the family's holdout run is used, reject. If a holdout ran this week, the candidate waits.
   The result is pass or fail only; you never see its numbers.
   The grid point is the one picked on all data before the holdout.
   Fail if holdout Sharpe < 0 or drawdown > 1.5 × the benchmark's validation max drawdown.
3. Pass → a new sleeve, if fewer than 3 sleeves run (default); else it waits.
A family whose holdout run is used can't promote again: step 3 refuses its new cards (not a trial).

## 5. Templates

### 5.1 Card
```yaml
id: H-YYYY-MM-DD-slug
parent: null              # id of the hypothesis this refines, else null
source: I-001             # the ideas.md line this card tests
idea: >
  One or two sentences.
premium: behavioral       # behavioral | risk | structural
rationale: >
  Why the premium exists and who pays it. Name a book or paper if you know one.
rule: >
  The rule in words. Universe-wide: no tickers, no dates.
grid:                     # at most 12 combinations in total
  param_name: [value1, value2]
expected: >
  What result would support the idea.
failure_if:               # report fields only (section 6); the script evaluates it
  - val_sharpe <= bench_sharpe
libraries: []             # never pandas, numpy, scipy, statsmodels (both sandboxes have them); others only after the user approved them
```
`failure_if`: 1 to 6 lines (the user's checks included), each `field op field-or-number`, with op one of `< <= > >=`.
A library the user hasn't approved refuses the card: ask the user in the journal, with the reason.
Any line fails → `MET`. The script refuses a card with any other form.
If the source idea has `checks:` (5.3), copy each one into `failure_if` word for word. The script refuses a card that drops one.

### 5.2 Signal
```python
import pandas as pd

def signal(prices: pd.DataFrame, **params) -> pd.DataFrame:
    """prices: adjusted closes, index = trading days, columns = tickers.
    return: target weights, same index and columns.
    a row of only NaN = hold (no order). in other rows NaN = 0.
    row t may use rows <= t only. weights >= 0, row sum <= 1."""
```
A row on every day lets the engine trade every day; each order costs €1.
Lookahead traps the truncation test catches: `shift(-1)`, `center=True` windows, `bfill`,
"is this the last day of the month?" checks that look at the next row, full-sample mean or std.

### 5.3 Idea line (`journal/ideas.md`)
```
I-001 | new | user | behavioral | Hold bonds only when stocks fall | why it might work, or a book/paper
I-002 | new | user | risk | Hold the least jumpy half of the ETFs | why | checks: orders_per_year > 12; val_maxdd > 0.15
```
- checks (optional, last field): the user's own `failure_if` lines, separated by `;`. Never edit or remove them.
  They apply to every card written for the idea after they were added; they don't change past decisions.
- status: `new` · `testing <H-id>` · `done <F-id> <decision>` · `done - reject` (failed step 3 twice, no family) · `dropped <why>` · `parked` (ML ideas wait until the user opens them after the course)
- source: `user` · `journal` · `seed` · `agent`
- The user and you add lines. Never delete a line; change its status.
- Only price-based ideas fit the data (adjusted close only). Ideas that need other data (yields, dividends): status `parked`, reason "needs data".

## 6. Report (≤ 20 lines, written by scripts)

Fields you can use in `failure_if`: `val_sharpe`, `bench_sharpe`, `val_cagr`, `bench_cagr`,
`val_vol`, `val_maxdd`, `bench_maxdd` (drawdowns as positive fractions), `orders_per_year`,
`cost_per_year`, `train_sharpe`, `grid_sharpe_min`, `grid_sharpe_median`, `grid_sharpe_max`,
`dsr`, `trials_total`, `families_total` (the Deflated Sharpe's N: families plus independent refines).
The report also shows the family, the `failure_if` result line by line, the number of walk-forward switches and the last picks.

`reports/families.md` (scripts rewrite it after every run) is the lab's memory of old ideas. Read it before you write a card. One line per family:
```
F-id | status (open|rejected|promoted|retired|full) | tries n/3 | the idea in one line | best result | why it ended
```
Your own memory can be wrong; this file and the registry are the truth.

## 7. Journal entry (append to `journal/lab.md`)
```
## <id> — <reject|refine|candidate> — <date>
family: <F-id> (<new|existing>) · trials in registry: <n>
tested: <one line>
result: val Sharpe <x> vs bench <y>; max DD <a> vs <b>; <orders>/yr, cost <c>/yr
why: <the failure_if line that decided, or "not met">
learned: <about the idea, not the parameters>
next: <one line, or none>
concepts: <knowledge-map concepts this entry shows>
trust: untrusted until the gate — <reason>
```

## 8. Stop rule and budget

- After 5 rejections in a row (default), open no new hypotheses. Write in the journal:
  "Question for the user: idea pool empty, or protocol too strict?" Wait for the answer.
  A refine doesn't count and doesn't reset the count. Only a promotion or the user's reset resets it.
  The script counts: the count is at the top of `reports/families.md`, and while the rule is active the script refuses new cards.
- The script records only the decisions section 4 allows. Another decision is replaced by the rule's decision and noted in the outbox.
- If `journal/ideas.md` has no `new` line and you have no idea you would bet on, write "Question for the user: idea pool empty" in the journal and open nothing.
- Every session has a turn cap. If you hit it, write "stopped at cap" and what is unfinished. The next session continues.
- A session that doesn't start was skipped by the budget veto. That is normal.

## 9. The user and the lessons

- Monday report: at most 3 lab items, most important first:
  promotions or retirements → stop-rule notes → the most instructive rejection.
  Plain words. For each item, one thing the user can check.
- The `concepts:` line links the journal to the knowledge map. When a lesson covers a concept, the tutor uses a real lab entry:
  orders and costs (W9), truncation failures for lookahead (W10), train vs validation gaps for overfitting (W13),
  walk-forward (W15), premium families (W21–W25).
- Lesson data ends at [HOLDOUT_START].

## 10. Sleeves (the agent's paper portfolio)

- Each sleeve: €5,000 simulated, same fill and cost rules, compared weekly with the benchmark by a script.
- Parameters: the walk-forward from the sleeve's start: the grid point picked on all data before it, re-picked every 6 months (default).
- `reports/paper.md` (scripts rewrite it every weekday): each sleeve, the benchmark and a 60/40 line (context only) since their start.
- Retire a sleeve (defaults): forward drawdown > 1.5 × the benchmark's validation max drawdown,
  or after 52 forward weeks with net Sharpe below the benchmark's.
- Before the gate, scripts retire sleeves automatically. After the gate, the user reviews retirements
  and decides what, if anything, goes into their own IBKR paper account.
