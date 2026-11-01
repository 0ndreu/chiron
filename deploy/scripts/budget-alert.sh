#!/bin/bash
# S5, daily: one line when the week passes 80% of its share.
. "$(dirname "$0")/common.sh"
"$PY" -m scripts.budget alert
