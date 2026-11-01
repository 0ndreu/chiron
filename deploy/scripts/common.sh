# shellcheck shell=bash
# sourced by the script-only wrappers (not the budget gates): the project, its virtual env, the strategy sandbox and
# the registry lock. any failure stops the wrapper with a non-zero exit, and Hermes sends an error alert.
set -euo pipefail
RESEARCH=${CHIRON_RESEARCH:-/research}
cd "$RESEARCH"
# shellcheck disable=SC2034  # used by the wrappers that source this file
PY=$RESEARCH/.venv/bin/python
# the agent's strategy code runs here: no network, no host files, read-only, an unprivileged user (harness/sandbox.py)
export LAB_SANDBOX='docker run --rm -i --network none --read-only --tmpfs /tmp:size=64m --user 65534:65534 --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 1g --mount type=bind,src={harness},dst=/w/harness,readonly -w /w chiron-sandbox python -m harness.sandbox'
# DuckDB allows one writer, and Hermes may run jobs in parallel: every registry writer waits for this lock
locked() { flock -w 1800 registry/.lock "$@"; }
