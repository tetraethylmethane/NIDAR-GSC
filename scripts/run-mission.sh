#!/usr/bin/env bash
# Start the ground station in MISSION mode. This is the competition launcher.
#
# WHY THIS EXISTS
# scripts/run-gs.sh is the DEV launcher and always has been: zsh, an interactive
# `vared` prompt for a serial port, FLASK_ENV=development, and no MISSION_MODE.
# It starts the build that registers the legacy blueprint's 31 routes --
# including /uav/commands/insert and /uav/commands/jump, each a -50 under rule
# 8.16. It is also the only launcher the docs mention, so the documented way to
# start the ground station on competition day was the wrong build.
#
# Mission mode never imports apps.uav, apps.image or groundstation, so DroneKit
# is absent from the process rather than merely unused, and there is no command
# route to reach. SYS-20 is satisfied by construction, not by a guard.
#
#   ./scripts/run-mission.sh
#
# Refuses to start rather than starting wrong. Every check below is one that
# has already failed silently at least once on this project.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
SERVER="$REPO/server"
CLIENT="$REPO/client"
PORT="${PORT:-5000}"

die() { echo "REFUSING TO START: $*" >&2; exit 1; }

echo "=== pre-flight ==="

# 1. Rule 8.4: no external network. A GCS that can reach the internet is a
#    protest waiting to happen, and the tile cache hides the failure until the
#    venue has no signal.
if [ "${ALLOW_NETWORK:-0}" = "1" ]; then
  # Never claim a check passed when it was skipped. An operator scanning this
  # output at t+30 s in a five-minute window reads the left-hand column, not
  # the environment they set two minutes ago.
  echo "  network check SKIPPED (ALLOW_NETWORK=1) -- not competition-legal"
else
  if timeout 3 getent hosts one.one.one.one >/dev/null 2>&1 \
     || timeout 3 bash -c 'exec 3<>/dev/tcp/1.1.1.1/443' 2>/dev/null; then
    die "this machine can reach the internet. Rule 8.4 requires no external
    network. Turn Wi-Fi off in hardware, then re-run. ALLOW_NETWORK=1 overrides
    for bench work -- never on competition day."
  fi
  echo "  no external network"
fi

# 2. Offline tiles. Empty cache means a blank map, which means no visible
#    boundary, no aircraft, and no evidence path for 250 detection points.
TILES="$CLIENT/public/map"
if [ ! -d "$TILES" ] || [ -z "$(find "$TILES" -name '*.png' -o -name '*.jpg' 2>/dev/null | head -1)" ]; then
  die "no cached map tiles in $TILES. With the network down the map renders
    blank. Run:
      python server/utils/slippy_map_getter.py --center LAT,LON --radius-km 10
      python server/utils/slippy_map_getter.py --verify"
fi
echo "  tiles present: $(find "$TILES" \( -name '*.png' -o -name '*.jpg' \) | wc -l) files"

[ -f "$SERVER/config.json" ] || cp "$SERVER/sample.config.json" "$SERVER/config.json"

echo
echo "=== starting mission build ==="
cd "$SERVER" || die "no server directory at $SERVER"

MISSION_MODE=1 NIDAR_INGEST=1 python3 - "$PORT" <<'PY' &
import sys, app
app.app.run(host="0.0.0.0", port=int(sys.argv[1]),
            use_reloader=False, threaded=True)
PY
SRV=$!
sleep 5

# 3. Assert the build that came up is the one we asked for. "We set the env var"
#    is a claim about intent; the URL map is a fact about the process.
base="http://127.0.0.1:$PORT"
fleet=$(curl -sf "$base/api/fleet" || true)
[ -n "$fleet" ] || { kill $SRV 2>/dev/null; die "server did not answer on $base"; }

case "$fleet" in
  *'"mission_mode":true'*|*'"mission_mode": true'*) echo "  mission_mode: true" ;;
  *) kill $SRV 2>/dev/null
     die "server started in DEV mode. Command routes are live and each one is
    a -50 under rule 8.16." ;;
esac

code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$base/uav/commands/insert")
if [ "$code" = "403" ]; then
  echo "  /uav/commands/insert -> 403 blocked (SYS-20)"
else
  kill $SRV 2>/dev/null
  die "/uav/commands/insert answered $code, expected 403. A mission-altering
    route is reachable."
fi

echo
echo "  GCS up on $base  (mission mode, no command routes)"
echo "  start the client separately, or open the built page"
echo "  Ctrl-C to stop"
wait $SRV
