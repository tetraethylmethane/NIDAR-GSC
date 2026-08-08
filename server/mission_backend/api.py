"""Flask app factory with the SYS-20 module split.

SYS-20: "GCS shall be incapable of originating a retask, waypoint change or drop
command by construction", verified by source review. Abort and recall are exempt
— permitted by 8.16 and required by 8.19.

The mechanism is deliberately structural rather than a feature flag. In mission
mode the command blueprint is **never imported and never registered**, so there
is no route to reach. `test_sys20.py` asserts this against the live URL map, so
the requirement is checked by CI on every push rather than by someone
remembering to look.

  create_app(mission_mode=True)   -> mission build.  Telemetry + abort/recall.
  create_app(mission_mode=False)  -> dev build.      Everything, for flight test.
"""
from __future__ import annotations

from typing import Any

from flask import Blueprint, Flask, current_app, jsonify, request

from .fleet import Fleet
from .kml import KMLError, check_against_brief, parse_boundary

# ---------------------------------------------------------------- mission view
# Read-only. Everything rule 8.14 requires the GCS to display.
view = Blueprint("view", __name__)


@view.get("/api/fleet")
def fleet_snapshot():
    """The single consolidated document behind the unified interface (4D-4)."""
    snap = request.app_fleet.snapshot()
    # The client uses this to hide every command control in a mission build.
    # Defence in depth: the server already refuses the requests, but a button
    # that exists at all invites the click that costs -50.
    snap["mission_mode"] = bool(current_app.config.get("MISSION_MODE", True))
    return jsonify(snap)


@view.get("/api/fleet/progress")
def progress():
    return jsonify(request.app_fleet.progress())


@view.get("/api/drone/<int:drone_id>")
def drone(drone_id: int):
    f: Fleet = request.app_fleet
    if drone_id not in f.vehicles:
        return jsonify({"error": "unknown drone"}), 404
    v = f.vehicles[drone_id]
    ms = f.mission[drone_id]
    return jsonify({
        "id": drone_id, "health": v.health, "mode": v.mode, "armed": v.armed,
        "lat": v.lat, "lon": v.lon, "alt_m": v.alt_m, "gnss_fix": v.gnss_fix,
        "battery_pct": v.battery_pct, "phase": ms.phase, "task": ms.task,
        "region": ms.region,
    })


@view.post("/api/mission/boundary")
def load_boundary():
    """Load the organisers' KML — SYS-38.

    This is a POST but it is NOT a vehicle command. MB §3 explicitly permits
    mission-file loading; it is one of the four allowed operator actions.
    """
    payload = request.get_data(as_text=True)
    try:
        b = parse_boundary(payload)
    except KMLError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({
        "name": b.name,
        "points": b.points,
        "area_ha": round(b.area_hectares(), 2),
        "bounds": b.bounds(),
        "warnings": check_against_brief(b),
    })


# ------------------------------------------------------------------- safety
# Permitted by 8.16, required by 8.19. Present in BOTH builds.
safety = Blueprint("safety", __name__)


@safety.post("/api/safety/abort")
def abort():
    """Mission abort — all aircraft hold, then sequenced recovery."""
    request.app_fleet.abort_requested = True
    return jsonify({"ok": True, "action": "ABORT"})


@safety.post("/api/safety/recall")
def recall():
    """Emergency recall — immediate RTH on the 868 MHz link."""
    request.app_fleet.recall_requested = True
    return jsonify({"ok": True, "action": "RECALL"})


def create_app(mission_mode: bool = True, fleet: Fleet | None = None) -> Flask:
    app = Flask(__name__)
    app.config["MISSION_MODE"] = mission_mode
    f = fleet or Fleet()

    @app.before_request
    def _attach() -> None:
        request.app_fleet = f            # type: ignore[attr-defined]

    app.register_blueprint(view)
    app.register_blueprint(safety)

    if not mission_mode:
        # Dev build only. During P3-P6 flight testing you WANT arm, mode change
        # and manual waypoints -- that is how flight testing works. This import
        # is inside the branch so the module is not even loaded in a mission
        # build, which is what makes SYS-20 checkable rather than promised.
        from .dev_commands import commands           # noqa: PLC0415

        app.register_blueprint(commands)

    return app
