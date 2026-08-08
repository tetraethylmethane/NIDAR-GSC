"""MAVLink ingest — three SYSIDs into one Fleet.

The inherited ground station opened one DroneKit connection to one vehicle.
NIDAR flies three aircraft through a single GCS (rule 8.13, 50 binary points),
so telemetry arrives as one multiplexed stream from **mavlink-router**, with the
aircraft distinguished by MAVLink source system ID.

    drone 1 ─┐
    drone 2 ─┼─► mavlink-router ─► udpout:127.0.0.1:14550 ─► this module ─► Fleet
    drone 3 ─┘

DESIGN NOTE. `handle_message()` is a pure function of (fleet, message) with no
socket in sight, and the receive loop is a thin wrapper around it. That is
deliberate: it makes every field mapping testable against synthetic MAVLink
messages, with no aircraft, no SITL and no network. The loop is the part that
cannot be unit tested, so it is kept as small as possible.

THE FIELD THAT MATTERS MOST is `GPS_RAW_INT.fix_type`. RTK_FIXED vs RTK_FLOAT is
the difference between a 0.91 m and a 1.37 m geotag, which is worth ~20 delivery
points; and no RTK at all costs ~100. `Fleet.survivors()` ranks competing
observations on exactly this value, so mapping it correctly is not cosmetic.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from .fleet import Fleet

log = logging.getLogger("groundstation.mavlink")

# MAV_GPS_FIX_TYPE -> the strings Fleet and the client understand.
# 5 and 6 are the ones that decide the geotag budget.
GPS_FIX_TYPE = {
    0: "NONE",       # NO_GPS
    1: "NONE",       # NO_FIX
    2: "2D",
    3: "3D",
    4: "DGPS",
    5: "RTK_FLOAT",
    6: "RTK_FIXED",
    7: "3D",         # STATIC
    8: "3D",         # PPP
}

# ArduCopter custom_mode -> name. Only the modes this mission can be in.
COPTER_MODE = {
    0: "STABILIZE", 1: "ACRO", 2: "ALT_HOLD", 3: "AUTO", 4: "GUIDED",
    5: "LOITER", 6: "RTL", 7: "CIRCLE", 9: "LAND", 16: "POSHOLD",
    17: "BRAKE", 20: "GUIDED_NOGPS", 21: "SMART_RTL", 27: "AUTO_RTL",
}

MAV_MODE_FLAG_SAFETY_ARMED = 128


def handle_message(fleet: Fleet, msg: Any) -> bool:
    """Apply one MAVLink message to the fleet. Returns True if it was used.

    Unknown message types are ignored rather than raising: a real stream carries
    dozens of types we do not care about, and a GCS that falls over on an
    unexpected packet is worse than one that ignores it.
    """
    try:
        mtype = msg.get_type()
        sysid = msg.get_srcSystem()
    except AttributeError:
        return False

    if mtype == "BAD_DATA" or sysid == 0:
        return False

    if mtype == "HEARTBEAT":
        # Ignore the GCS's own heartbeat and any component that is not a vehicle.
        if getattr(msg, "type", None) == 6:          # MAV_TYPE_GCS
            return False
        fleet.update_vehicle(
            sysid,
            mode=COPTER_MODE.get(getattr(msg, "custom_mode", -1), "UNKNOWN"),
            armed=bool(getattr(msg, "base_mode", 0) & MAV_MODE_FLAG_SAFETY_ARMED),
        )
        return True

    if mtype == "GLOBAL_POSITION_INT":
        fleet.update_vehicle(
            sysid,
            lat=msg.lat / 1e7,
            lon=msg.lon / 1e7,
            alt_m=msg.relative_alt / 1000.0,        # AGL, not AMSL
            heading_deg=(msg.hdg / 100.0) if msg.hdg != 65535 else None,
        )
        return True

    if mtype == "GPS_RAW_INT":
        fleet.update_vehicle(
            sysid,
            gnss_fix=GPS_FIX_TYPE.get(msg.fix_type, "NONE"),
            satellites=msg.satellites_visible,
        )
        return True

    if mtype == "VFR_HUD":
        fleet.update_vehicle(sysid, groundspeed_ms=msg.groundspeed)
        return True

    if mtype == "SYS_STATUS":
        pct = msg.battery_remaining
        fleet.update_vehicle(
            sysid,
            battery_pct=float(pct) if pct not in (-1, 255) else None,
            battery_v=(msg.voltage_battery / 1000.0)
            if msg.voltage_battery not in (0, 65535) else None,
        )
        return True

    if mtype == "BATTERY_STATUS":
        pct = getattr(msg, "battery_remaining", -1)
        if pct not in (-1, 255):
            fleet.update_vehicle(sysid, battery_pct=float(pct))
            return True
        return False

    if mtype == "RADIO_STATUS":
        # RADIO_STATUS comes from the radio, not the vehicle, so it carries the
        # radio's sysid. Attribute it to the vehicle only if we know that id.
        if sysid in fleet.vehicles:
            fleet.update_vehicle(sysid, link_rssi_dbm=_rssi_dbm(msg.rssi))
            return True
        return False

    return False


def _rssi_dbm(raw: int) -> float:
    """SiK radio RSSI byte to approximate dBm.

    The SiK firmware convention is dBm = raw/1.9 - 127. Approximate, and only
    used for an operator health indicator, never for a decision.
    """
    return round(raw / 1.9 - 127.0, 1)


class MavlinkIngest:
    """Receive loop around `handle_message`. Kept deliberately thin."""

    def __init__(
        self,
        fleet: Fleet,
        endpoint: str = "udpin:0.0.0.0:14550",
        source_system: int = 255,
    ) -> None:
        self.fleet = fleet
        self.endpoint = endpoint
        self.source_system = source_system
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.conn: Any = None
        self.messages_used = 0

    def start(self, connect: Callable[..., Any] | None = None) -> None:
        if connect is None:                              # pragma: no cover
            from pymavlink import mavutil

            connect = mavutil.mavlink_connection
        self.conn = connect(self.endpoint, source_system=self.source_system)
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="mavlink-ingest")
        self._thread.start()
        log.info("MAVLink ingest started on %s", self.endpoint)

    def _loop(self) -> None:                             # pragma: no cover
        while not self._stop.is_set():
            try:
                msg = self.conn.recv_match(blocking=True, timeout=1.0)
            except Exception:
                log.exception("MAVLink receive failed")
                continue
            if msg is None:
                continue
            if handle_message(self.fleet, msg):
                self.messages_used += 1

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
