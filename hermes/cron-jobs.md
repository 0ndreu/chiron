# Hermes jobs

Not deployed as a file: `deploy/jobs.sh` turns each row into a job, one line per row. Chiron has no `cronjob` tool, so only this list
creates jobs. Server timezone: Europe/Madrid. The US market closes at 22:00 Madrid time (21:00 in the few weeks a year
when US and EU daylight saving don't match).

## Hermes facts this list depends on (official docs, the source where they are silent; Hermes v0.22.5)

- `--script` is a **file** inside `~/.hermes/scripts/`, never a command line. A `.sh` file runs under bash. The script's
  environment is cleaned: no API keys are passed in.
- A pre-run script that prints **nothing** skips the AI call. Only a last line `{"wakeAgent": false}` means "skip" on
  purpose; our budget check prints `{"wakeAgent": true}` to run (`scripts/budget.py`, `check()`).
- `hermes cron create` has `--name`, `--workdir`, `--model`, `--provider`, `--script`, `--no-agent`, `--deliver`,
  `--failure-deliver`, `--skill`, `--interpreter`. It has no flag
  for per-job toolsets or for continuable delivery: those exist only in the agent's `cronjob` tool, which Chiron
  doesn't have. So every job gets the toolsets of the `cron` platform (`hermes tools`), and `cron.mirror_delivery: true`
  makes deliveries continuable.
- Turn and wall-clock caps exist only globally (`agent.max_turns`, `agent.run_budget_seconds`), not per job: one
  cap each, from the hungriest job in the week-0 measurement × 1.5. They also limit each message of the Sunday chat.

## Settings for every job

- **Wrappers.** Every script is a `.sh` wrapper from `deploy/scripts/`, copied to `~/.hermes/scripts/`. It does
  `cd /research`, exports `LAB_SANDBOX` (`common.sh`) and runs the command with the project's virtual env
  (`.venv/bin/python -m …`; not `uv run`, which can fail on a sync, and never a bare `python`). The data wrapper reads
  the Tiingo key from `/etc/chiron/tiingo.key` (host only: the agent's container never mounts it). The setup creates
  `registry/` (gitignored; the data log and the budget log need it).
- **LLM jobs:** `--script budget-<track>.sh` (runs `python -m scripts.budget check <track>`), `--model`. The main model
  in `config.yaml` is the strong one: the Sunday lesson is a chat, not a job, and uses it.
- **Toolsets:** `file, terminal, skills` for every job, set once for the `cron` platform, and the same list for
  Telegram chats (the Sunday lesson and every reply to a cron message run there). The terminal adds no access:
  the file tools already run in the same container, with the same mounts and no network. It costs the terminal tool's
  description in every call; the week-0 measurement counts it.
- **No web, anywhere:** `agent.disabled_toolsets` has `web` and `browser` (and `cronjob`), for every session, the CLI
  too. Web tools run in Hermes on the host, not in the container, and need no key; a page written after
  [HOLDOUT_START] would make the holdout useless. Enabling a toolset in `hermes tools` removes it from that list:
  run `deploy/setup.sh` again after any Hermes setup step.
- **The budget wrappers never exit non-zero.** Hermes applies the gate only when the script exits 0; on a crash it runs
  the agent anyway (`cron/scheduler.py`). So if the check command fails, `budget-lab.sh` prints `{"wakeAgent": false}`
  (fail closed: an unknown spend never lets the lab run) and `budget-user.sh` prints `{"wakeAgent": true}` (the user's
  jobs never wait on a broken check); both log the error to `registry/budget.log` and exit 0, even when they can't log.
  `research/tests/test_deploy.py` tests both with a broken check.
- **The user's jobs** (kickoff, quiz, reminder, check): `--deliver telegram`. `--workdir /research`, so `AGENTS.md`
  loads. Continuable (`cron.mirror_delivery: true`), so a reply in Telegram has the message in context; by default a
  cron message is not in the chat history. In Telegram topic mode each delivery opens its own thread: answer inside
  it. The quiz also writes its questions into `progress.md`, so grading works either way.
- **Lab jobs:** `--deliver local --failure-deliver telegram`: their final answer goes to `~/.hermes/cron/output/`, not to
  the user (by default Hermes sends a job's final answer unless it contains `[SILENT]`); the user hears about the lab in
  the Monday kickoff (≤ 3 items), and a failed run still alerts. No workdir (only SOUL.md, memory and `program.md`
  load: the lab never sees the tutor's rules); nothing to continue (they deliver locally).
- **Skills:** every LLM job has the `skills` toolset (`skill_manage` lives there), and `skills.write_approval: true`
  in `config.yaml`, so every skill write from any job or chat is staged in `~/.hermes/pending/skills/` and does nothing
  until reviewed. The skills tools add tokens to every request; the week-0 measurement counts them.
- **Script-only jobs:** `--no-agent --script <wrapper>.sh --deliver telegram`. What the script prints goes to
  Telegram; empty output sends nothing. A non-zero exit sends Hermes's error alert with the script's stderr.
- **One registry writer at a time** (DuckDB): every wrapper that writes it (S1, S2, S3, S4 and the user's `resume`)
  waits for one lock, `registry/.lock` (`flock`). The docs disagree on whether jobs run in parallel; the lock is
  correct either way.

## LLM jobs

| # | Job | When | Model | Budget wrapper | Prompt |
|---|---|---|---|---|---|
| 1 | Kickoff | Mon 09:00 | cheap | `budget-user.sh` | `Monday kickoff. Follow AGENTS.md, "The week", Mon.` |
| 2 | Quiz | Wed 20:00 | cheap | `budget-user.sh` | `Wednesday quiz. Follow AGENTS.md, "The week", Wed.` |
| 3 | Reminder | Sun 10:30 | cheap | `budget-user.sh` | `Sunday reminder. Follow AGENTS.md, "The week", Sun 10:30.` |
| 4 | Weekly check | Sun 19:00 | cheap | `budget-user.sh` | `Weekly check. Follow AGENTS.md, "The week", Sun 19:00.` |
| 5 | Lab close | Tue, Thu, after S1 | cheap | `budget-lab.sh` | `Lab session: close. Follow /research/program.md, section 4, "Close session". Nothing else.` |
| 6 | Lab open | Tue, Thu, after S3 | strong | `budget-lab.sh` | `Lab session: open. Follow /research/program.md, section 4, "Open session". Nothing else.` |

"Cheap" and "strong" are the models picked before the Portal weekend, pinned to exact versions (an alias could move
the training cutoff, and the holdout starts at it). The close session only reads reports and writes files; the open
session runs its smoke test in the terminal.

## Script-only jobs (no LLM)

| # | Job | When | Wrapper | Command | Prints |
|---|---|---|---|---|---|
| S1 | Data, then paper | Mon–Fri, [DATA_TIME] | `data-paper.sh` | `python -m scripts.data > registry/data.log`, then `python -m scripts.paper` | paper events (a sleeve retired, a server error); bad data → exit 1 → Hermes's error alert with the problem list |
| S2 | Paper summary | Mon 08:45 | `paper-summary.sh` | `python -m scripts.paper summary` | the weekly numbers, then any events, before the kickoff |
| S3 | Lab run after close | Tue, Thu, after job 5 | `lab-run.sh` | `python -m harness.lab run` | alerts only (records decisions, step 6) |
| S4 | Lab run after open | Tue, Thu, after job 6 | `lab-run.sh` | `python -m harness.lab run` | alerts only (tests the new cards) |
| S5 | Budget alert | daily 21:00 | `budget-alert.sh` | `python -m scripts.budget alert` | one line at 80% of the week's share |
| S6 | Usage report | Sun 18:45 | `budget-report.sh` | `python -m scripts.budget report` | the weekly usage report, with skipped jobs and the last lab skip reason, before the check |
| S7 | Skill proposals | Sun 18:50 | `skill-proposals.sh` | count the entries in `~/.hermes/pending/skills/` | "N skill proposals wait for review (/skills pending)"; nothing if N = 0 |

[DATA_TIME]: after Tiingo publishes the day's prices; check when that happens on the Portal weekend. If it is after midnight, the
weekday labels of S1 and the Tue/Thu chain move one day later. S1 must end before S2 on Monday morning.
The Tue/Thu chain: S1 → 5 → S3 → 6 → S4, each step after the previous one has ended. Hermes starts jobs only by the
clock (`context_from` reads the last output; it doesn't wait) and may run them in parallel, so each step gets a fixed
time, one slot after the previous one. A slot is longer than `agent.run_budget_seconds` and than the longest script
run; the five times are at the top of `deploy/jobs.sh`. After the gateway was down, each missed job runs once when it
returns, maybe together with the others: then a lab run can refuse a card that the open session hasn't finished
(not a trial; the note says why).

Until week 0 fills `budget.user_jobs` in `lab.yaml`, the budget check skips every lab job ("the cost of the user's jobs
isn't measured yet"; S6 shows the reason). So the week-0 measurement measures the user's jobs first, then the lab jobs.

## Outside Hermes

- No watchdog: the gateway's systemd unit restarts it when it stops (`Restart=always`), and the scheduler runs inside
  the gateway. `hermes cron status` shows whether it ticks.
- The stop-rule reset is the user's: `deploy/scripts/lab-resume.sh` as the `hermes` user, over SSH. It waits for the
  registry lock, so it never runs while S1–S4 write.
