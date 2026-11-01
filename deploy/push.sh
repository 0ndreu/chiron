#!/bin/bash
# deploy/push.sh: copies the code from this laptop to the server. only while the server setup is built: after that
# the server updates only with `git pull`, and this file is deleted.
#
#     deploy/push.sh       copy to chiron:/opt/chiron (the ssh host "chiron": ubuntu, with sudo)
#     deploy/push.sh -n    dry run: list what would change, change nothing
#
# then run the setup on the server, after every push:  ssh chiron 'sudo /opt/chiron/deploy/setup.sh'
#
# it copies research/, hermes/ and deploy/. it never copies, and never deletes on the server: the virtual env, the
# python caches, the data, the lab state (the lab-state folders in .gitignore) and the course books.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
DEST=${CHIRON_DEST:-chiron:/opt/chiron}   # a local folder instead, for a test

cd "$REPO"
# -rlpt: folders, links, permissions and times, but not the laptop's owner: setup.sh gives the checkout to hermes.
# --delete: a file deleted or renamed here goes away on the server too. an excluded path is never deleted.
# --rsync-path: on the server rsync runs as root, because the checkout belongs to hermes (it makes /opt/chiron too).
rsync -rlpt --delete --itemize-changes "$@" \
    --rsync-path='sudo rsync' \
    --exclude='.DS_Store' --exclude='.venv/' --exclude='__pycache__/' --exclude='.pytest_cache/' \
    --exclude='/research/data/' --exclude='/research/registry/' --exclude='/research/strategies/' \
    --exclude='/research/reports/' --exclude='/research/journal/' --exclude='/research/books/' \
    research hermes deploy "$DEST/"
echo "next: ssh chiron 'sudo /opt/chiron/deploy/setup.sh'"
