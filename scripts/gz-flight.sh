#!/usr/bin/env bash
# ArduPilot SITL flying inside Gazebo, with a DOWNWARD camera writing frames.
#
# This is the one thing plain SITL cannot give you. sim-flight.sh flies the
# coverage plan on three aircraft with real dynamics, a real EKF and real
# failsafe logic -- but SITL renders nothing, so the perception half of the
# mission has never had pixels. Survivors have only ever come from
# sim_mission.py.
#
#   ./scripts/gz-flight.sh              fly and capture frames
#   ./scripts/gz-flight.sh --no-capture just fly
#
# WHAT IT IS GOOD FOR: plumbing. Does a detection become a geotag, does the
# geotag reach the GCS, does a delivery get assigned, does the chain hold for
# eight minutes.
#
# WHAT IT IS NOT GOOD FOR: recall. Synthetic scenery flatters a detector and
# recall is worth 250 points. Measure that on real flood imagery.
set -uo pipefail

AP="${ARDUPILOT:-$HOME/ardupilot}"
BIN="$AP/build/sitl/bin/arducopter"
PLUGIN_DIR="${ARDUPILOT_GAZEBO:-$HOME/ardupilot_gazebo}"
CAM_SDF="$PLUGIN_DIR/models/gimbal_small_3d/model.sdf"
CAPTURE_DIR=/tmp/gzcam
OUT=/tmp/gzflight
CAPTURE=1
[ "${1:-}" = "--no-capture" ] && CAPTURE=0

export GZ_SIM_SYSTEM_PLUGIN_PATH=$PLUGIN_DIR/build:${GZ_SIM_SYSTEM_PLUGIN_PATH:-}
export GZ_SIM_RESOURCE_PATH=$PLUGIN_DIR/models:$PLUGIN_DIR/worlds:${GZ_SIM_RESOURCE_PATH:-}

[ -x "$BIN" ] || { echo "SITL not built: $BIN"; exit 2; }
[ -d "$PLUGIN_DIR/build" ] || { echo "run scripts/install-gazebo.sh first"; exit 2; }

# ---- frame capture -------------------------------------------------------
# Gazebo has no headless way to pull images off a topic without writing a
# gz-transport subscriber, but the camera sensor will write PNGs itself. Patch
# it in on demand rather than shipping it enabled -- left on, it fills the disk
# on every run.
restore_sdf() { [ -f "$CAM_SDF.nidar-orig" ] && mv "$CAM_SDF.nidar-orig" "$CAM_SDF"; }
trap 'restore_sdf; pkill -f "gz sim" 2>/dev/null; pkill -f "bin/arducopter" 2>/dev/null' EXIT

if [ "$CAPTURE" = 1 ] && ! grep -q '<save' "$CAM_SDF"; then
  cp "$CAM_SDF" "$CAM_SDF.nidar-orig"
  python3 - "$CAM_SDF" "$CAPTURE_DIR" <<'PY'
import re, sys
p, out = sys.argv[1], sys.argv[2]
s = open(p, encoding="utf-8").read()
m = re.search(r'(<sensor name="camera"[^>]*>.*?<camera[^>]*>)', s, re.S)
if not m:
    sys.exit("camera element not found")
s = s[:m.end()] + f'\n<save enabled="true"><path>{out}</path></save>' + s[m.end():]
open(p, "w", encoding="utf-8").write(s)
PY
  rm -rf "$CAPTURE_DIR"; mkdir -p "$CAPTURE_DIR"
  echo "frame capture -> $CAPTURE_DIR"
fi

rm -rf $OUT; mkdir -p $OUT
pkill -f 'gz sim' 2>/dev/null || true
pkill -f 'bin/arducopter' 2>/dev/null || true
sleep 2

echo "=== gazebo ==="
gz sim -s -r -v2 iris_runway.sdf > $OUT/gz.log 2>&1 &
sleep 12
pgrep -f 'gz sim' >/dev/null || { echo "gazebo died"; tail -20 $OUT/gz.log; exit 1; }

