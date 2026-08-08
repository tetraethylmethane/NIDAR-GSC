"""Mission-state ingest — the 5 Hz mesh document into Fleet.update_mission.

Telemetry and mission state travel separately (see PLAN.md §2.1). MAVLink
carries position, mode and battery. This carries what MAVLink has no message
for: which region a drone was assigned, what task it is on, which survivors it
has geotagged, and how far each delivery has got.

Wire format: one UDP datagram per drone, 5 Hz, JSON. The RF budget allocates
25 kbps of swarm state and 150 kbps of detection metadata per drone for exactly
this (`sizing-calculations.md` §12.1).

    {"drone": 2, "t": 1723459200.4, "state": "SEARCH",
     "region": [[13.0,80.0], ...],
     "task": {"type": "DELIVER", "survivor": 4},
     "detections": [{"id": 4, "lat": .., "lon": .., "conf": 0.91,
                     "frames": 7, "fix": "RTK_FIXED"}],
     "deliveries": [{"survivor": 4, "state": "RELEASED"}]}

DESIGN NOTE, same as the MAVLink side: `handle_datagram()` is a pure function so
every parsing and validation path is testable without a socket. The receive loop
is a thin wrapper.

ROBUSTNESS IS THE POINT. This runs during an eight-minute scored mission on a
mesh that is expected to partition. A malformed, truncated or duplicated
datagram must never take the GCS down — losing the display loses the evidence
for 250 points, whatever the aircraft are doing.
"""
from __future__ import annotations

import json
import logging
import socket
import threading
from typing import Any

from .fleet import Fleet

log = logging.getLogger("groundstation.mission")

MAX_DATAGRAM = 65535
REQUIRED = ("drone",)


class MissionIngestStats:
    __slots__ = ("accepted", "rejected", "last_error")

    def __init__(self) -> None:
        self.accepted = 0
        self.rejected = 0
        self.last_error: str | None = None


def handle_datagram(fleet: Fleet, data: bytes,
                    stats: MissionIngestStats | None = None) -> bool:
    """Apply one mission-state datagram. Returns True if it was accepted.

    Never raises. A bad packet increments a counter and is dropped.
    """
    def reject(why: str) -> bool:
        if stats:
            stats.rejected += 1
            stats.last_error = why
        log.debug("mission datagram rejected: %s", why)
        return False

    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return reject(f"not JSON: {exc}")

    if not isinstance(doc, dict):
        return reject("payload is not an object")
    for key in REQUIRED:
        if key not in doc:
            return reject(f"missing {key!r}")
    try:
        drone_id = int(doc["drone"])
    except (TypeError, ValueError):
        return reject("drone id not an integer")
    if not 1 <= drone_id <= 250:
        return reject(f"drone id {drone_id} outside MAVLink sysid range")

    # Stale-packet rejection. UDP reorders, and applying an older document over
    # a newer one would make survivors and deliveries flicker backwards on the
    # operator's display.
    t = doc.get("t")
    if isinstance(t, (int, float)):
        prev = fleet.mission.get(drone_id)
        last = getattr(prev, "doc_t", None) if prev else None
        if last is not None and t < last:
            return reject(f"stale: t={t} < {last}")

    try:
        fleet.update_mission(doc)
    except (KeyError, TypeError, ValueError) as exc:
        return reject(f"malformed field: {exc}")

    if isinstance(t, (int, float)):
        fleet.mission[drone_id].doc_t = t          # type: ignore[attr-defined]
    if stats:
        stats.accepted += 1
    return True


class MissionIngest:
    """UDP listener. Thin wrapper around `handle_datagram`."""

    def __init__(self, fleet: Fleet, host: str = "0.0.0.0",
                 port: int = 14660) -> None:
        self.fleet = fleet
        self.host = host
        self.port = port
        self.stats = MissionIngestStats()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.sock: socket.socket | None = None

    def start(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.settimeout(1.0)
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="mission-ingest")
        self._thread.start()
        log.info("mission-state ingest listening on %s:%d", self.host, self.port)

    def _loop(self) -> None:
        assert self.sock is not None
        while not self._stop.is_set():
            try:
                data, _addr = self.sock.recvfrom(MAX_DATAGRAM)
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    return
                log.exception("mission ingest socket error")
                continue
            handle_datagram(self.fleet, data, self.stats)

    def stop(self) -> None:
        self._stop.set()
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=2.0)


def send(doc: dict[str, Any], host: str = "127.0.0.1",
         port: int = 14660) -> None:
    """Emit one mission-state document. Used by SITL harnesses and tests."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(json.dumps(doc).encode("utf-8"), (host, port))
