# Lab glossary

Chiron's Monday lab items use these words from week 1, long before module 3 teaches them. Each word has one plain
sentence and one thing the user can check. Until the gate, every lab result is "untrusted until the gate".
The exact definitions are in `program.md` (sections 2–4); this page only translates them.

| Word | In plain words | What you can check |
|---|---|---|
| Hypothesis (card) | One trading idea, written down before any test: the rule, why it might work, and when it counts as failed | The card in `strategies/archive/`: the "fails if" lines exist before the result |
| `failure_if` | The test the idea must not fail, fixed before the backtest — for example "Sharpe not above the benchmark's" | The report shows each line with "→ yes" (this line failed) or "→ no", and one overall line: MET (the idea failed) or NOT MET |
| Family | Hypotheses that are really the same idea. The scripts group them by how alike their returns are, not by their names; a refine (a changed rule for the same idea) always joins its parent's family | `reports/families.md`: one line per family, "tries n/3" |
| Trial | A hypothesis that was really backtested on the hidden validation years. The scripts count every one | `trials_total` in each report |
| Truncation test | The scripts run the rule on data cut at random days. If the signals change, the rule looked into the future | A note in `journal/outbox.md`: "truncation test failed on …" (one fix allowed); a second failure is a rejection in `journal/lab.md` |
| Walk-forward | Every 6 months the scripts pick the best setting using only earlier data, then trade it for the next 6 months | "switches" and "last picks" in the report |
| Deflated Sharpe | How likely the result is more than luck, after counting how many ideas were tried. Each new family raises the bar, and so does a refine that trades unlike its family | The bar at the top of `reports/families.md`. The report's `dsr` counts the ideas on the report's day; promotion computes it again with the count on its own day, so it can fall below 0.80 later |
| Benchmark | ⅓ stocks, ⅓ bonds, ⅓ real assets, rebalanced every quarter — what you get without any cleverness | `bench_sharpe` in every report |
| Holdout | Several months of prices nobody sees, used once per family as a last pass/fail check | Only "pass" or "fail" ever appears; no numbers, by design |
| Sleeve | A strategy that passed and now trades in Chiron's paper portfolio with €5,000 of pretend money | `reports/paper.md` and the script message on Monday morning |