# Point the gimbal STRAIGHT DOWN. The model ships looking at the horizon, which
# is useless for finding someone in water: NIDAR searches nadir at 40 m.
gz topic -t /gimbal/cmd_pitch -m gz.msgs.Double -p 'data: -1.57' 2>/dev/null \
  && echo "gimbal commanded nadir" || echo "gimbal command failed (check topic name)"

echo "=== SITL ==="
# gazebo-iris.parm, NOT copter.parm. The generic defaults leave the JSON
# physics link half-configured and SITL logs "No JSON sensor message received,
# resending servos" forever while the EKF never converges.
cd $OUT
"$BIN" -M JSON --home -35.363262,149.165237,584,353 --sysid 1 \
    --serial0 "udpclient:127.0.0.1:14570" \
    --defaults "$AP/Tools/autotest/default_params/gazebo-iris.parm" \
    > $OUT/sitl.log 2>&1 &
sleep 15
grep -q 'No JSON sensor' $OUT/sitl.log \
  && { echo "PHYSICS LINK DEAD"; tail -10 $OUT/sitl.log; exit 1; }
echo "physics link up"

python3 - <<'PY'
import threading, time
from pymavlink import mavutil
m = mavutil.mavlink_connection("udpin:0.0.0.0:14570", source_system=250)
if not m.wait_heartbeat(timeout=60):
    raise SystemExit("no heartbeat")

# Ask for telemetry: a passive listener gets heartbeats and nothing else, and
# then every reading sits at its initialised zero and looks like a dead vehicle.
for mid, hz in ((33, 5), (24, 2), (74, 5), (1, 1), (30, 5)):
    m.mav.command_long_send(m.target_system, m.target_component,
                            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
                            mid, int(1e6/hz), 0, 0, 0, 0, 0)
m.mav.param_set_send(m.target_system, m.target_component, b"DISARM_DELAY",
                     0.0, mavutil.mavlink.MAV_PARAM_TYPE_REAL32)

# No receiver exists headless and FS_THR_ENABLE is on, so give it a stick.
stop = threading.Event()
def rc():
    while not stop.is_set():
        m.mav.rc_channels_override_send(m.target_system, m.target_component,
                                        1500, 1500, 1500, 1500, 1500, 1500, 1500, 1500)
        stop.wait(0.1)
threading.Thread(target=rc, daemon=True).start()

m.set_mode_apm("GUIDED"); time.sleep(2)
for i in range(60):
    m.mav.command_long_send(m.target_system, m.target_component,
                            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0,
                            1, 0, 0, 0, 0, 0, 0)
    a = m.recv_match(type="COMMAND_ACK", blocking=True, timeout=3)
    if a and a.command == 400 and a.result == 0:
        print(f"ARMED (attempt {i+1})"); break
    time.sleep(2)
else:
    raise SystemExit("never armed -- check EKF/position estimate in sitl.log")

m.mav.command_long_send(m.target_system, m.target_component,
                        mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0, 0, 0, 0, 0, 0, 0, 40)
# Lockstep means Gazebo advances only when SITL sends servos, so this runs
# roughly 3x slower than wall clock. That is EXPECTED and harmless -- simulated
# time stays consistent. Budget the wall-clock wait accordingly.
best, t0 = 0.0, time.time()
while time.time() - t0 < 420:
    g = m.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=3)
    if g:
        best = max(best, g.relative_alt / 1000.0)
        if best > 38:
            break
print(f"max altitude in Gazebo: {best:.1f} m")
stop.set()
PY

if [ "$CAPTURE" = 1 ]; then
  echo
  echo "=== frames captured ==="
  N=$(ls "$CAPTURE_DIR"/*.png 2>/dev/null | wc -l)
  echo "  $N PNGs in $CAPTURE_DIR"
  [ "$N" -gt 0 ] && cp "$(ls "$CAPTURE_DIR"/*.png | tail -1)" /tmp/drone-camera.png \
    && echo "  latest -> /tmp/drone-camera.png"
fi
echo GZ_FLIGHT_DONE
