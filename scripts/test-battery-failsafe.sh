#!/usr/bin/env bash
# Prove the battery failsafe brings the aircraft home, using the committed
# parameter file itself.
#
# A simulation run showed the drones never returning to the pad on low battery.
# The parameters were right the whole time -- BATT_FS_LOW_ACT = 2 has been in
# firmware/ardupilot-params/ for weeks, validated and unit-tested. Nothing ever
# loaded them into a simulator. Every SITL script here launched with stock
# copter.parm, where BATT_FS_LOW_ACT is 0.
#
# Third instance of the same pattern in this repo, after mediamtx.yml and
# mavlink-router.conf: a config that reviews clean and is not in the path.
#
#   ./scripts/test-battery-failsafe.sh
#
# Needs: ArduPilot SITL built, pymavlink, and the systems repo for the params.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_GSC="$(dirname "$HERE")"
REPO_SYS="${NIDAR_SYS:-$(dirname "$REPO_GSC")/Drikr-NIDAR}"
AP="${ARDUPILOT:-$HOME/ardupilot}"
BIN="$AP/build/sitl/bin/arducopter"
PARM="$REPO_SYS/firmware/ardupilot-params/rescueswarm-drone1.parm"
RUN=/tmp/battery-failsafe-test

[ -x "$BIN" ]  || { echo "SITL not built: $BIN"; exit 2; }
[ -f "$PARM" ] || { echo "params not found: $PARM  (set NIDAR_SYS)"; exit 2; }

rm -rf "$RUN"; mkdir -p "$RUN"
pkill -f 'bin/arducopter' 2>/dev/null || true
sleep 1
cd "$RUN"

echo "=== SITL with copter.parm + $(basename "$PARM") ==="
# --defaults takes a comma-separated list applied left to right, so the project
# file overrides the stock one. Verified by reading the parameters back below
# rather than assumed: an earlier version of this fix assumed it.
"$BIN" --model quad --sysid 1 --home 12.999,80.0,10,0 \
    --defaults "$AP/Tools/autotest/default_params/copter.parm,$PARM,$HERE/sitl-sim.parm" \
    > "$RUN/sitl.log" 2>&1 &
sleep 8

python3 "$HERE/battery_failsafe_check.py"
rc=$?

pkill -f 'bin/arducopter' 2>/dev/null || true
[ $rc -eq 0 ] && echo "PASS" || echo "FAIL (see $RUN/sitl.log)"
exit $rc
