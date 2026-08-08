#!/usr/bin/env python3
"""Fly a synthetic three-drone mission at the ground station.

Drives the GCS end-to-end with no aircraft, no SITL and no radios: emits both
MAVLink telemetry and the 5 Hz mission-state documents, so every rule 8.14
display can be exercised and demonstrated.

    python scripts/sim_mission.py                 # localhost, real time
    python scripts/sim_mission.py --speed 8       # 8x, for a quick check
    python scripts/sim_mission.py --host 10.0.0.5 # a GCS on the mesh

What it produces, in order:

    SETUP -> CLIMB -> SEARCH (three drones sweeping three regions,
    finding survivors one at a time) -> DELIVER (kits assigned, en route,
    released) -> RTH -> LANDED

Deliberately includes the awkward cases the operator must be able to see:

  * drone 2 loses its link for ~8 s mid-search, so the health indicator and the
    stale-telemetry warning are exercised
  * survivor 3 is first tagged in RTK_FLOAT and later re-tagged RTK_FIXED by a
    different drone, so the dedup rule (best fix wins, not newest) is visible
  * survivor 6 is tagged with a 3D fix only, which should raise the "tagged
    without RTK" warning -- that is a ~100-point problem and must be obvious
    while there is still time to re-acquire

This is the P2 gate: prove the GCS works before the first real flight, not at it.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import socket
import time

# 10 ha near Chennai, matching the boundary used in the KML tests.
LAT0, LON0 = 13.0000, 80.0000
DLAT, DLON = 250.0 / 111_132.0, 400.0 / (111_320.0 * math.cos(math.radians(LAT0)))

PHASES = ["SETUP", "CLIMB", "SEARCH", "DELIVER", "RTH", "LANDED"]


def region(i: int) -> list[list[float]]:
    """Drone i's third of the area — a DARP-style equal-area strip."""
    a, b = i / 3.0, (i + 1) / 3.0
    return [
        [LAT0, LON0 + a * DLON], [LAT0, LON0 + b * DLON],
        [LAT0 + DLAT, LON0 + b * DLON], [LAT0 + DLAT, LON0 + a * DLON],
    ]


def boustrophedon(i: int, u: float) -> tuple[float, float]:
    """Position along a 4-leg lawnmower sweep of drone i's strip, u in [0,1]."""
    legs = 4
    leg = min(int(u * legs), legs - 1)
    v = u * legs - leg
    x0 = (i + (leg + 0.5) / legs) / 3.0
    lon = LON0 + x0 * DLON
    lat = LAT0 + (v if leg % 2 == 0 else 1.0 - v) * DLAT
    return lat, lon


SURVIVORS = [
    # id, lat frac, lon frac, found at t/T, fix, found by
    (1, 0.20, 0.10, 0.30, "RTK_FIXED", 1),
    (2, 0.70, 0.22, 0.38, "RTK_FIXED", 1),
    (3, 0.45, 0.45, 0.42, "RTK_FLOAT", 2),   # re-tagged better below
    (4, 0.80, 0.55, 0.50, "RTK_FIXED", 2),
    (5, 0.30, 0.78, 0.55, "RTK_FIXED", 3),
    (6, 0.60, 0.88, 0.62, "3D", 3),          # no RTK -> must warn
]
RETAG = (3, "RTK_FIXED", 3, 0.58)            # survivor 3, better fix, drone 3


