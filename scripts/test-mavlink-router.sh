#!/usr/bin/env bash
# Prove scripts/mavlink-router.conf routes, using the committed file itself.
#
# This exists because the config shipped for weeks with Mode = Normal on the
# aircraft endpoints, which routes NOTHING when the aircraft initiates -- and
# it started cleanly the whole time, so nothing complained. A config nobody has
# run is a guess.
#
#   ./scripts/test-mavlink-router.sh
#
# Needs: mavlink-routerd on PATH, ArduPilot SITL built, pymavlink.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="$HERE/mavlink-router.conf"
MR="$(command -v mavlink-routerd || echo "$HOME/.local/bin/mavlink-routerd")"
AP="${ARDUPILOT:-$HOME/ardupilot}"
BIN="$AP/build/sitl/bin/arducopter"
RUN=/tmp/mavlink-router-test

[ -x "$MR" ]  || { echo "mavlink-routerd not found"; exit 2; }
[ -x "$BIN" ] || { echo "SITL not built: $BIN"; exit 2; }

rm -rf "$RUN"; mkdir -p "$RUN/logs"
pkill -f mavlink-routerd 2>/dev/null || true
pkill -f 'bin/arducopter' 2>/dev/null || true
sleep 1
cd "$RUN"

echo "=== starting mavlink-router on the committed config ==="
"$MR" -c "$CONF" > "$RUN/router.log" 2>&1 &
sleep 2
pgrep -f mavlink-routerd >/dev/null || {
  echo "router did not start"; cat "$RUN/router.log"; exit 1; }
grep -iE 'error|unknown|invalid' "$RUN/router.log" && { echo "CONFIG ERRORS"; exit 1; }
grep -E 'Opened' "$RUN/router.log" | sed 's/^/  /'

echo
echo "=== three aircraft, each to its own endpoint port ==="
for i in 1 2 3; do
  d="$RUN/sitl$i"; mkdir -p "$d"
  lon=$(python3 -c "print(80.0 + ($i-1)*0.001)")
  ( cd "$d"; "$BIN" --model quad --instance $((i-1)) --sysid "$i" \
      --home "12.999,$lon,10,0" \
      --serial0 "udpclient:127.0.0.1:1454$i" \
      --defaults "$AP/Tools/autotest/default_params/gazebo-iris.parm" \
      > "$d/sitl.log" 2>&1 ) &
done
sleep 15

python3 - <<'PY'
import collections, sys, time
from pymavlink import mavutil

m = mavutil.mavlink_connection("udpin:0.0.0.0:14550", source_system=250)
seen = collections.Counter()
t0 = time.time()
while time.time() - t0 < 20:
    msg = m.recv_match(blocking=True, timeout=2)
    if msg and msg.get_type() != "BAD_DATA":
        seen[msg.get_srcSystem()] += 1

print("\nSYSIDs on the single GCS port 14550 (rule 8.13):")
for sysid, n in sorted(seen.items()):
    print(f"   SYSID {sysid}: {n:>4} messages")
missing = {1, 2, 3} - set(seen)
if missing:
    print(f"\nFAIL -- missing {sorted(missing)}")
    sys.exit(1)
print("\nOK -- all three aircraft routed onto one port")
PY
rc=$?

pkill -f 'bin/arducopter' 2>/dev/null || true
pkill -f mavlink-routerd 2>/dev/null || true
exit $rc
