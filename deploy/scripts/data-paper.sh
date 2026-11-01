#!/bin/bash
# S1, weekdays after the US close: new prices, then the paper portfolios. bad data: data.py exits 1 with the problem
# list on stderr, nothing is written, and Hermes sends it as an error alert.
. "$(dirname "$0")/common.sh"
TIINGO_API_KEY=$(cat /etc/chiron/tiingo.key) "$PY" -m scripts.data >registry/data.log
locked "$PY" -m scripts.paper
