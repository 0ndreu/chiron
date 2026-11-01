#!/bin/bash
# S2, Monday before the kickoff: the weekly paper numbers.
. "$(dirname "$0")/common.sh"
locked "$PY" -m scripts.paper summary
