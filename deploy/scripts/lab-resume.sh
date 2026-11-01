#!/bin/bash
# the stop-rule reset, run by the user over SSH as the hermes user. it waits for the registry lock, so it never
# runs while a lab or paper job writes.
. "$(dirname "$0")/common.sh"
locked "$PY" -m harness.lab resume
