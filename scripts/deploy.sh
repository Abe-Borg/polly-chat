#!/usr/bin/env bash
# Deploy the latest commit onto the droplet.
#
# The GitHub Actions workflow pipes this file to `bash -s` over SSH, so the
# version that runs is always the one from the commit being deployed. It is a
# normal script otherwise — `bash scripts/deploy.sh` on the droplet works too.
#
# Override any of the settings below by exporting them first.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/policita}"
SERVICE_NAME="${SERVICE_NAME:-policita}"
BRANCH="${BRANCH:-master}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/health}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-45}"

log() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

find_pip() {
    for candidate in "$APP_DIR/venv/bin/pip" "$APP_DIR/.venv/bin/pip"; do
        if [ -x "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

install_deps() {
    local pip
    if pip=$(find_pip); then
        "$pip" install --quiet --upgrade --requirement requirements.txt
    else
        echo "No virtualenv found under $APP_DIR — skipping dependency install." >&2
        echo "Create one with: python3 -m venv $APP_DIR/venv" >&2
        return 1
    fi
}

# Waits for the app to answer, then prints the health report.
wait_for_health() {
    local deadline=$((SECONDS + HEALTH_TIMEOUT)) body
    while [ "$SECONDS" -lt "$deadline" ]; do
        if body=$(curl -fsS --max-time 10 "$HEALTH_URL" 2>/dev/null); then
            printf '%s' "$body"
            return 0
        fi
        sleep 2
    done
    return 1
}

cd "$APP_DIR"

PREVIOUS=$(git rev-parse HEAD)
log "Deploying $BRANCH to $APP_DIR (currently at ${PREVIOUS:0:7})"

log "Fetching"
git fetch --quiet origin "$BRANCH"
# Reset rather than pull: the droplet is a deployment target, not a workspace,
# and a stray local edit should never turn a deploy into a merge conflict.
git reset --hard --quiet "origin/$BRANCH"
TARGET=$(git rev-parse HEAD)

if [ "$TARGET" = "$PREVIOUS" ]; then
    log "Already at ${TARGET:0:7} — restarting anyway to pick up any config change"
fi

log "Installing dependencies"
install_deps

log "Restarting $SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

log "Waiting for health check"
if ! REPORT=$(wait_for_health); then
    echo "The app did not answer $HEALTH_URL within ${HEALTH_TIMEOUT}s." >&2
    echo "Rolling back to ${PREVIOUS:0:7}." >&2
    git reset --hard --quiet "$PREVIOUS"
    install_deps || true
    sudo systemctl restart "$SERVICE_NAME"
    echo "Rolled back. Recent logs:" >&2
    sudo journalctl -u "$SERVICE_NAME" -n 40 --no-pager >&2 || true
    exit 1
fi

echo "$REPORT"

# A healthy process that cannot reach the agent is a configuration problem, not
# a bad deploy — rolling back would only hide the report that identifies it.
if printf '%s' "$REPORT" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("agent_reachable") else 1)'; then
    log "Deployed ${TARGET:0:7} — app healthy, agent reachable"
else
    log "Deployed ${TARGET:0:7} — app is up, but it cannot reach the agent"
    echo "Read the report above: agent_detail names the cause, and" >&2
    echo "api_key_configured: false means the process never loaded its environment." >&2
fi
