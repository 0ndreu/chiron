# chiron

An AI research partner and tutor for systematic trading, built on
[Hermes Agent](https://github.com/NousResearch/hermes-agent). The agent is called Chiron. It runs on a small VPS and
has two jobs:

1. **The lab.** Chiron writes trading hypotheses (a card plus a `signal()` function). Scripts test them on daily
   prices of 13 ETFs with fixed rules: a truncation test for lookahead, walk-forward parameter picks, a Deflated Sharpe
   bar that rises as more ideas are tried, a holdout used once per family, and a paper portfolio. Chiron judges the
   reports; it can't change the scripts or the rules.
2. **The course.** About 28 weeks of systematic trading for someone new to trading: a Sunday lesson, homework, a
   midweek quiz and nudges over Telegram. The first 16 weeks teach the user to audit the lab and end in a gate.

## Layout

| Path | What |
|---|---|
| `hermes/SOUL.md` | Chiron's identity, loaded in every session |
| `hermes/cron-jobs.md` | every scheduled job: when, which model, which budget check |
| `research/program.md` | the lab protocol the agent follows |
| `research/AGENTS.md` | the rules for sessions with the user |
| `research/curriculum/` | the course, the progress file, the glossary |
| `research/harness/` | the backtest engine, the checks, the lab runner, the strategy sandbox |
| `research/scripts/` | the data download, the paper portfolio, the budget check |
| `research/lab.yaml`, `research/universe.yaml` | dates, costs and the LLM budget; the 13 ETFs |
| `research/ideas.md` | the idea backlog |
| `docs/program-walkthrough.md` | one idea's path through the lab, step by step |
| `docs/seed-research.md` | the sources behind the seed ideas |

## Rules the design depends on

- The agent's strategy code never runs on the host: it runs in a throwaway container with no network and no data
  files, and the prices go in on stdin.
- The agent sees only training data (2007-04 → 2011-12). Validation, holdout and forward prices stay with the scripts.
- The holdout answers only pass or fail, once per family.
- A script checks the LLM budget before every job, outside the model. The lab waits when its weekly share is spent;
  the user's jobs keep running.
- The lab's state (data, registry, strategies, reports, journal) lives on the server, never in git.

## Run the tests

```bash
cd research
uv sync
uv run pytest
```

Python 3.12, managed with [uv](https://docs.astral.sh/uv/). The data download needs a Tiingo key:
`TIINGO_API_KEY=... uv run python -m scripts.data`.

## Status

The lab code and its tests are done. Next: the server setup, then picking the models and a week-0 cost measurement,
then week 1 of the course.
