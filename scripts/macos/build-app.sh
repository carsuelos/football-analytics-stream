#!/bin/bash
# Builds "Football Analytics Launcher.app" (make dock-app): a Dock icon that
# runs scripts/macos/launch.sh for this checkout. It replaces the app where it
# already is (/Applications or ~/Applications), so the Dock keeps pointing at
# it; a first build goes to ~/Applications.
#
#   scripts/macos/build-app.sh [web app name]      KEEP_RECORDING=1 to keep recording prices on close
set -euo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
WEBAPP=${1:-Football Analytics}
NAME="Football Analytics Launcher.app"
APP="$HOME/Applications/$NAME"
[ -d "/Applications/$NAME" ] && APP="/Applications/$NAME"
LOG="$HOME/Library/Logs/football-analytics-launcher.log"
q() { printf "'%s'" "${1//\'/\'\\\'\'}"; } # shell-quote

mkdir -p "$(dirname "$APP")"
rm -rf "$APP"
cmd="KEEP_RECORDING=${KEEP_RECORDING:-0} nohup $(q "$REPO/scripts/macos/launch.sh") $(q "$REPO") $(q "$WEBAPP") >> $(q "$LOG") 2>&1 &"
osacompile -o "$APP" -e "do shell script \"${cmd//\"/\\\"}\""

# The heat-tiles icon in the macOS app shape (app-icon.svg, rendered to
# app-icon.png at 1024 px).
set_icon() {
  local work
  work=$(mktemp -d)
  mkdir "$work/icon.iconset"
  local src="$REPO/scripts/macos/app-icon.png"
  for size in 16 32 128 256 512; do
    sips -z $size $size "$src" --out "$work/icon.iconset/icon_${size}x${size}.png" >/dev/null
    sips -z $((size * 2)) $((size * 2)) "$src" --out "$work/icon.iconset/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "$work/icon.iconset" -o "$APP/Contents/Resources/applet.icns"
  rm -rf "$work"
}
set_icon
# Newer AppleScript apps carry their icon in Assets.car, which wins over the
# .icns; drop it so ours shows. Changing the bundle breaks its signature, so
# sign it again (ad hoc: it only runs on this Mac).
rm -f "$APP/Contents/Resources/Assets.car"
/usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" "$APP/Contents/Info.plist" 2>/dev/null || true
codesign --force --deep --sign - "$APP" 2>/dev/null
touch "$APP"

echo "Built $APP"
echo "  It runs make up, opens \"$WEBAPP\" (Safari > File > Add to Dock), and runs make down when you quit it."
echo "  Drag it to the Dock (open $(dirname "$APP")). Log: $LOG"
