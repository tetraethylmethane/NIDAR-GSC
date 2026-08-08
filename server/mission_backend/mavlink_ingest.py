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

# ---------------------------------------------------------------------------
# TELEMETRY MUST BE ASKED FOR. This is not optional and it is not obvious.
#
# ArduPilot streams messages at the rates set by the SRx_* parameters for the
# channel the GCS is on, and a channel that has never had a stream request sends
# almost nothing. Measured against a real ArduCopter SITL over UDP:
#
#   passive listener            HEARTBEAT only, 1 Hz. Nothing else.
#   + GCS heartbeat             still HEARTBEAT only.
#   + SET_MESSAGE_INTERVAL      everything, at the rates asked for.
#
# So a GCS that only listens shows flight mode and armed state and NOTHING
# ELSE: no position, no altitude, no battery, no GNSS fix. That is rule 8.14
# items 3 and 4 blank on the operator's screen, and the survivor geotag fix
# quality -- worth ~100 points -- unknown.
#
# The synthetic tests could not have caught this. They call handle_message()
# with constructed messages, which tests the mapping and says nothing about
# whether the messages ever arrive. It took a real autopilot.
#
# ON SYS-20 AND RULE 8.16. MAV_CMD_SET_MESSAGE_INTERVAL configures the
# telemetry stream. It is not a retask, a waypoint change, a mode change or a
# payload command -- it cannot alter what the aircraft does, only what it tells
# us about it. Every GCS ever written sends it on connect. The implementation
# below can emit exactly two things, a GCS heartbeat and this one command with
# a message id from REQUESTED_STREAMS; test_ingest.py asserts that nothing else
# is ever transmitted.
#
# Rates are deliberately modest. The RF budget allows ~0.7 Mbps for telemetry
# and detection metadata across all three aircraft, and this is per aircraft.
REQUESTED_STREAMS: dict[int, float] = {
    33: 4.0,    # GLOBAL_POSITION_INT — position and heading (8.14 item 3)
    24: 2.0,    # GPS_RAW_INT         — fix type; decides the geotag budget
    74: 4.0,    # VFR_HUD             — groundspeed
    1:  1.0,    # SYS_STATUS          — battery (8.14 item 4)
}

MAV_CMD_SET_MESSAGE_INTERVAL = 511
MAV_TYPE_GCS = 6
MAV_AUTOPILOT_INVALID = 8

# Re-ask this often for any aircraft that has told us a mode but still has no
# position. Covers an autopilot that rebooted, a link that dropped the request,
# and mavlink-router coming up after us.
REREQUEST_S = 10.0


def stream_requests(sysid: int) -> list[tuple[int, int, int]]:
    """(target_system, message_id, interval_us) for one aircraft.

    Pure, so the request set is testable without a socket -- the same reason
    handle_message is pure.
    """
    return [(sysid, mid, int(1_000_000 / hz))
            for mid, hz in sorted(REQUESTED_STREAMS.items())]


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
    """Receive loop around `handle_message`, plus the transmit side.

    The transmit side exists only because telemetry has to be requested -- see
    REQUESTED_STREAMS. It sends a GCS heartbeat and MAV_CMD_SET_MESSAGE_INTERVAL
    and nothing else, ever.
    """

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
        self._tx_thread: threading.Thread | None = None
        self.conn: Any = None
        self.messages_used = 0
        self.requests_sent = 0
        self._requested: dict[int, float] = {}   # sysid -> monotonic time

    def start(self, connect: Callable[..., Any] | None = None) -> None:
        if connect is None:                              # pragma: no cover
            from pymavlink import mavutil

            connect = mavutil.mavlink_connection
        self.conn = connect(self.endpoint, source_system=self.source_system)
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="mavlink-ingest")
        self._thread.start()
        self._tx_thread = threading.Thread(target=self._tx_loop, daemon=True,
                                           name="mavlink-request")
        self._tx_thread.start()
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

    # -- transmit ----------------------------------------------------------
    def needs_request(self, sysid: int, now: float) -> bool:
        """Ask again if we have never asked, or if we asked and STILL have no
        position from this aircraft.

        The second case covers an autopilot that rebooted mid-mission, a request
        dropped on a lossy link, and mavlink-router coming up after us. Once
        position is flowing we stop asking, so a healthy link carries no repeat
        traffic.
        """
        last = self._requested.get(sysid)
        if last is None:
            return True
        v = self.fleet.vehicles.get(sysid)
        if v is not None and v.lat is not None:
            return False
        return (now - last) >= REREQUEST_S

    def send_requests(self, sysid: int) -> None:
        """Emit the SET_MESSAGE_INTERVAL set for one aircraft.

        Component 1 (MAV_COMP_ID_AUTOPILOT1) rather than 0: mavlink-router
        forwards on system id, and addressing the autopilot explicitly avoids a
        companion computer on the same system id answering instead.
        """
        for target, mid, interval_us in stream_requests(sysid):
            self.conn.mav.command_long_send(
                target, 1, MAV_CMD_SET_MESSAGE_INTERVAL, 0,
                mid, interval_us, 0, 0, 0, 0, 0)
            self.requests_sent += 1

    def tick(self, now: float) -> None:
        """One transmit cycle. Separated from the loop so it is testable."""
        self.conn.mav.heartbeat_send(
            MAV_TYPE_GCS, MAV_AUTOPILOT_INVALID, 0, 0, 0)
        for sysid in list(self.fleet.vehicles):
            if self.needs_request(sysid, now):
                self.send_requests(sysid)
                self._requested[sysid] = now
                log.info("requested telemetry streams from SYSID %d", sysid)

    def _tx_loop(self) -> None:                          # pragma: no cover
        import time as _time

        while not self._stop.wait(1.0):
            try:
                self.tick(_time.monotonic())
            except Exception:
                log.exception("MAVLink transmit failed")

    def stop(self) -> None:
        self._stop.set()
        for t in (self._thread, self._tx_thread):
            if t:
                t.join(timeout=2.0)
