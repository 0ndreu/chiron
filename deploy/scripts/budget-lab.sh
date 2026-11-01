#!/bin/bash
# pre-run gate of the lab jobs. Hermes ignores the gate of a failed script and runs the agent, so this wrapper never
# fails: a broken check skips the lab (an unknown spend never lets it run) and logs why.
RESEARCH=${CHIRON_RESEARCH:-/research}
log=$RESEARCH/registry/budget.log
if out=$(cd "$RESEARCH" && "$RESEARCH/.venv/bin/python" -m scripts.budget check lab 2>>"$log") && [ -n "$out" ]; then
    echo "$out"
else
    echo "$(date '+%F %T') budget-lab.sh: the check failed, the lab job is skipped" >>"$log"
    echo '{"wakeAgent": false}'
fi
exit 0
