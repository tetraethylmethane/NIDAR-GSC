#!/usr/bin/env python3
"""Does the battery failsafe actually bring the aircraft home?

Reported from a simulation run: the drones did not return to the pad when the
battery got low. firmware/ardupilot-params/ has carried BATT_FS_LOW_ACT = 2
(RTL) for weeks, reviewed and unit-tested -- and no simulation ever loaded that
file. Every SITL script launched with stock copter.parm, where BATT_FS_LOW_ACT
is 0: no action on low battery, ever.

So this does not test the parameter file. It tests that the parameters reach a
running aircraft and that the aircraft then does the thing they ask for.

Called by scripts/test-battery-failsafe.sh, which starts the SITL.
"""
from __future__ import annotations

import sys
import time

from pymavlink import mavutil

MODES = {0: "STABILIZE", 2: "ALT_HOLD", 3: "AUTO", 4: "GUIDED",
         5: "LOITER", 6: "RTL", 9: "LAND", 16: "POSHOLD"}
WANT = ("BATT_LOW_MAH", "BATT_CAPACITY", "BATT_FS_LOW_ACT",
        "BATT_FS_VOLTSRC", "RTL_LOIT_TIME", "RTL_ALT")
SPEEDUP = 20
TIMEOUT_S = 900


def main() -> int:
    m = mavutil.mavlink_connection("tcp:127.0.0.1:5760")
    if not m.wait_heartbeat(timeout=90):
        print("no heartbeat from SITL")
        return 2
    print(f"connected, SYSID {m.target_system}")

    for mid, hz in ((0, 2), (147, 2), (33, 2)):
        m.mav.command_long_send(m.target_system, m.target_component,
                                mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
                                0, mid, int(1e6 / hz), 0, 0, 0, 0, 0)

    def setp(name, val):
        m.mav.param_set_send(m.target_system, m.target_component,
                             name.encode(), float(val),
                             mavutil.mavlink.MAV_PARAM_TYPE_REAL32)
        time.sleep(0.3)

    setp("SIM_SPEEDUP", SPEEDUP)

    # Read back what the aircraft actually holds. If these are stock values the
    # test is meaningless and should say so rather than pass.
    for k in WANT:
        m.mav.param_request_read_send(m.target_system, m.target_component,
                                      k.encode(), -1)
    got, t0 = {}, time.time()
    while time.time() - t0 < 15 and len(got) < len(WANT):
        msg = m.recv_match(type="PARAM_VALUE", blocking=True, timeout=2)
        if msg and msg.param_id in WANT:
            got[msg.param_id] = msg.param_value

    print("\nparameters ON THE AIRCRAFT:")
    for k in WANT:
        print(f"  {k:18} = {got.get(k)}")

    if got.get("BATT_FS_LOW_ACT") != 2:
        print("\nBATT_FS_LOW_ACT is not 2 (RTL) -- the project parameter file "
              "did not reach the aircraft. This is the original defect, not a "
              "new one: check the --defaults list in the launch script.")
        return 1
    low_mah = got.get("BATT_LOW_MAH", 0)
    if not low_mah:
        print("\nBATT_LOW_MAH is 0 -- capacity failsafe disabled.")
        return 1

    print("\nwaiting for EKF and pre-arm...")
    time.sleep(30)

    m.set_mode("GUIDED")
    time.sleep(2)

    # RETRY, do not give up after one attempt. Several pre-arm checks in the
    # real parameter set clear on their own once the EKF has a position
    # estimate -- "PreArm: Fence enabled, need position estimate" is the usual
    # one, because FENCE_ENABLE=1 needs a fix before it can define a boundary.
    # A single attempt at a fixed delay read that transient state as a
    # permanent failure and reported a config problem that was not there.
    armed, reasons = False, []
    deadline = time.time() + 90
    while time.time() < deadline and not armed:
        m.mav.command_long_send(m.target_system, m.target_component,
                                mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                                0, 1, 0, 0, 0, 0, 0, 0)
        end = time.time() + 8
        while time.time() < end:
            msg = m.recv_match(type=["HEARTBEAT", "STATUSTEXT"],
                               blocking=True, timeout=2)
            if msg is None:
                continue
            if msg.get_type() == "STATUSTEXT":
                if "rearm" in msg.text.lower() or "arm:" in msg.text.lower():
                    if msg.text not in reasons:
                        reasons.append(msg.text)
            elif msg.base_mode & 128:
                armed = True
                break
    print(f"armed: {armed}")
    if not armed:
        print("could not arm after 90 s. Pre-arm checks are part of the real "
              "config, so this is a finding, not a harness problem:")
        for r in reasons[-6:]:
            print(f"    {r}")
        return 1

    m.mav.command_long_send(m.target_system, m.target_component,
                            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                            0, 0, 0, 0, 0, 0, 0, 40)
    print(f"climbing to 40 m; draining the pack at {SPEEDUP}x\n")

    last, mah, alt = None, 0.0, 0.0
    t0 = time.time()
    while time.time() - t0 < TIMEOUT_S:
        msg = m.recv_match(type=["HEARTBEAT", "BATTERY_STATUS",
                                 "GLOBAL_POSITION_INT"],
                           blocking=True, timeout=5)
        if msg is None:
            continue
        kind = msg.get_type()
        if kind == "BATTERY_STATUS":
            mah = msg.current_consumed
        elif kind == "GLOBAL_POSITION_INT":
            alt = msg.relative_alt / 1000.0
        else:
            mode = MODES.get(msg.custom_mode, msg.custom_mode)
            if mode != last:
                print(f"  t+{time.time() - t0:5.0f}s  mode -> {mode:<9} "
                      f"{mah:6.0f} mAh consumed, {alt:5.1f} m")
                last = mode
                if mode == "RTL":
                    pct = 100.0 * mah / got["BATT_CAPACITY"]
                    print(f"\nBATTERY FAILSAFE FIRED -> RTL")
                    print(f"  consumed {mah:.0f} mAh of "
                          f"{got['BATT_CAPACITY']:.0f} ({pct:.0f} %)")
                    print(f"  threshold BATT_LOW_MAH = {low_mah:.0f} mAh")
                    print(f"  the aircraft is returning to the pad, which is "
                          f"the behaviour that was missing.")
                    return 0

    print(f"\nNO FAILSAFE within {TIMEOUT_S} s. Consumed {mah:.0f} mAh against "
          f"a {low_mah:.0f} mAh threshold -- if consumption is still far below "
          f"the threshold the drain is too slow, not the failsafe broken.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
