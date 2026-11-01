#!/bin/bash
# deploy/setup.sh: turns a fresh Ubuntu 26.04 VPS into the chiron server.
#
# run it as root from the checkout on the server:
#     sudo /opt/chiron/deploy/setup.sh
#
# safe to run again (after every deploy, too): each step checks first, or writes the same result again.
#
# the steps, in order:
#    1. hardening: updates, ssh with keys only, firewall, timezone (the same as the first manual setup)
#    2. swap
#    3. docker, from docker's own apt repository
#    4. the "hermes" user: it runs the agent, every job and every script
#    5. the project: /research, the lab-state folders, the first journal files, the Tiingo key folder
#    6. python: uv and the project's packages
#    7. the sandbox image
#    8. hermes, pinned to one release
#    9. hermes settings
#   10. chiron's files for hermes: SOUL.md and the job wrappers
#   11. the hermes gateway as a user service of hermes (it also runs the job scheduler)
#
# not here: the Tiingo key (a secret: you put it in once by hand, the end of the run says how), the models,
# Telegram and the jobs (they come after the Portal purchase).
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)                   # the checkout this script lives in, e.g. /opt/chiron
RESEARCH=/research                                       # the path every text and job uses: a link to $REPO/research
HERMES_HOME_DIR=/home/hermes
HERMES=$HERMES_HOME_DIR/.local/bin/hermes                # the hermes command, after step 8
HERMES_COMMIT=bf0203a794a07aac3ff764972ab9087baa4e4f4e   # hermes v0.22.5, the latest stable release on 2026-11-01
UV_VERSION=0.13.6

say() { printf '\n=== %s\n' "$*"; }
as_hermes() { sudo -u hermes -H "$@"; }

if [ "$(id -u)" -ne 0 ]; then
    echo "run me as root: sudo $0" >&2
    exit 1
fi
cd /    # commands run as hermes start here; hermes may not be allowed into the folder you ran sudo from


say "1. hardening"
# install every pending update. a new kernel needs a reboot: the end of the run says so; the script never reboots.
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get full-upgrade -y -q
# ssh: keys only, no root login. the name starts with 00 because sshd keeps the first value it reads.
printf '%s\n' 'PermitRootLogin no' 'PasswordAuthentication no' 'KbdInteractiveAuthentication no' \
    >/etc/ssh/sshd_config.d/00-hardening.conf
sshd -t                       # stop here if the ssh config is broken: reloading it could lock everyone out
systemctl reload ssh
# firewall: nothing comes in except ssh. docker goes around ufw only for published ports, and we publish none.
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable
# every job time in hermes/cron-jobs.md is Madrid time
timedatectl set-timezone Europe/Madrid


