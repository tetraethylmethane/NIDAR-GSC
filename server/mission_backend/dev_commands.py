"""Vehicle command routes — DEV BUILD ONLY. Never loaded in mission mode.

⚠ Every route in this module is a rule 8.16 manual intervention if used during
the Final Mission, at −50 points each. That is precisely why it lives in a
separate module that `create_app(mission_mode=True)` does not import.

These exist because flight testing needs them. During P3–P6 you must be able to
arm, change mode, push a waypoint and jog a servo — you cannot commission an
aircraft without that. The mistake would be carrying the capability into the
mission build, which is what the ground station we inherited does.

If you are reading this while wondering how to add a "just nudge it a bit"
control to the mission GCS: don't. That is the −50.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

commands = Blueprint("dev_commands", __name__)


def _link():
    """Vehicle link, injected by the dev server. Stubbed here."""
    return getattr(request, "app_link", None)


@commands.post("/api/dev/drone/<int:drone_id>/arm")
def arm(drone_id: int):
    return jsonify({"ok": True, "drone": drone_id, "action": "ARM"})


@commands.post("/api/dev/drone/<int:drone_id>/disarm")
def disarm(drone_id: int):
    return jsonify({"ok": True, "drone": drone_id, "action": "DISARM"})


@commands.post("/api/dev/drone/<int:drone_id>/mode")
def set_mode(drone_id: int):
    mode = (request.get_json(silent=True) or {}).get("mode", "GUIDED")
    return jsonify({"ok": True, "drone": drone_id, "mode": mode})


@commands.post("/api/dev/drone/<int:drone_id>/waypoint")
def insert_waypoint(drone_id: int):
    """The one that costs −50 if it ever reaches a mission build."""
    body = request.get_json(silent=True) or {}
    return jsonify({"ok": True, "drone": drone_id,
                    "lat": body.get("lat"), "lon": body.get("lon"),
                    "alt": body.get("alt")})


@commands.post("/api/dev/drone/<int:drone_id>/servo")
def set_servo(drone_id: int):
    body = request.get_json(silent=True) or {}
    return jsonify({"ok": True, "drone": drone_id, "servo": body.get("servo")})


@commands.post("/api/dev/drone/<int:drone_id>/param")
def set_param(drone_id: int):
    body = request.get_json(silent=True) or {}
    return jsonify({"ok": True, "drone": drone_id, "param": body.get("key")})
