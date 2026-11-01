# Course: systematic trading from scratch

Pace: 1–2 hours a week; the lesson is on Sunday at 11:00 (Europe/Madrid). Length: ~28 weeks.
Weekly format: theory ≤ 15 min → homework → quiz → "explain it in your own words".
[hands-on] = the user writes the code; Chiron only reviews.

Two tracks run in parallel. Chiron's lab runs from week 1 on a harness that was built in week 0 (it is
read-only to Chiron). Weeks 1–16 teach the user to audit that lab, not to build it. Every lab result is "untrusted until
the gate". The module-3 gate means the user can audit the lab; from then on the user decides what goes into their own IBKR paper
account. Chiron's lab searches from week 1; the user's own strategy work starts after the gate (ideas can go into
`journal/ideas.md` any time; the lab tests them first).

Data rules: `AGENTS.md`, "Data in lessons" (one copy; they bind Chiron's demos and the user's homework). In short:
Chiron's demos use train data (2007–2011); homework on the user's own computer uses data up to 2026-07-01; the
user's strategy backtests use train only, and later years go through the lab.

Core books (in `/research/books/`, if the user puts them there):

- Carver, "Systematic Trading" — risk, position sizing, combining rules
- Chan, "Quantitative Trading" — practical start
- Aronson, "Evidence-Based Technical Analysis" — data-mining bias
- Harris, "Trading and Exchanges" — how markets work
- López de Prado, "Advances in Financial Machine Learning" — only after week 28

## Week 0 — setup (one-off, not course time)

Built before any purchase: harness, data pipeline, universe, benchmark, budget scripts.
Then the server setup, on the VPS, before Portal Plus is bought. Portal weekend (timebox: one weekend):
Portal login, Telegram, the week-0 cost measurement, the IBKR paper account.
Week 1 starts on schedule even if small pieces are unfinished.
Done when: the server setup, the purchases and the Portal weekend pass their checks.

## Module 1. Market mechanics (weeks 1–3)

- W1. Stocks, bonds, ETFs; who is on the other side of a trade; exchange vs broker. US ETFs vs UCITS equivalents, and
  why an EU retail investor can't buy SPY (PRIIPs/KID). 5 minutes: what a risk premium is (why someone pays you for
  holding a risk) — every lab card names one.
  Homework:
  - Python check (20 min): write a function that turns a list of prices into returns. Chiron gives a "your language → pandas"
    cheat sheet in the lesson: the calls that `harness/engine.py` uses.
  - Critique the lab's 13-ETF universe (`universe.yaml`) with this checklist. Points 1–2 for all 13 ETFs; points 3–5 for
    5 ETFs, one or two per asset class (the other twins wait until W20, when the user picks what goes into their account):
    1. Does each ETF hold something different? Chiron prints a correlation table of daily returns (train data); flag
       pairs above 0.9.
    2. How long is each history? `scripts/data.py` printed the first dates.
    3. Is there a UCITS twin at Revolut, where real money goes? Search in the Revolut app; prefer EUR lines (no FX fee).
       Can it be ordered in the IBKR paper account, where practice happens? Check the order preview.
    4. What does it cost a year (TER)? justETF.
    5. Accumulating or distributing? justETF; note what it means for your taxes.
  Write the result as a table; Chiron reviews it.
- W2. Order types (market, limit, stop), spread, liquidity, commissions.
  Homework:
  - Place a market order and a limit order in the IBKR paper account.
  - Measure the Revolut spread in 3 short checks on different days: bid and ask for the 5 UCITS twins from W1. The
    engine charges Y once per order, so Y = what one order pays against the mid price = half the median
    (ask − bid) / mid, in bps (the full spread would be the conservative choice; say which one you use). The user writes
    Y into `lab.yaml` (`costs.spread_bps`); lab runs before that used Y = 0, so their costs are a little too low.
  - Compute the round-trip cost of a €385 order (one full position at €5,000): €1 per order + Y.
  - Pandas exercise 1 (~30 min): load `prices.csv`, daily returns with `pct_change` and with `shift`.
- W3. Data: OHLCV, adjusted prices, splits, dividends, how dirty free sources are.
  Homework:
  - [hands-on] Read the quality check in `scripts/data.py` (`problems()`, ~20 lines). Find and describe one real data
    problem: start with SHY's flat days in 2012, 2013 and 2021 — stale data or real prices?
  - Critique the lab's benchmark (⅓ equities, ⅓ bonds, ⅓ real assets, equal weight inside, quarterly rebalance) in
    3 answers: what question does it answer? Which of its ETFs are in it only because they survived (survivorship)?
    Where do USD research and EUR money differ?
  - Pandas exercise 2 (~30 min): boolean masks and `reindex` (which ETFs closed above their 200-day average?).
  Module quiz.

