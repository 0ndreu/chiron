#!/bin/bash
# pre-run gate of the user's jobs. Hermes ignores the gate of a failed script and runs the agent, so this wrapper never
# fails: a broken check lets the user's job run (it never waits on a broken check) and logs why.
RESEARCH=${CHIRON_RESEARCH:-/research}
log=$RESEARCH/registry/budget.log
if out=$(cd "$RESEARCH" && "$RESEARCH/.venv/bin/python" -m scripts.budget check user 2>>"$log") && [ -n "$out" ]; then
    echo "$out"
else
    echo "$(date '+%F %T') budget-user.sh: the check failed, the user's job runs anyway" >>"$log"
    echo '{"wakeAgent": true}'
fi
exit 0
