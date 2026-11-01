# Hermes jobs

Not deployed as a file: the server setup turns each row into a job. Chiron has no `cronjob` tool, so only this list
creates jobs. Server timezone: Europe/Madrid. The US market closes at 22:00 Madrid time (21:00 in the few weeks a year
when US and EU daylight saving don't match).

## Hermes facts this list depends on (source checked 2026-10-31, hermes-agent main c419cf7c)

- `--script` is a **file** inside `~/.hermes/scripts/`, never a command line. A `.sh` file runs under bash. The script's
  environment is cleaned: no API keys are passed in.
- A pre-run script that prints **nothing** skips the AI call. Only a last line `{"wakeAgent": false}` means "skip" on
  purpose; our budget check prints `{"wakeAgent": true}` to run (`scripts/budget.py`, `check()`).
- `hermes cron create` has `--workdir`, `--model`, `--script`, `--skill`, `--interpreter`, `--deliver`. It has no flag
  for `enabled_toolsets` or `attach_to_session`: set those in the jobs file (the server setup finds the exact way).
- Turn and wall-clock caps exist only globally (`agent.max_turns`, `agent.run_budget_seconds`), not per job: one
  cap each, from the hungriest job in the week-0 measurement × 1.5. They also limit each message of the Sunday chat.

## Settings for every job

- **Wrappers.** Every script is a `.sh` wrapper in `~/.hermes/scripts/` that does `cd /research`, exports `LAB_SANDBOX`
  and runs the command with the project's virtual env (`.venv/bin/python -m …`; not `uv run`, which can fail on a sync,
  and never a bare `python`). The data wrapper reads the Tiingo key from a host-only file. The setup creates
  `registry/` (gitignored; the data log and the budget log need it).
- **LLM jobs:** `--script budget-<track>.sh` (runs `python -m scripts.budget check <track>`), `--model`,
  `enabled_toolsets` (jobs file). The main model in `config.yaml` is the strong one: the Sunday lesson is a chat, not a
  job, and uses it.
- **The budget wrappers never exit non-zero.** Hermes applies the gate only when the script exits 0; on a crash it runs
  the agent anyway (`cron/scheduler.py`). So if the check command fails, `budget-lab.sh` prints `{"wakeAgent": false}`
  (fail closed: an unknown spend never lets the lab run) and `budget-user.sh` prints `{"wakeAgent": true}` (the user's
  jobs never wait on a broken check); both log the error to `registry/budget.log` and exit 0. The server setup tests
  both with a broken command.
- **The user's jobs** (kickoff, quiz, reminder, check): `--deliver telegram`. `--workdir /research`, so `AGENTS.md` loads. Continuable
  (`attach_to_session: true` in the jobs file, or `cron.mirror_delivery: true`), so a reply in Telegram has the message
  in context; by default a cron message is not in the chat history. In Telegram topic mode each delivery opens its own
  thread: answer inside it. The quiz also writes its questions into `progress.md`, so grading works either way.
