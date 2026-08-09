#!/usr/bin/env bash
# The whole system, flying.
#
#   coverage planner -> QGC WPL 110 -> 3 x ArduCopter SITL in AUTO
#                                   -> ground station (SYSID 1/2/3, one port)
#                                   -> browser
#
# This is the loop the ground station exists to serve. Until it ran, the
# planner was unit-tested, SITL had flown nothing, and the GCS had watched
# three aircraft sit on the ground.
#
# REQUIREMENTS
#   * ArduPilot SITL built:  ~/ardupilot/build/sitl/bin/arducopter
#     (./waf configure --board sitl && ./waf copter)
#   * The systems repo checked out next to this one, or NIDAR_SYS pointing at it
#   * python3 with flask, flask-cors, pymavlink
#
#   ./scripts/sim-flight.sh [hold_seconds]
#   SPEEDUP=1 ./scripts/sim-flight.sh 600      # real time, for recording
#
# TWO MAVLINK OUTPUTS PER AIRCRAFT
#   serial0 -> 127.0.0.1:14550   the GCS, all three multiplexed by SYSID
#   serial1 -> 127.0.0.1:1456N   a private link for the planner/uploader
#
# The private link exists so the uploader can run a MISSION_COUNT/REQUEST
# handshake with ONE aircraft without the other two answering on the same
# socket. At the venue mavlink-router does this routing; here a second serial
# port is simpler and exercises the same GCS path.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_GSC="$(dirname "$HERE")"
REPO_SYS="${NIDAR_SYS:-$(dirname "$REPO_GSC")/Drikr-NIDAR}"
AP="${ARDUPILOT:-$HOME/ardupilot}"
BIN="$AP/build/sitl/bin/arducopter"
RUN=/tmp/nidar-fly
HOLD="${1:-1200}"

[ -x "$BIN" ] || { echo "SITL not built: $BIN"; exit 2; }
[ -d "$REPO_SYS/autonomy" ] || {
  echo "systems repo not found at $REPO_SYS -- set NIDAR_SYS"; exit 2; }

rm -rf "$RUN"; mkdir -p "$RUN"
pkill -f 'build/sitl/bin/arducopter' 2>/dev/null || true
pkill -f 'nidar_server.py' 2>/dev/null || true
pkill -f 'sim_mission.py'  2>/dev/null || true
sleep 1

# --- ground station --------------------------------------------------------
cat > "$RUN/nidar_server.py" <<'PY'
import os, sys
sys.path.insert(0, os.environ["SERVER_DIR"])
os.chdir(os.environ["SERVER_DIR"])
import app
app.app.run(host="0.0.0.0", port=5000, use_reloader=False, threaded=True)
PY
export SERVER_DIR="$REPO_GSC/server"
cd "$SERVER_DIR"
[ -f config.json ] || cp sample.config.json config.json
MISSION_MODE=1 NIDAR_INGEST=1 python3 "$RUN/nidar_server.py" > "$RUN/server.log" 2>&1 &
SRV=$!
sleep 5
curl -sf http://127.0.0.1:5000/api/fleet >/dev/null || {
  echo "backend did not start"; tail -20 "$RUN/server.log"; exit 1; }
echo "backend up"

# --- three aircraft --------------------------------------------------------
# THE AIRCRAFT MUST FLY THE AIRCRAFT'S PARAMETERS.
#
# This launched with stock copter.parm and nothing else for as long as it has
# existed. firmware/ardupilot-params/ has carried a reviewed, validated,
# unit-tested failsafe set the whole time -- and no simulation ever loaded it.
# Stock ArduCopter ships BATT_FS_LOW_ACT = 0 and BATT_LOW_MAH = 0, so the
# battery failsafe was DISABLED in every run: a low battery did nothing at all,
# and the aircraft flew until the sim battery hit zero. That is exactly what a
# reviewer sees in a simulation video and reads as "it does not come home".
#
# Same class of bug as mavlink-router's Mode = Normal: a config that parses,
# starts, looks right in review, and is not in the path.
PARAMS_DIR="$REPO_SYS/firmware/ardupilot-params"
for i in 1 2 3; do
  [ -f "$PARAMS_DIR/rescueswarm-drone$i.parm" ] || {
    echo "missing $PARAMS_DIR/rescueswarm-drone$i.parm"
    echo "generate with: python params.py --drones 3 --out ."
    echo "refusing to fly stock defaults -- that is the bug this check exists for"
    exit 2; }
done

for i in 1 2 3; do
  d="$RUN/sitl$i"; mkdir -p "$d"
  lon=$(python3 -c "print(80.0000 + ($i-1)*0.0010)")
  port=$((14559 + i))
  # --defaults takes a comma-separated list, applied left to right, so the
  # project set overrides the stock set rather than merely sitting beside it.
  ( cd "$d"; "$BIN" --model quad --instance $((i-1)) --sysid "$i" \
      --home "12.9990,$lon,10,0" \
      --serial0 "udpclient:127.0.0.1:14550" \
      --serial1 "udpclient:127.0.0.1:$port" \
      --defaults "$AP/Tools/autotest/default_params/copter.parm,$PARAMS_DIR/rescueswarm-drone$i.parm" \
      > "$d/sitl.log" 2>&1 ) &
done
echo "3 ArduCopter SITL launched with rescueswarm-drone{1,2,3}.parm"

# Mission state: survivors, deliveries, phases. MAVLink carries none of it.
python3 "$REPO_GSC/scripts/sim_mission.py" --speed 6 --port 14660 \
    > "$RUN/sim_mission.log" 2>&1 &

sleep 12

# --- plan, upload, fly -----------------------------------------------------
cd "$REPO_SYS"
FLY_S="$HOLD" SPEEDUP="${SPEEDUP:-5}" NIDAR_SYS="$REPO_SYS" \
    python3 "$REPO_GSC/scripts/fly_plan.py" 2>&1 | tee "$RUN/fly.log"

echo
echo "=== fleet as the GCS sees it ==="
curl -s --max-time 5 http://127.0.0.1:5000/api/fleet | python3 -m json.tool | head -45

pkill -f 'build/sitl/bin/arducopter' 2>/dev/null || true
kill $SRV 2>/dev/null || true
echo FLYSTACK_DONE
