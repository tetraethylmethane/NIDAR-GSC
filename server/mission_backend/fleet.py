"""Fleet and mission state — the data model behind rule 8.14.

Rule 8.14 requires the GCS to display, at minimum: mission status, a live camera
feed from EACH drone, the position of each drone, the assigned search area or
task per drone, detected and geotagged survivor locations, kit delivery status,
comms and system health, and consolidated mission progress.

The existing ground station holds ONE vehicle object. This module is the
multi-vehicle replacement, and it deliberately keeps two things apart:

  VehicleState   position, mode, battery, GNSS fix, link health.
                 Arrives over MAVLink via mavlink-router, SYSID 1/2/3.

  MissionState   assigned region, current task, detections, deliveries.
                 Arrives as a small JSON document per drone at 5 Hz over the
                 mesh. There is no sensible MAVLink message for "survivor at
                 lat/lon, confidence 0.87, confirmed by 3 frames", and bending
                 NAMED_VALUE_FLOAT into that shape is a trap.

Merging three MissionStates into one consolidated view is what actually
satisfies the "single unified operator interface" criterion (4D-4, 50 points).

Stdlib only.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable

# A drone is considered stale if nothing has arrived for this long. The design
# continues an assigned bundle for 10 s of mesh loss and returns home at 60 s,
# so the GCS should show a warning well before the aircraft acts on its own.
STALE_S = 3.0
LOST_S = 10.0


@dataclass
class VehicleState:
    """Per-drone flight state, from MAVLink."""

    drone_id: int
    lat: float | None = None
    lon: float | None = None
    alt_m: float | None = None
    heading_deg: float | None = None
    groundspeed_ms: float | None = None
    mode: str = "UNKNOWN"
    armed: bool = False
    battery_pct: float | None = None
    battery_v: float | None = None
    gnss_fix: str = "NONE"          # NONE | 2D | 3D | DGPS | RTK_FLOAT | RTK_FIXED
    satellites: int = 0
    link_rssi_dbm: float | None = None
    mesh_peers: int = 0
    updated: float = field(default_factory=time.time)

    @property
    def age_s(self) -> float:
        return time.time() - self.updated

    @property
    def health(self) -> str:
        """OK | STALE | LOST — 8.14 item 7."""
        a = self.age_s
        if a > LOST_S:
            return "LOST"
        if a > STALE_S:
            return "STALE"
        return "OK"

    @property
    def rtk(self) -> bool:
        return self.gnss_fix in ("RTK_FLOAT", "RTK_FIXED")


@dataclass
class Detection:
    """A geotagged survivor observation — 8.14 item 5."""

    survivor_id: int
    lat: float
    lon: float
    confidence: float = 0.0
    frames: int = 1
    fix: str = "NONE"               # GNSS fix quality AT THE TIME OF THE TAG
    reported_by: int | None = None
    t: float = field(default_factory=time.time)

    def quality(self) -> tuple[int, int, float]:
        """Sort key for choosing between competing observations.

        RTK_FIXED beats RTK_FLOAT beats everything else; then more frames; then
        higher confidence. Fix quality dominates because it is worth metres,
        where confidence is worth nothing at all in position terms.
        """
        rank = {"RTK_FIXED": 2, "RTK_FLOAT": 1}.get(self.fix, 0)
        return (rank, self.frames, self.confidence)


@dataclass
class Delivery:
    """Kit delivery progress for one survivor — 8.14 item 6."""

    survivor_id: int
    state: str = "UNASSIGNED"       # UNASSIGNED|ASSIGNED|EN_ROUTE|RELEASED|CONFIRMED|FAILED
    drone_id: int | None = None
    t: float = field(default_factory=time.time)

    ORDER = ("UNASSIGNED", "ASSIGNED", "EN_ROUTE", "RELEASED", "CONFIRMED", "FAILED")

    def rank(self) -> int:
        try:
            return self.ORDER.index(self.state)
        except ValueError:
            return 0


@dataclass
class MissionState:
    """Per-drone mission state, from the 5 Hz mesh document."""

    drone_id: int
    phase: str = "IDLE"             # IDLE|SETUP|CLIMB|SEARCH|DELIVER|RTH|LANDED
    region: list[tuple[float, float]] = field(default_factory=list)
    task: dict[str, Any] = field(default_factory=dict)
    detections: list[Detection] = field(default_factory=list)
    deliveries: list[Delivery] = field(default_factory=list)
    updated: float = field(default_factory=time.time)


class Fleet:
    """The consolidated view of all aircraft. One of these per GCS."""

    def __init__(self, drone_ids: Iterable[int] = (1, 2, 3)) -> None:
        self.vehicles: dict[int, VehicleState] = {
            i: VehicleState(drone_id=i) for i in drone_ids
        }
        self.mission: dict[int, MissionState] = {
            i: MissionState(drone_id=i) for i in drone_ids
        }
        self.expected_survivors = 10
        self.started_at: float | None = None
        # Set by the safety blueprint. Declared here so the two permitted
        # operator actions are visible in the data model, not bolted on.
        self.abort_requested = False
        self.recall_requested = False

    # ---------------------------------------------------------------- ingest
    def update_vehicle(self, drone_id: int, **fields: Any) -> None:
        v = self.vehicles.setdefault(drone_id, VehicleState(drone_id=drone_id))
        for k, val in fields.items():
            if hasattr(v, k):
                setattr(v, k, val)
        v.updated = time.time()

    def update_mission(self, doc: dict[str, Any]) -> None:
        """Ingest one 5 Hz mission-state document from a drone."""
        did = int(doc["drone"])
        ms = self.mission.setdefault(did, MissionState(drone_id=did))
        ms.phase = doc.get("state", ms.phase)
        if "region" in doc:
            ms.region = [(float(a), float(b)) for a, b in doc["region"]]
        ms.task = doc.get("task", {}) or {}
        ms.detections = [
            Detection(
                survivor_id=int(d["id"]), lat=float(d["lat"]), lon=float(d["lon"]),
                confidence=float(d.get("conf", 0.0)), frames=int(d.get("frames", 1)),
                fix=str(d.get("fix", "NONE")), reported_by=did,
            )
            for d in doc.get("detections", [])
        ]
        ms.deliveries = [
            Delivery(
                survivor_id=int(x["survivor"]), state=str(x.get("state", "UNASSIGNED")),
                drone_id=did,
            )
            for x in doc.get("deliveries", [])
        ]
        ms.updated = time.time()

    # ------------------------------------------------------------ consolidate
    def survivors(self) -> dict[int, Detection]:
        """Fleet-wide survivor list, deduplicated across drones.

        Two aircraft can see the same survivor. The tag we display -- and aim a
        kit at -- must be the BEST observation, not the most recent, because a
        later RTK_FLOAT tag is worse than an earlier RTK_FIXED one.
        """
        best: dict[int, Detection] = {}
        for ms in self.mission.values():
            for d in ms.detections:
                cur = best.get(d.survivor_id)
                if cur is None or d.quality() > cur.quality():
                    best[d.survivor_id] = d
        return dict(sorted(best.items()))

    def deliveries(self) -> dict[int, Delivery]:
        """Fleet-wide delivery status, furthest-progressed wins."""
        best: dict[int, Delivery] = {}
        for ms in self.mission.values():
            for x in ms.deliveries:
                cur = best.get(x.survivor_id)
                if cur is None or x.rank() > cur.rank():
                    best[x.survivor_id] = x
        return dict(sorted(best.items()))

    def progress(self) -> dict[str, Any]:
        """Consolidated mission progress — 8.14 item 8."""
        surv = self.survivors()
        deliv = self.deliveries()
        done = [d for d in deliv.values() if d.state in ("RELEASED", "CONFIRMED")]
        elapsed = (time.time() - self.started_at) if self.started_at else 0.0
        return {
            "found": len(surv),
            "expected": self.expected_survivors,
            "delivered": len(done),
            "elapsed_s": round(elapsed, 1),
            "elapsed": f"{int(elapsed // 60)}:{int(elapsed % 60):02d}",
            "bonus_window_s": max(0.0, 900.0 - elapsed),   # 15 min, 4D-5
            "drones_ok": sum(1 for v in self.vehicles.values() if v.health == "OK"),
            "drones_total": len(self.vehicles),
            "rtk_fixed": sum(1 for v in self.vehicles.values()
                             if v.gnss_fix == "RTK_FIXED"),
        }

    def warnings(self) -> list[str]:
        """Operator-facing warnings. The GCS cannot act, but it must inform."""
        out: list[str] = []
        for v in self.vehicles.values():
            if v.health == "LOST":
                out.append(f"drone {v.drone_id}: telemetry lost ({v.age_s:.0f} s)")
            elif v.health == "STALE":
                out.append(f"drone {v.drone_id}: telemetry stale ({v.age_s:.1f} s)")
            if v.battery_pct is not None and v.battery_pct < 25:
                out.append(f"drone {v.drone_id}: battery {v.battery_pct:.0f} %")
            if v.armed and not v.rtk:
                out.append(f"drone {v.drone_id}: no RTK ({v.gnss_fix}) — "
                           f"geotags will be degraded")
        # A survivor tagged without RTK is a scoring problem, not just a warning.
        for s in self.survivors().values():
            if s.fix not in ("RTK_FIXED", "RTK_FLOAT"):
                out.append(f"survivor {s.survivor_id}: tagged without RTK ({s.fix})")
        return out

    def snapshot(self) -> dict[str, Any]:
        """Everything rule 8.14 requires, in one document for the client."""
        return {
            "vehicles": {
                i: {**asdict(v), "health": v.health, "age_s": round(v.age_s, 2)}
                for i, v in self.vehicles.items()
            },
            "regions": {i: ms.region for i, ms in self.mission.items()},
            "phases": {i: ms.phase for i, ms in self.mission.items()},
            "tasks": {i: ms.task for i, ms in self.mission.items()},
            "survivors": {k: asdict(v) for k, v in self.survivors().items()},
            "deliveries": {k: asdict(v) for k, v in self.deliveries().items()},
            "progress": self.progress(),
            "warnings": self.warnings(),
        }