- **Lab jobs:** `--deliver local --failure-deliver telegram`: their final answer goes to `~/.hermes/cron/output/`, not to
  the user (by default Hermes sends a job's final answer unless it contains `[SILENT]`); the user hears about the lab in
  the Monday kickoff (≤ 3 items), and a failed run still alerts. No workdir (only SOUL.md, memory and `program.md`
  load: the lab never sees the tutor's rules), not continuable (`attach_to_session: false` if `cron.mirror_delivery` is
  on). No web (the holdout prices must stay unseen), no cronjob tool.
- **Skills:** every LLM job has the `skills` toolset (`skill_manage` lives there), and `skills.write_approval: true`
  in `config.yaml`, so every skill write from any job or chat is staged in `~/.hermes/pending/skills/` and does nothing
  until reviewed. The skills tools add tokens to every request; the week-0 measurement counts them.
- **Script-only jobs:** `--no-agent --script <wrapper>.sh --deliver telegram`. What the script prints goes to
  Telegram; empty output sends nothing. A non-zero exit sends Hermes's error alert with the script's stderr.
- **One registry writer at a time** (DuckDB): `scripts.paper` (S1, S2) and `harness.lab` (S3, S4, and the user's manual
  `resume`) never overlap.

## LLM jobs

| # | Job | When | Model | Budget wrapper | Toolsets | Prompt |
|---|---|---|---|---|---|---|
| 1 | Kickoff | Mon 09:00 | cheap | `budget-user.sh` | file, skills | `Monday kickoff. Follow AGENTS.md, "The week", Mon.` |
| 2 | Quiz | Wed 20:00 | cheap | `budget-user.sh` | file, skills | `Wednesday quiz. Follow AGENTS.md, "The week", Wed.` |
| 3 | Reminder | Sun 10:30 | cheap | `budget-user.sh` | file, skills | `Sunday reminder. Follow AGENTS.md, "The week", Sun 10:30.` |
| 4 | Weekly check | Sun 19:00 | cheap | `budget-user.sh` | file, skills | `Weekly check. Follow AGENTS.md, "The week", Sun 19:00.` |
| 5 | Lab close | Tue, Thu, after S1 | cheap | `budget-lab.sh` | file, skills | `Lab session: close. Follow /research/program.md, section 4, "Close session". Nothing else.` |
| 6 | Lab open | Tue, Thu, after S3 | strong | `budget-lab.sh` | file, terminal, skills | `Lab session: open. Follow /research/program.md, section 4, "Open session". Nothing else.` |

"Cheap" and "strong" are the models picked before the Portal weekend, pinned to exact versions (an alias could move
the training cutoff, and the holdout starts at it). The close session needs no
terminal: it only reads reports and writes files. The open session runs its smoke test.

## Script-only jobs (no LLM)

| # | Job | When | Command | Prints |
|---|---|---|---|---|
| S1 | Data, then paper | Mon–Fri, [DATA_TIME] | `python -m scripts.data > registry/data.log && python -m scripts.paper` | paper events (a sleeve retired, a server error); bad data → exit 1 → Hermes's error alert with the problem list |
| S2 | Paper summary | Mon 08:45 | `python -m scripts.paper summary` | the weekly numbers, then any events, before the kickoff |
| S3 | Lab run after close | Tue, Thu, after job 5 | `python -m harness.lab run` | alerts only (records decisions, step 6) |
| S4 | Lab run after open | Tue, Thu, after job 6 | `python -m harness.lab run` | alerts only (tests the new cards) |
| S5 | Budget alert | daily 21:00 | `python -m scripts.budget alert` | one line at 80% of the week's share |
| S6 | Usage report | Sun 18:45 | `python -m scripts.budget report` | the weekly usage report, with skipped jobs and the last lab skip reason, before the check |
| S7 | Skill proposals | Sun 18:50 | count the files in `~/.hermes/pending/skills/` | "N skill proposals wait for review (/skills pending)"; nothing if N = 0 |

[DATA_TIME]: after Tiingo publishes the day's prices; check when that happens on the Portal weekend. If it is after midnight, the
weekday labels of S1 and the Tue/Thu chain move one day later. S1 must end before S2 on Monday morning.
The Tue/Thu chain: S1 → 5 → S3 → 6 → S4, each step after the previous one has ended.

Until week 0 fills `budget.user_jobs` in `lab.yaml`, the budget check skips every lab job ("the cost of the user's jobs
isn't measured yet"; S6 shows the reason). So the week-0 measurement measures the user's jobs first, then the lab jobs.

## Outside Hermes

- System cron, every 15 minutes: a watchdog that checks the Hermes gateway (the scheduler runs inside it).
- The stop-rule reset is the user's: `python -m harness.lab resume` over SSH (a one-line wrapper in the user's home
  directory), never while S1–S4 run.
