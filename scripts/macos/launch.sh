#!/bin/bash
# The Dock launcher's work (make dock-app builds the app that runs it): start
# Docker if need be, `make up`, open the dashboard's web app (Safari > File >
# Add to Dock), wait for it to quit, then `make down`. With KEEP_RECORDING=1,
# the markets service keeps running (and recording prices) after the rest stops.
#
#   scripts/macos/launch.sh <repo> [web app name]
#
# Logs to ~/Library/Logs/football-analytics-launcher.log. A second launch while
# one is running just brings the web app forward.
set -uo pipefail

REPO=${1:?usage: launch.sh <repo> [web app name]}
WEBAPP=${2:-Football Analytics}
URL=http://localhost:3000
LOCK=${TMPDIR:-/tmp}/football-analytics-launcher.lock
export PATH="$HOME/.docker/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

notify() { osascript -e "display notification \"$1\" with title \"Football Analytics\"" >/dev/null 2>&1 || true; }
running() { [ "$(osascript -e "application \"$WEBAPP\" is running" 2>/dev/null)" = "true" ]; }
webapp_installed() { [ -d "$HOME/Applications/$WEBAPP.app" ] || [ -d "/Applications/$WEBAPP.app" ]; }
log() { echo "$(date '+%F %T') $*"; }

if ! mkdir "$LOCK" 2>/dev/null; then
  log "already running; bringing the dashboard forward"
  webapp_installed && open -a "$WEBAPP" || open "$URL"
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

cd "$REPO" || { notify "Can't find $REPO"; exit 1; }

if ! docker info >/dev/null 2>&1; then
  log "starting Docker Desktop"
  notify "Starting Docker…"
  open -a Docker
  for _ in $(seq 1 90); do docker info >/dev/null 2>&1 && break; sleep 2; done
  docker info >/dev/null 2>&1 || { notify "Docker didn't start"; log "Docker didn't start"; exit 1; }
fi

log "make up"
notify "Starting the stack…"
if ! make up; then
  notify "make up failed: see ~/Library/Logs/football-analytics-launcher.log"
  exit 1
fi

if ! webapp_installed; then
  log "no $WEBAPP.app; opening $URL in the browser and leaving the stack up (make down to stop it)"
  open "$URL"
  exit 0
fi

log "opening $WEBAPP"
open -a "$WEBAPP"
for _ in $(seq 1 30); do running && break; sleep 1; done
while running; do sleep 5; done

if [ "${KEEP_RECORDING:-0}" = 1 ]; then
  log "$WEBAPP quit: stopping all but the price recorder"
  docker compose stop $(docker compose config --services | grep -vx markets)
  notify "Stopped (still recording prices)"
else
  log "$WEBAPP quit: make down"
  make down
  notify "Stopped"
fi
