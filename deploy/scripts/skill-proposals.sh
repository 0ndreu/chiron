#!/bin/bash
# S7, Sunday before the weekly check: how many skill writes wait for review. prints nothing when there are none.
n=$(find "${HERMES_HOME:-$HOME/.hermes}/pending/skills" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l)
[ "$n" -eq 0 ] || echo "$n skill proposals wait for review (/skills pending)"
