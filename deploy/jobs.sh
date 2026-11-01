#!/bin/bash
# deploy/jobs.sh: creates every job in hermes/cron-jobs.md, one line per row of its two tables.
#
# run it as root on the server, after setup.sh, once the values below are filled in and committed:
#     sudo /opt/chiron/deploy/jobs.sh
#
# safe to run again: each line first removes its own old job (same name), then creates it again.
# a row you delete from this file leaves its old job behind: remove it by hand (hermes cron remove chiron-<name>).
#
# the steps:
#    1. the values decided with the models: the script stops while one is empty
#    2. the three kinds of job: the user's, the lab's, script-only
#    3. the jobs, in the order of hermes/cron-jobs.md
set -euo pipefail


# 1. the values decided with the models (the script stops while one is empty)
# exact versions only: an alias could move the training cutoff, and the holdout starts at it (lab.yaml)
CHEAP="anthropic/claude-haiku-5.5"     # the lab's close session
STRONG="anthropic/claude-sonnet-5.5"   # the lab's open session
TUTOR="anthropic/claude-sonnet-5.5"    # the user's jobs (picked blind in the comparison)
PROVIDER="nous"
# the Tue/Thu chain: S1 -> lab close -> S3 -> lab open -> S4. hermes starts jobs only by the clock (context_from
# doesn't wait) and may run them in parallel, so each step gets its own time, one slot after the previous one.
# a slot is longer than agent.run_budget_seconds and than the longest script run.
# cron format, Madrid time: "minute hour * * weekdays", 0 = Sunday.
# Tiingo's corrections end at 8 PM ET (02:00 Madrid), so S1 runs at 02:30 the next morning (Tue-Sat for the Mon-Fri
# closes) and the chain runs Wed and Fri. slot: 30 min (the longest session in the comparison took 94 s).
DATA_AT="30 2 * * 2-6"     # S1, after every trading day
CLOSE_AT="0 3 * * 3,5"     # lab close
S3_AT="30 3 * * 3,5"       # lab run after close
OPEN_AT="0 4 * * 3,5"      # lab open
S4_AT="30 4 * * 3,5"       # lab run after open

for value in CHEAP STRONG TUTOR PROVIDER DATA_AT CLOSE_AT S3_AT OPEN_AT S4_AT; do
    if [ -z "${!value}" ]; then
        echo "fill in $value at the top of $0 first" >&2
        exit 1
    fi
done
if [ "$(id -u)" -ne 0 ]; then
    echo "run me as root: sudo $0" >&2
    exit 1
fi
HERMES=/home/hermes/.local/bin/hermes
if [ ! -x "$HERMES" ]; then
    echo "hermes isn't installed: run deploy/setup.sh first" >&2
    exit 1
fi
cd /    # commands run as hermes start here; hermes may not be allowed into the folder you ran sudo from


# 2. the three kinds of job
# every job belongs to the hermes user (its ~/.hermes/cron/jobs.json), and its name starts with "chiron-"
cron() { sudo -u hermes -H "$HERMES" cron "$@"; }
# a job that doesn't exist yet is fine: the first run, or a new row
new_job() { cron remove "chiron-$1" >/dev/null 2>&1 || true; }

# the user's jobs: the budget check for the user's track (never skips on a broken check), the answer goes to
# Telegram, and /research is the workdir, so AGENTS.md loads
user_job() {   # name, schedule, prompt
    new_job "$1"
    cron create "$2" "$3" --name "chiron-$1" --model "$TUTOR" --provider "$PROVIDER" \
        --script budget-user.sh --workdir /research --deliver telegram
}
# the lab's jobs: the budget check for the lab's track (skips on a broken check), no workdir (the lab never sees the
# tutor's rules), the answer stays on the server (~/.hermes/cron/output/), only a failure goes to Telegram
lab_job() {    # name, schedule, model, prompt
    new_job "$1"
    cron create "$2" "$4" --name "chiron-$1" --model "$3" --provider "$PROVIDER" \
        --script budget-lab.sh --deliver local --failure-deliver telegram
}
# script-only jobs: no LLM. what the script prints goes to Telegram; nothing printed, no message; a non-zero exit
# sends hermes's error alert with the script's stderr
script_job() { # name, schedule, wrapper in ~/.hermes/scripts/
    new_job "$1"
    cron create "$2" --name "chiron-$1" --no-agent --script "$3" --deliver telegram
}


# 3. the jobs (hermes/cron-jobs.md). the prompts are word for word the same as there.
# the LLM jobs, rows 1-6
user_job   kickoff         "0 9 * * 1"    'Monday kickoff. Follow AGENTS.md, "The week", Mon. At the end, update journal/progress.md (AGENTS.md, "progress.md").'
user_job   quiz            "0 20 * * 3"   'Wednesday quiz. Follow AGENTS.md, "The week", Wed. At the end, update journal/progress.md (AGENTS.md, "progress.md").'
user_job   reminder        "30 10 * * 0"  'Sunday reminder. Follow AGENTS.md, "The week", Sun 10:30. At the end, update journal/progress.md (AGENTS.md, "progress.md").'
user_job   check           "0 19 * * 0"   'Weekly check. Follow AGENTS.md, "The week", Sun 19:00. At the end, update journal/progress.md (AGENTS.md, "progress.md").'
lab_job    lab-close       "$CLOSE_AT"    "$CHEAP"  'Lab session: close. Follow /research/program.md, section 4, "Close session". Nothing else.'
lab_job    lab-open        "$OPEN_AT"     "$STRONG" 'Lab session: open. Follow /research/program.md, section 4, "Open session". Nothing else.'
# the script-only jobs, rows S1-S7
script_job data-paper      "$DATA_AT"     data-paper.sh
script_job paper-summary   "45 8 * * 1"   paper-summary.sh
script_job lab-run-close   "$S3_AT"       lab-run.sh
script_job lab-run-open    "$S4_AT"       lab-run.sh
script_job budget-alert    "0 21 * * *"   budget-alert.sh
script_job usage-report    "45 18 * * 0"  budget-report.sh
script_job skill-proposals "50 18 * * 0"  skill-proposals.sh

cron list
