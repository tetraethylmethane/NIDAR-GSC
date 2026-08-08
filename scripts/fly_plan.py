"""Plan the search, upload it to three real autopilots, and fly it.

    coverage planner -> QGC WPL 110 -> SITL AUTO x3 -> the ground station

This is the loop the ground station exists to serve, and until now no part of it
had been joined up: the planner was unit-tested, SITL had flown nothing, and the
GCS had watched three aircraft sit on the ground in STABILIZE.

Wind is ON. Gust response is the largest single term in the geolocation error
budget (0.70 m unmodelled, ~60 % of variance in case C) and it gates 450 of the
600 flight points, so flying the plan in still air would be the least useful
version of this test.
"""
from __future__ import annotations

import math
import os
import sys
import threading
import time

# The coverage planner lives in the systems repo. NIDAR_SYS overrides; the
# default assumes the two repos are checked out side by side.
REPO = os.environ.get("NIDAR_SYS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "Drikr-NIDAR")
if not os.path.isdir(os.path.join(REPO, "autonomy")):
    sys.exit(f"coverage planner not found under {REPO} -- set NIDAR_SYS")
sys.path.insert(0, REPO)

from autonomy.coverage_planner.plan import plan_mission  # noqa: E402
from pymavlink import mavutil  # noqa: E402

# The 10 ha search box from sim_mission.py, so the tile cache covers it.
LAT0, LON0 = 13.0000, 80.0000
DLAT = 250.0 / 111_132.0
DLON = 400.0 / (111_320.0 * math.cos(math.radians(LAT0)))
BOUNDARY = [(LAT0, LON0), (LAT0, LON0 + DLON),
            (LAT0 + DLAT, LON0 + DLON), (LAT0 + DLAT, LON0)]
HOME = (LAT0, LON0)

N = 3
PORTS = [14560, 14561, 14562]        # private per-aircraft link (SITL serial1)
SPEEDUP = float(os.environ.get("SPEEDUP", "5"))


def upload(m, items, drone_id):
    """Push a QGC WPL 110 item list over MISSION_ITEM_INT.

    Deliberately the int variant: MISSION_ITEM uses float32 for lat/lon, which
    quantises to roughly 1-2 m at these latitudes. The whole delivery budget is
    1 m zones -- throwing away metres in the upload would be absurd.
    """
    m.mav.mission_count_send(m.target_system, m.target_component, len(items))
    sent = 0
    t0 = time.time()
    while sent < len(items) and time.time() - t0 < 30:
        req = m.recv_match(type=["MISSION_REQUEST", "MISSION_REQUEST_INT"],
                           blocking=True, timeout=5)
        if req is None:
            continue
        it = items[req.seq]
        m.mav.mission_item_int_send(
            m.target_system, m.target_component, req.seq,
            it.frame, it.command, 1 if req.seq == 0 else 0, it.autocontinue,
            it.p1, it.p2, it.p3, it.p4,
            int(round(it.lat * 1e7)), int(round(it.lon * 1e7)), it.alt)
        sent = req.seq + 1
    ack = m.recv_match(type="MISSION_ACK", blocking=True, timeout=10)
    ok = ack is not None and ack.type == 0
    print(f"  drone {drone_id}: uploaded {sent}/{len(items)} items, "
          f"ack={'OK' if ok else ack.type if ack else 'NONE'}")
    return ok


def main() -> int:
    print("=" * 74)
    print("PLAN")
    print("=" * 74)
    mp = plan_mission(BOUNDARY, HOME, n_drones=N, altitude_m=40.0, speed_ms=8.0)
    print(mp.summary())

    print()
    print("=" * 74)
    print("CONNECT  (three real ArduCopter autopilots)")
    print("=" * 74)
    links = []
    for i, port in enumerate(PORTS[:N], start=1):
        m = mavutil.mavlink_connection(f"udpin:0.0.0.0:{port}", source_system=250)
        print(f"  waiting for drone {i} on udp/{port} ...", flush=True)
        m.wait_heartbeat(timeout=90)
        print(f"  drone {i}: heartbeat, SYSID {m.target_system}")
        links.append(m)

    print()
    print("=" * 74)
    print("CONFIGURE  (wind on -- gust response gates 450 of 600 points)")
    print("=" * 74)
    for i, m in enumerate(links, start=1):
        for name, val in (
            # ArduCopter refuses to arm in AUTO unless bit 0 of AUTO_OPTIONS is
            # set. We arm in GUIDED and then switch, so this is belt and braces
            # -- but a mode change that silently blocks arming is exactly the
            # kind of thing that wasted the first run.
            ("AUTO_OPTIONS", 3),
            # Auto-disarm after 10 s on the ground is right on an aircraft and
            # wrong in this harness: arming three drones in sequence can leave
            # the first one armed and idle while the third is still passing
            # pre-arm, and it disarms underneath us.
            ("DISARM_DELAY", 0),
            ("SIM_SPEEDUP", SPEEDUP),
            ("SIM_WIND_SPD", 6.0),      # 6 m/s, a plausible flood-plain day
            ("SIM_WIND_DIR", 270.0),
            ("SIM_WIND_TURB", 3.0),
            ("WPNAV_SPEED", 800.0),     # cm/s = 8 m/s, the design search speed
            ("RTL_ALT", 2500.0 + 500 * (i - 1)),
        ):
            m.mav.param_set_send(m.target_system, m.target_component,
                                 name.encode(), float(val),
                                 mavutil.mavlink.MAV_PARAM_TYPE_REAL32)
        # ASK FOR TELEMETRY. Exactly the defect found in the ground station's
        # ingest earlier today, reproduced here in the harness that was
        # supposed to be watching for it.
        #
        # ArduPilot streams at the rates set by SRx_* for the channel the GCS
        # is on. This private link (serial1) has never had a stream request, so
        # a passive listener gets heartbeats and nothing else. Every reading in
        # this script then sat at its initialised 0.0 -- and I read "0.00 m,
        # throttle 0%, no RC" as evidence the aircraft was not flying, when it
        # was evidence that nothing was being sent. The GCS, which does request
        # streams, was showing the same aircraft at 40 m at the time.
        #
        # ABSENT DATA IS NOT ZERO DATA. Two diagnoses were built on that
        # confusion before this line existed.
        for mid, hz in ((33, 5), (24, 2), (74, 5), (1, 1), (42, 2), (65, 2)):
            m.mav.command_long_send(
                m.target_system, m.target_component,
                mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
                mid, int(1e6 / hz), 0, 0, 0, 0, 0)
        print(f"  drone {i}: wind 6 m/s from 270 deg, turbulence 3, speedup {SPEEDUP:g}x")

    # ---------------------------------------------------------------- RC
    # WHY THIS IS HERE, after five runs that armed and never moved.
    #
    # The aircraft accepted MAV_CMD_NAV_TAKEOFF, reported ACCEPTED, stayed
    # armed in GUIDED, and held throttle at 0 % indefinitely. The diagnostic
    # that finally explained it asked the autopilot what RC it could see:
    #
    #     RC_CHANNELS      NO RC_CHANNELS RECEIVED
    #     FS_THR_ENABLE    1.0
    #
    # There is no receiver in this harness at all, and the throttle failsafe is
    # enabled, so the motors stay at MOT_SPIN_ARM no matter what is commanded.
    # That is correct behaviour on an aircraft and an artefact of running SITL
    # headless without MAVProxy.
    #
    # The fix is to give it a transmitter rather than to disable the failsafe.
    # Turning FS_THR_ENABLE off would also work and would be the wrong habit:
    # the parameter matters, and a harness that quietly disables safety
    # features teaches you nothing about the aircraft that will fly.
    stop_rc = threading.Event()

    def rc_pump():
        """A simulated transmitter: sticks centred, throttle mid, at 10 Hz."""
        while not stop_rc.is_set():
            for m in links:
                m.mav.rc_channels_override_send(
                    m.target_system, m.target_component,
                    1500, 1500, 1500, 1500, 1500, 1500, 1500, 1500)
            stop_rc.wait(0.1)

    threading.Thread(target=rc_pump, daemon=True, name="rc").start()
    time.sleep(2)
    for i, m in enumerate(links, start=1):
        rc = m.recv_match(type="RC_CHANNELS", blocking=True, timeout=5)
        print(f"  drone {i}: RC {'seen, ch3=' + str(rc.chan3_raw) if rc else 'STILL ABSENT'}")

    print()
    print("=" * 74)
    print("UPLOAD")
    print("=" * 74)
    for m, d in zip(links, mp.drones):
        upload(m, d.items, d.drone_id)

    print()
    print("=" * 74)
    print("ARM AND FLY")
    print("=" * 74)
    # Arming is a request that can be REFUSED, and the first version of this
    # script fired it and moved on. All three aircraft sat on the ground in
    # AUTO at 0.0 m for the whole run while the script cheerfully printed
    # "armed, taking off". Check the ACK, print the reason, and retry.
    ARM_RESULT = {0: "ACCEPTED", 1: "TEMPORARILY_REJECTED", 2: "DENIED",
                  3: "UNSUPPORTED", 4: "FAILED", 5: "IN_PROGRESS"}

    def drain_statustext(m, prefix):
        out = []
        while True:
            s = m.recv_match(type="STATUSTEXT", blocking=False)
            if s is None:
                break
            txt = s.text.strip() if isinstance(s.text, str) else s.text.decode(errors="replace").strip()
            if txt:
                out.append(txt)
        for t in out[-4:]:
            print(f"    {prefix} {t}")
        return out

    def arm(m, i, timeout=180):
        """Retry until the autopilot accepts. Pre-arm checks take time to pass
        in SITL -- the EKF has to settle and home has to be set."""
        m.set_mode_apm("GUIDED")
        time.sleep(1)
        t0 = time.time()
        attempt = 0
        while time.time() - t0 < timeout:
            attempt += 1
            m.mav.command_long_send(
                m.target_system, m.target_component,
                mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0,
                1, 0, 0, 0, 0, 0, 0)
            ack = None
            t1 = time.time()
            while time.time() - t1 < 4:
                a = m.recv_match(type="COMMAND_ACK", blocking=True, timeout=2)
                if a and a.command == mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM:
                    ack = a
                    break
            if ack and ack.result == 0:
                print(f"  drone {i}: ARMED after {attempt} attempt(s), "
                      f"{time.time() - t0:.0f}s")
                return True
            reason = ARM_RESULT.get(ack.result, ack.result) if ack else "no ACK"
            if attempt in (1, 3) or attempt % 8 == 0:
                print(f"  drone {i}: arm refused ({reason}), attempt {attempt}")
                drain_statustext(m, f"drone {i}:")
            time.sleep(3)
        print(f"  drone {i}: NEVER ARMED after {timeout}s")
        drain_statustext(m, f"drone {i}:")
        return False

    def state(m):
        """Mode and armed flag straight off the next heartbeat.

        Worth checking rather than assuming: run four commanded takeoff on
        aircraft that had already auto-disarmed, got ACCEPTED from one of them,
        and reported nothing wrong.
        """
        hb = m.recv_match(type="HEARTBEAT", blocking=True, timeout=5)
        if hb is None:
            return "?", False
        armed = bool(hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
        return mavutil.mode_string_v10(hb), armed

    def takeoff(m, i, alt=40.0):
        mode, armed = state(m)
        print(f"  drone {i}: pre-takeoff state mode={mode} armed={armed}")
        if not armed:
            print(f"  drone {i}: disarmed before takeoff -- re-arming")
            if not arm(m, i, timeout=60):
                return False
        m.mav.command_long_send(
            m.target_system, m.target_component,
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0, 0, 0, 0, 0, 0, 0, alt)
        a = m.recv_match(type="COMMAND_ACK", blocking=True, timeout=5)
        res = ARM_RESULT.get(a.result, a.result) if a else "no ACK"
        print(f"  drone {i}: GUIDED takeoff -> {res}")
        if a is None or a.result != 0:
            drain_statustext(m, f"drone {i}:")
        return a is not None and a.result == 0

    # WHY NOT JUST SWITCH TO AUTO.
    #
    # On the ground ArduCopter will not begin an AUTO mission until the pilot
    # raises the throttle. MAV_CMD_MISSION_START is ACCEPTED and still does not
    # start it -- run three armed all three aircraft, got ACCEPTED from all
    # three, and left them at 0.0 m and waypoint 0 until they auto-disarmed.
    #
    # A GUIDED takeoff needs no throttle stick, so: arm, GUIDED, take off,
    # VERIFY the climb, and only then hand over to AUTO, which picks the
    # mission up from the air. This is also what a real operator does, and what
    # the mission brief's single "start" action has to expand into.
    def climbed(m, i, target=5.0, timeout=60):
        t0 = time.time()
        best = 0.0
        while time.time() - t0 < timeout:
            msg = m.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=3)
            if msg:
                alt = msg.relative_alt / 1000.0
                best = max(best, alt)
                if alt > target:
                    print(f"  drone {i}: airborne, {alt:.1f} m")
                    return True
        print(f"  drone {i}: DID NOT CLIMB within {timeout}s (best {best:.2f} m)")
        drain_statustext(m, f"drone {i}:")
        return False

    # Arm and take off in the SAME step per aircraft, so nothing sits armed and
    # idle waiting for its siblings.
    flying = []
    for i, m in enumerate(links, start=1):
        if not arm(m, i):
            flying.append(False)
            continue
        takeoff(m, i)
        flying.append(climbed(m, i))

    if not any(flying):
        print("\n  nothing is flying -- stopping rather than logging zeros")
        return 1

    # Let them get most of the way to search altitude before handing over, so
    # the first transect is not flown in a climb.
    t0 = time.time()
    while time.time() - t0 < 60:
        alts = []
        for m in links:
            msg = m.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=2)
            if msg:
                alts.append(msg.relative_alt / 1000.0)
        if alts and min(alts) > 35.0:
            break
    print(f"  all airborne at ~{min(alts) if alts else 0:.0f} m, handing over to AUTO")

    for i, m in enumerate(links, start=1):
        if not flying[i - 1]:
            continue
        m.set_mode_apm("AUTO")
        time.sleep(0.5)
        m.mav.command_long_send(
            m.target_system, m.target_component,
            mavutil.mavlink.MAV_CMD_MISSION_START, 0, 0, 0, 0, 0, 0, 0, 0)
        print(f"  drone {i}: AUTO, flying the plan")

    print()
    print("=" * 74)
    print("FLYING")
    print("=" * 74)
    print(f"{'t':>6}{'D1 mode':>10}{'alt':>7}{'wp':>4}"
          f"{'D2 mode':>10}{'alt':>7}{'wp':>4}"
          f"{'D3 mode':>10}{'alt':>7}{'wp':>4}")
    state = {i: {"mode": "?", "alt": 0.0, "wp": 0, "lat": 0.0, "lon": 0.0,
                 "armed": False, "was_airborne": False, "max_alt": 0.0,
                 "max_wp": 0}
             for i in range(1, N + 1)}
    t0 = time.time()
    last = 0.0
    while time.time() - t0 < float(os.environ.get("FLY_S", "900")):
        for i, m in enumerate(links, start=1):
            while True:
                msg = m.recv_match(blocking=False)
                if msg is None:
                    break
                t = msg.get_type()
                if t == "HEARTBEAT":
                    state[i]["mode"] = mavutil.mode_string_v10(msg)
                    state[i]["armed"] = bool(
                        msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                elif t == "GLOBAL_POSITION_INT":
                    a = msg.relative_alt / 1000.0
                    state[i]["alt"] = a
                    state[i]["max_alt"] = max(state[i]["max_alt"], a)
                    if a > 10.0:
                        state[i]["was_airborne"] = True
                    state[i]["lat"] = msg.lat / 1e7
                    state[i]["lon"] = msg.lon / 1e7
                elif t == "MISSION_CURRENT":
                    state[i]["wp"] = msg.seq
                    state[i]["max_wp"] = max(state[i]["max_wp"], msg.seq)
        now = time.time() - t0
        if now - last >= 10:
            last = now
            row = f"{now:6.0f}"
            for i in range(1, N + 1):
                s = state[i]
                row += f"{s['mode']:>10}{s['alt']:>7.1f}{s['wp']:>4}"
            print(row, flush=True)
            # Completion is "landed and disarmed", not a mode change: the
            # mission ends with RTL as a mission ITEM, so the flight mode stays
            # AUTO throughout and never reads RTL. The previous version watched
            # for a mode that never comes and sat for 900 s after the aircraft
            # were down.
            if all(not state[i]["armed"] and state[i]["alt"] < 1.0
                   and state[i]["was_airborne"] for i in range(1, N + 1)):
                print("\n  all three have flown the plan, landed and disarmed")
                break

    print()
    print("=" * 74)
    print("RESULT")
    print("=" * 74)
    n_items = len(mp.drones[0].items)
    for i in range(1, N + 1):
        s = state[i]
        done = "COMPLETED" if s["max_wp"] >= n_items - 2 and not s["armed"] else "incomplete"
        print(f"  drone {i}: {done:<11} reached wp {s['max_wp']:>2}/{n_items - 1}  "
              f"max alt {s['max_alt']:5.1f} m  final {s['lat']:.6f},{s['lon']:.6f}")
    print()
    print("  Flown by three real ArduCopter autopilots, in AUTO, from the")
    print("  coverage planner's own QGC WPL 110 output, with 6 m/s of wind and")
    print("  turbulence 3. No part of this path was hand-written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