## Module 2. Return statistics (weeks 4–7)

- W4. Simple vs log returns, CAGR, why −50% needs +100% to recover.
  Homework [hands-on]: returns and CAGR for the universe. Pandas exercise 3 (~30 min): `to_numpy` and a loop over days
  that grows a portfolio value, the way `engine.py` does.
- W5. Volatility, drawdown, Sharpe; comparing assets with different risk.
  Homework: a metrics table for the universe + its interpretation in your own words.
- W6. Fat tails, crises, correlations that break in a crisis.
  Homework: a return histogram vs a normal distribution; correlations in calm vs crisis years. Chiron's demo: 2008
  (train). The user's own computer: 2020 and 2022 (stocks and bonds fell together).
- W7. Random walk and market efficiency.
  Homework [hands-on]: generate 20 random "price series" and find "patterns" in them.
  Module quiz.

## Module 3. Backtesting and its traps (weeks 8–16) — GATE

The audit of the lab's harness runs next to the lessons: the 284 lines that decide results line by line, the rest by
behaviour. Nine weeks, so each week stays within 1–2 hours: in an audit week the lesson is 30–45 minutes. If a week
still doesn't fit, Chiron splits it.

- W8. What a backtest is; vectorized vs event-driven; the fill rule (signal at the close of day t, fill at the close of
  day t+1).
  Audit `harness/engine.py`, part 1, line by line: the daily loop and the fill.
- W9. Costs, slippage, turnover.
  Audit `harness/engine.py`, part 2: the €1 + spread cost, the 1% no-trade rule, the metrics, the benchmark. Run
  `uv run pytest tests/test_engine.py` and say each test name as a rule. Short task: why 3 orders a week cost ≈ 3% a year
  at €5,000. Lab material: orders and costs in the reports.
- W10. Lookahead bias.
  Homework: Chiron hides 3 lookahead bugs in a small signal; the user finds them. Lab material: truncation failures in
  `reports/outbox.md` (second failures in `journal/lab.md`).
- W11. Audit `harness/checks.py`, part 1, line by line: the truncation test and the novelty check (families).
- W12. Audit `harness/checks.py`, part 2: the card checks and the `failure_if` parser.
- W13. Overfitting and multiple testing.
  Homework [hands-on]: sweep 500 parameter sets on random data and get a "great strategy". Lab material: train vs
  validation gaps.
- W14. Audit `harness/evaluate.py` line by line: walk-forward, Deflated Sharpe. Lab material: the bar at the top of
  `reports/families.md`.
- W15. Out-of-sample, walk-forward, holdout; parametric look-ahead (an LLM knows the years it was trained on).
  The real holdout example: why lesson data ends at 2026-07-01, and why the forward paper portfolio is the real
  judge.
  Audit by behaviour: `harness/lab.py`, `harness/sandbox.py`, `scripts/`. The test names are the rules; run the
  deliberate-break script (`uv run python -m tests.deliberate_break`, ~2 min) and see each break caught; read a line
  only where a test is unclear.
- W16. Gate: quiz ≥ 80% + explain three traps with your own examples + explain each rule of the result code (engine,
  checks, evaluate) + find the bug in the result code without saying where.

## Module 4. Risk, position sizing and the first strategy (weeks 17–20)

- W17. Why position size matters more than the signal; volatility targeting.
- W18. Drawdowns, Kelly and why not full Kelly; personal risk rules.
- W19. First strategy: trend following on the universe with volatility targeting.
  Homework [hands-on]: write the signal on train; run the truncation test on it. Compare it with the lab's family for
  the same idea in `reports/families.md`. If the lab hasn't tested the idea, add it to `journal/ideas.md` (source `user`).
- W20. Honest evaluation: costs, validation, the benchmark — from the lab's report, not a private backtest.
  Trading plan v1: instruments, risk, frequency, stop conditions. The user decides what, if anything, goes into their own
  IBKR paper account, and places those orders by hand.

## Module 5. Where risk premia come from (weeks 21–25)

- W21. Trend and momentum: time-series vs cross-sectional, and why they exist.
- W22. Short-horizon mean reversion.
- W23. Carry and value at the asset-class level (the lab parks these: they need data beyond prices).
- W24. Why premia decay; premium vs data mining (Aronson).
- W25. Module quiz; Chiron presents 2–3 lab families (promoted or the most instructive) and what they taught.

## Module 6. A portfolio of strategies (weeks 26–28)

- W26. Strategy correlations and diversification.
- W27. Combining signals (Carver).
- W28. Trading plan v2 + retro: what's clear, what isn't, what's next.

## Beyond (decided at the retro)

ML and meta-labeling (López de Prado; the lab's parked ML ideas open here); crypto on daily bars; taxes and
moving to real money with small capital at Revolut; or stopping.