say "2. swap"
# 4 GB of RAM is tight for hermes, docker and pandas together: swap turns a memory peak into a slowdown instead of
# a killed job. skipped when the server already has swap.
if [ -z "$(swapon --show)" ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >>/etc/fstab
fi


say "3. docker"
# from docker's own apt repository, as docs.docker.com/engine/install/ubuntu shows (Ubuntu 26.04 is supported)
if [ ! -f /etc/apt/sources.list.d/docker.sources ]; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    . /etc/os-release
    printf '%s\n' \
        'Types: deb' \
        'URIs: https://download.docker.com/linux/ubuntu' \
        "Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}" \
        'Components: stable' \
        "Architectures: $(dpkg --print-architecture)" \
        'Signed-By: /etc/apt/keyrings/docker.asc' \
        >/etc/apt/sources.list.d/docker.sources
    apt-get update -q
fi
apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin
# the hermes installer needs these; it can't install them itself, because the hermes user has no sudo
apt-get install -y -q git curl libatomic1


say "4. the hermes user"
# an account with no password and no ssh key: nobody logs in as hermes. it is in the docker group, which is as strong
# as root on this host (accepted for a single-purpose server); the agent's own commands still run in the sandbox.
id hermes >/dev/null 2>&1 || useradd --create-home --home-dir "$HERMES_HOME_DIR" --shell /bin/bash hermes
usermod -aG docker hermes
# a user session that outlives logouts: hermes starts each cron job in its own systemd scope, so a gateway restart
# doesn't kill a running job (hermes docs: cron, restart-safe workers)
loginctl enable-linger hermes


say "5. the project"
# the checkout belongs to hermes: the jobs write the lab state inside it, and later deploys run git pull as hermes
chown -R hermes:hermes "$REPO"
ln -sfn "$REPO/research" "$RESEARCH"
# the lab-state folders (gitignored). the agent's container mounts some of them, and docker would create a missing
# one as root, so they must exist before hermes starts
for dir in registry journal reports data/train books \
           strategies/inbox strategies/decisions strategies/archive strategies/fix strategies/refused; do
    as_hermes mkdir -p "$RESEARCH/$dir"
done
# the first journal files, copied only when missing: on a running server they hold the agent's work
for file in ideas.md progress.md; do
    [ -e "$RESEARCH/journal/$file" ] || as_hermes cp "$RESEARCH/seeds/$file" "$RESEARCH/journal/$file"
done
# the folder for the Tiingo key: root writes it, hermes reads it, the agent's container never mounts it
install -d -m 750 -o root -g hermes /etc/chiron
if [ -e /etc/chiron/tiingo.key ]; then
    chown root:hermes /etc/chiron/tiingo.key
    chmod 640 /etc/chiron/tiingo.key
fi


say "6. python"
# uv, pinned (docs.astral.sh/uv: the installer with the version in its url)
if [ "$(uv --version 2>/dev/null | cut -d' ' -f2)" != "$UV_VERSION" ]; then
    curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi
# python 3.12 and the exact packages from uv.lock. --frozen: use the lock file as it is, never resolve again.
(cd "$RESEARCH" && as_hermes uv sync --frozen)


say "7. the sandbox image"
# one image for the agent's commands and for the lab's strategy runs. docker's cache makes a second run quick.
docker build -q -t chiron-sandbox "$REPO/deploy/sandbox"


say "8. hermes"
# the official installer (hermes docs: installation), run as hermes so it installs into /home/hermes.
# --commit pins the release. skipped when that commit is already installed.
installed=$(as_hermes git -C "$HERMES_HOME_DIR/.hermes/hermes-agent" rev-parse HEAD 2>/dev/null || true)
if [ "$installed" != "$HERMES_COMMIT" ]; then
    curl -fsSL https://hermes-agent.nousresearch.com/install.sh |
        as_hermes bash -s -- --non-interactive --skip-browser --skip-computer-use --commit "$HERMES_COMMIT"
fi


say "9. hermes settings"
# each line is one `hermes config set <key> <value>` (hermes docs: configuration); the comment says why
hset() { as_hermes "$HERMES" config set "$1" "$2" >/dev/null; }

# the agent's commands, file tools and code run in our sandbox container, never on the host
hset terminal.backend docker
hset terminal.docker_image chiron-sandbox
hset terminal.docker_network false                  # --network=none: no internet inside the sandbox
hset terminal.docker_run_as_host_user true          # files the agent writes belong to hermes, not to root
hset terminal.docker_mount_cwd_to_workspace false   # true would mount all of /research read-write
hset terminal.container_memory 1536                 # MB, well below the 4 GB of RAM; the RAM test can change it
hset terminal.cwd "$RESEARCH"                       # the Telegram chat starts in /research, so AGENTS.md loads

# what the agent's container sees: each path at the same place as on the host. read-only, except the three folders
# the agent writes. not mounted at all: data/all/ (later prices), registry/, harness/, scripts/, the Tiingo key.
read_only="program.md AGENTS.md lab.yaml universe.yaml curriculum reports data/train books
           strategies/archive strategies/fix strategies/refused"
writable="journal strategies/inbox strategies/decisions"
volumes=""
for path in $read_only; do volumes+="\"$RESEARCH/$path:$RESEARCH/$path:ro\", "; done
for path in $writable; do volumes+="\"$RESEARCH/$path:$RESEARCH/$path\", "; done
hset terminal.docker_volumes "[${volumes%, }]"

# off in every session, the CLI too:
#   cronjob: a chat could create, change or remove jobs, and skip the budget check (cron agents can't by default)
#   web, browser: they run in hermes on the host, outside the sandbox, and a page written after the holdout start
#     would make the holdout useless. they need no key, so they would work without this line.
# enabling one of them in `hermes tools` removes it from this list: run this script again after any hermes setup.
hset agent.disabled_toolsets '["cronjob", "web", "browser"]'
# every cron job and every Telegram chat gets the same short list: per-job lists exist only in the cronjob tool,
# and Telegram's default list has ~40 tools (images, speech, sub-agents...) whose descriptions cost tokens per message
hset platform_toolsets.cron '["file", "terminal", "skills"]'
hset platform_toolsets.telegram '["file", "terminal", "skills"]'
# a reply to a cron message in Telegram continues it, with the message in context
hset cron.mirror_delivery true
# every skill the agent writes waits for the user's review (/skills pending)
hset skills.write_approval true
# one warning near the turn cap, so a session can still write "stopped at cap". it works once week 0 sets
# agent.max_turns (the measurement gives the number).
hset agent.budget_warning_ratio 0.8
# no update checks and no usage metrics leave the server
hset updates.check false
hset telemetry.shared_metrics.enabled false
hset telemetry.shared_metrics.send false
hset timezone Europe/Madrid


say "10. chiron's files for hermes"
# hermes loads SOUL.md only from its own folder (hermes docs: context files): a copy, renewed on every run
as_hermes install -m 644 "$REPO/hermes/SOUL.md" "$HERMES_HOME_DIR/.hermes/SOUL.md"
# the job wrappers: hermes runs only scripts inside ~/.hermes/scripts/, and it refuses links that point outside
as_hermes mkdir -p "$HERMES_HOME_DIR/.hermes/scripts"
as_hermes install -m 755 "$REPO"/deploy/scripts/*.sh "$HERMES_HOME_DIR/.hermes/scripts/"
# the user's stop-rule reset as one short command over ssh: chiron-resume
printf '#!/bin/sh\nexec sudo -u hermes bash %s/deploy/scripts/lab-resume.sh\n' "$REPO" >/usr/local/bin/chiron-resume
chmod 755 /usr/local/bin/chiron-resume


say "11. the gateway service"
# a user service of hermes, never a system one (hermes docs: "Non-Sudo / System Service User Installs"): hermes's
# files must belong to hermes, so root never runs the hermes command. linger (step 4) starts it at boot, its unit has
# Restart=always (no extra watchdog), and the cron jobs get their restart-safe systemd scopes from the same session.
# logs: sudo -u hermes XDG_RUNTIME_DIR=/run/user/$(id -u hermes) journalctl --user -u hermes-gateway
as_hermes_user() { as_hermes env XDG_RUNTIME_DIR="/run/user/$(id -u hermes)" "$@"; }   # systemctl --user needs it
as_hermes_user "$HERMES" gateway install
# sandbox containers made with the old settings or old files: remove them, hermes makes new ones on the next command
docker ps -aq --filter label=hermes-agent=1 | xargs -r docker rm -f >/dev/null
as_hermes_user systemctl --user restart hermes-gateway


say "done"
echo "hermes $(as_hermes git -C "$HERMES_HOME_DIR/.hermes/hermes-agent" rev-parse --short HEAD), $(docker --version), $(uv --version)"
if [ ! -e /etc/chiron/tiingo.key ]; then
    echo "missing: the Tiingo key. put it in once:  sudo sh -c 'cat > /etc/chiron/tiingo.key'"
    echo "         (paste the key, press Enter, then Ctrl-D), then run this script again"
fi
if [ -e /var/run/reboot-required ]; then
    echo "the updates need a reboot: sudo reboot"
fi
