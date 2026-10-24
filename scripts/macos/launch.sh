#!/bin/bash
# The Dock launcher's work (make dock-app builds the app that runs it): start
# Docker if need be, `make up`, open the dashboard's web app (Safari > File >
# Add to Dock), wait for it to quit, then `make down`. With KEEP_RECORDING=1,
# the markets service keeps running (and recording prices) after the rest stops.
#
#   scripts/macos/launch.sh <repo> [web app name]
#   scripts/macos/launch.sh <repo> --which         prints the web app it would open
#
# The web app is the one with that name, or else any Safari web app that opens
# the dashboard (whatever it was called when added).
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
log() { echo "$(date '+%F %T') $*"; }

# find_webapp sets APP_PATH and APP_ID to the dashboard's Safari web app.
APP_PATH='' APP_ID=''
find_webapp() {
  local app plist id url
  for app in "$HOME/Applications/$WEBAPP.app" "/Applications/$WEBAPP.app" "$HOME/Applications"/*.app /Applications/*.app; do
    plist="$app/Contents/Info.plist"
    [ -f "$plist" ] || continue
    id=$(plutil -extract CFBundleIdentifier raw "$plist" 2>/dev/null) || continue
    [[ $id == com.apple.Safari.WebApp.* ]] || continue
    if [[ $(basename "$app") != "$WEBAPP.app" ]]; then
      url=$(plutil -extract Manifest.start_url raw "$plist" 2>/dev/null || plutil -extract WKManifestURL raw "$plist" 2>/dev/null) || continue
      [[ $url == "$URL"* ]] || continue
    fi
    APP_PATH=$app APP_ID=$id
    return 0
  done
  return 1
}
running() { [ "$(osascript -e "application id \"$APP_ID\" is running" 2>/dev/null)" = "true" ]; }

if [ "$WEBAPP" = --which ]; then
  WEBAPP="Football Analytics"
  find_webapp && echo "$APP_PATH ($APP_ID)" || { echo "no web app for $URL"; exit 1; }
  exit 0
fi

if ! mkdir "$LOCK" 2>/dev/null; then
  log "already running; bringing the dashboard forward"
  if find_webapp; then open "$APP_PATH"; else open "$URL"; fi
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

if ! find_webapp; then
  log "no web app for $URL; opening it in the browser and leaving the stack up (make down to stop it)"
  open "$URL"
  exit 0
fi

log "opening $APP_PATH"
open "$APP_PATH"
for _ in $(seq 1 30); do running && break; sleep 1; done
while running; do sleep 5; done

if [ "${KEEP_RECORDING:-0}" = 1 ]; then
  log "$(basename "$APP_PATH" .app) quit: stopping all but the price recorder"
  docker compose stop $(docker compose config --services | grep -vx markets)
  notify "Stopped (still recording prices)"
else
  log "$(basename "$APP_PATH" .app) quit: make down"
  make down
  notify "Stopped"
fi
