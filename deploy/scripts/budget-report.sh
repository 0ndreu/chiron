#!/bin/bash
# S6, Sunday before the weekly check: the usage report.
. "$(dirname "$0")/common.sh"
"$PY" -m scripts.budget report
