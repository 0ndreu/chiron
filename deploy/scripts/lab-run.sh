#!/bin/bash
# S3 and S4, after each lab session: record the decisions, test the new cards. prints alerts only.
. "$(dirname "$0")/common.sh"
locked "$PY" -m harness.lab run