def send_udp(sock, host, port, doc) -> None:
    sock.sendto(json.dumps(doc).encode(), (host, port))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--mission-port", type=int, default=14660)
    ap.add_argument("--mavlink-port", type=int, default=14550)
    ap.add_argument("--duration", type=float, default=462.0,
                    help="design mission is 7.7 min = 462 s")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--no-mavlink", action="store_true")
    args = ap.parse_args()

    mav = None
    if not args.no_mavlink:
        try:
            from pymavlink import mavutil

            mav = mavutil.mavlink_connection(
                f"udpout:{args.host}:{args.mavlink_port}", source_system=1)
            print(f"MAVLink  -> udpout:{args.host}:{args.mavlink_port}")
        except Exception as exc:                       # pragma: no cover
            print(f"MAVLink disabled ({exc}); mission state only")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"mission  -> udp:{args.host}:{args.mission_port}")
    print(f"duration {args.duration:.0f} s at {args.speed}x\n")

    t0 = time.time()
    found: dict[int, dict] = {}
    deliveries: dict[int, str] = {}
    dt = 0.2                                   # 5 Hz

    while True:
        elapsed = (time.time() - t0) * args.speed
        frac = elapsed / args.duration
        if frac >= 1.0:
            break

        if frac < 0.06:
            phase, u = "SETUP", 0.0
        elif frac < 0.12:
            phase, u = "CLIMB", 0.0
        elif frac < 0.68:
            phase, u = "SEARCH", (frac - 0.12) / 0.56
        elif frac < 0.90:
            phase, u = "DELIVER", 1.0
        elif frac < 0.97:
            phase, u = "RTH", 1.0
        else:
            phase, u = "LANDED", 1.0

        # survivors appear as the sweep passes them
        for sid, fl, fo, at, fix, by in SURVIVORS:
            if frac >= at and sid not in found:
                found[sid] = {
                    "id": sid, "lat": LAT0 + fl * DLAT, "lon": LON0 + fo * DLON,
                    "conf": round(random.uniform(0.72, 0.96), 2),
                    "frames": random.randint(4, 12), "fix": fix, "by": by,
                }
                print(f"[{elapsed:6.1f}s] drone {by} tagged survivor {sid} ({fix})")
        sid, better, by, at = RETAG
        if frac >= at and sid in found and found[sid]["fix"] != better:
            found[sid] = {**found[sid], "fix": better, "frames": 14, "by": by}
            print(f"[{elapsed:6.1f}s] drone {by} re-tagged survivor {sid} "
                  f"({better}) -- dedup should prefer this")

        if phase == "DELIVER":
            order = sorted(found)
            done = (frac - 0.68) / 0.22
            for n, s in enumerate(order):
                p = done * len(order) - n
                deliveries[s] = ("CONFIRMED" if p > 1.0 else
                                 "RELEASED" if p > 0.75 else
                                 "EN_ROUTE" if p > 0.35 else
                                 "ASSIGNED" if p > 0 else "UNASSIGNED")

        for i in range(3):
            did = i + 1
            # drone 2 drops off the mesh mid-search
            if did == 2 and 0.40 <= frac <= 0.46:
                continue
            lat, lon = boustrophedon(i, u) if phase in ("SEARCH", "DELIVER") \
                else (LAT0, LON0 + (i + 0.5) / 3.0 * DLON)

            send_udp(sock, args.host, args.mission_port, {
                "drone": did, "t": time.time(), "state": phase,
                "region": region(i),
                "task": ({"type": "DELIVER", "survivor": min(found) if found else None}
                         if phase == "DELIVER" else {"type": phase}),
                "detections": [
                    {k: v for k, v in d.items() if k != "by"}
                    for d in found.values() if d["by"] == did
                ],
                "deliveries": [{"survivor": s, "state": st}
                               for s, st in deliveries.items()
                               if (s % 3) == i],
            })

            if mav is not None:
                mav.mav.srcSystem = did
                mav.mav.heartbeat_send(2, 3, 128 | 64, 3, 4)
                mav.mav.global_position_int_send(
                    int(elapsed * 1000), int(lat * 1e7), int(lon * 1e7),
                    45000, 40000, 0, 0, 0, int((u * 36000) % 36000))
                mav.mav.gps_raw_int_send(
                    0, 6 if did != 3 else 5, int(lat * 1e7), int(lon * 1e7),
                    45000, 80, 80, 0, 0, random.randint(14, 22))
                mav.mav.sys_status_send(
                    0, 0, 0, 300, 22200, 1500,
                    max(20, int(100 - 70 * frac)), 0, 0, 0, 0, 0, 0)
                mav.mav.vfr_hud_send(9.0, 8.0, int(u * 360) % 360, 45, 40.0, 0.0)

        time.sleep(dt / args.speed)

    print(f"\nmission complete: {len(found)} survivors, "
          f"{sum(1 for v in deliveries.values() if v in ('RELEASED', 'CONFIRMED'))} "
          f"kits delivered")


if __name__ == "__main__":
    main()
