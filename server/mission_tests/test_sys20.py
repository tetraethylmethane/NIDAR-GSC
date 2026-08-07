"""SYS-20 verified by test, not by promise.

SYS-20 requires the mission GCS be "incapable of originating a retask, waypoint
change or drop command BY CONSTRUCTION", verified by source review. A source
review happens when someone remembers. This runs on every push.

The inherited ground station (NIDAR-GSC) exposes insert_command(lat, lon, alt),
jump_to_command, set_flight_mode, arm/disarm and servos on the same server the
operator uses during the mission. Rule 8.16 makes each of those a −50 manual
intervention. These tests exist so that cannot come back.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

flask = pytest.importorskip("flask", reason="Flask not installed")
from mission_backend.api import create_app  # noqa: E402
from mission_backend.fleet import Fleet  # noqa: E402


# Substrings that must never appear in a mission-build route.
FORBIDDEN = ("waypoint", "arm", "disarm", "mode", "servo", "param",
             "command", "mission/jump", "drop", "release", "retask")

# Rules explicitly permit these; 8.19 requires them.
ALLOWED_POST = ("/api/safety/abort", "/api/safety/recall",
                "/api/mission/boundary")


def routes(app):
    return [(r.rule, sorted(r.methods - {"HEAD", "OPTIONS"}))
            for r in app.url_map.iter_rules() if r.endpoint != "static"]


def test_mission_build_exposes_no_command_route():
    app = create_app(mission_mode=True)
    for rule, _ in routes(app):
        low = rule.lower()
        for bad in FORBIDDEN:
            assert bad not in low, (
                f"mission build exposes {rule!r}, which contains {bad!r}. "
                f"Rule 8.16 makes this a -50 manual intervention."
            )


def test_mission_build_has_no_mutating_routes_beyond_the_allowed_three():
    app = create_app(mission_mode=True)
    posts = [rule for rule, methods in routes(app)
             if {"POST", "PUT", "PATCH", "DELETE"} & set(methods)]
    assert sorted(posts) == sorted(ALLOWED_POST), (
        f"unexpected mutating routes in the mission build: "
        f"{sorted(set(posts) - set(ALLOWED_POST))}"
    )


def test_dev_command_module_is_not_even_imported_in_mission_mode():
    """Structural, not a feature flag. A flag can be flipped by a config file;
    an unimported module cannot be reached at all."""
    for mod in list(sys.modules):
        if "dev_commands" in mod:
            del sys.modules[mod]
    create_app(mission_mode=True)
    assert not any("dev_commands" in m for m in sys.modules), (
        "dev_commands was imported in mission mode — the split is not structural"
    )


def test_dev_build_does_expose_commands():
    """The dev build must keep them: you cannot commission an aircraft without
    arm, mode change and manual waypoints."""
    app = create_app(mission_mode=False)
    rules = [r for r, _ in routes(app)]
    assert any("waypoint" in r for r in rules)
    assert any("arm" in r for r in rules)


def test_abort_and_recall_exist_in_the_mission_build():
    """8.19 requires mission abort and emergency recall. Removing them to
    satisfy SYS-20 would break a different rule."""
    app = create_app(mission_mode=True)
    rules = [r for r, _ in routes(app)]
    assert "/api/safety/abort" in rules
    assert "/api/safety/recall" in rules


def test_abort_and_recall_actually_work():
    f = Fleet()
    app = create_app(mission_mode=True, fleet=f)
    c = app.test_client()
    assert c.post("/api/safety/abort").get_json()["action"] == "ABORT"
    assert c.post("/api/safety/recall").get_json()["action"] == "RECALL"
    assert f.abort_requested and f.recall_requested


def test_boundary_load_is_permitted_and_works():
    """MB §3 lists mission-file loading as an allowed operator action."""
    app = create_app(mission_mode=True)
    kml = ('<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark>'
           '<name>Area</name><Polygon><outerBoundaryIs><LinearRing><coordinates>'
           '80.0,13.0 80.0037,13.0 80.0037,13.00225 80.0,13.00225'
           '</coordinates></LinearRing></outerBoundaryIs></Polygon>'
           '</Placemark></Document></kml>')
    r = app.test_client().post("/api/mission/boundary", data=kml)
    assert r.status_code == 200
    body = r.get_json()
    assert body["area_ha"] == pytest.approx(10.0, rel=0.05)
    assert body["points"][0][0] == pytest.approx(13.0)   # lat, not lon


def test_fleet_snapshot_serves_every_8_14_field():
    app = create_app(mission_mode=True)
    body = app.test_client().get("/api/fleet").get_json()
    for key in ("vehicles", "regions", "phases", "tasks",
                "survivors", "deliveries", "progress", "warnings"):
        assert key in body
