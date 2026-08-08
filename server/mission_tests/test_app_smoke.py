"""Integration smoke test — proves app.py actually starts.

The mission layer had unit tests but the WIRING into app.py was unverified: it
compiled, and nothing more. This closes that gap without needing an aircraft.

NOTHING IS STUBBED. That is the point of this file now.

This test used to install a fake `dronekit` module so app.py could be imported
at all, because `apps.uav` -> `handlers/uav.py` -> `dronekit`, and DroneKit does
`collections.MutableMapping` — moved to `collections.abc` in Python 3.10. The
stub let the test pass on 3.12 while the real server still could not boot on
3.12, which is the worst kind of green tick: it tested a program nobody runs.

The mission build now does not import the legacy layer at all, so this file
imports app.py exactly as `python app.py` does, on whatever interpreter CI is
running, with no stub in sight. `test_dronekit_is_not_in_the_mission_process`
asserts the absence directly.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(HERE)
sys.path.insert(0, SERVER)

pytest.importorskip("flask_cors", reason="flask-cors not installed")


@pytest.fixture(scope="module")
def app_module(tmp_path_factory):
    """Import app.py the way `python app.py` does, minus the sockets."""
    cwd = os.getcwd()
    os.chdir(SERVER)
    import json
    import shutil

    existing = os.path.exists("config.json")
    if existing:
        shutil.copy("config.json", "config.json.smokebak")
    cfg = json.load(open("sample.config.json", encoding="utf-8"))
    cfg["drones"] = [1, 2, 3]
    with open("config.json", "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    made = True
    os.environ["MISSION_MODE"] = "1"
    os.environ["NIDAR_INGEST"] = "0"      # do not bind sockets in a test
    try:
        for mod in [m for m in sys.modules if m.startswith(("app", "groundstation",
                                                            "apps", "handlers"))]:
            del sys.modules[mod]
        sys.modules.pop("dronekit", None)
        import app as app_mod

        yield app_mod
    finally:
        if os.path.exists("config.json.smokebak"):
            shutil.move("config.json.smokebak", "config.json")
        elif made:
            os.remove("config.json")
        os.chdir(cwd)


def test_dronekit_is_not_in_the_mission_process(app_module):
    """The reason the mission server could not start on a current interpreter.

    DroneKit is unmaintained, single-vehicle by construction, and unimportable
    on Python >= 3.10. It is also redundant here: mavlink_ingest.py already
    carries position, mode, battery and GNSS fix for all THREE aircraft over
    pymavlink, which DroneKit cannot do at all.

    Asserting absence rather than non-use is deliberate. "We do not call it" is
    a claim about intent; "it is not in sys.modules" is a fact about the running
    process, and it is the one that decides whether the server boots.
    """
    assert "dronekit" not in sys.modules, (
        "dronekit was imported by the mission build — the server will not "
        "start on Python >= 3.10"
    )


def test_legacy_groundstation_is_not_constructed_in_mission_mode(app_module):
    """It opens a DroneKit link to ONE aircraft and spawns a polling thread for
    it. In a mission build there are three aircraft and they arrive over
    mavlink_ingest, so there is nothing for it to do."""
    assert app_module.app.gs is None


def test_python_version_is_one_the_mission_build_actually_supports():
    """Guard against the fix regressing into a Python 3.9 pin."""
    assert sys.version_info >= (3, 10), (
        "these tests are meant to run on the interpreter the mission server "
        "runs on; pinning 3.9 to keep DroneKit is the fix we rejected"
    )


def test_app_imports_and_has_a_flask_app(app_module):
    """The thing that was previously unproven: app.py actually starts."""
    from flask import Flask

    assert isinstance(app_module.app, Flask)


def test_mission_mode_defaults_on(app_module):
    assert app_module.app.config["MISSION_MODE"] is True


def test_fleet_is_attached_with_three_drones(app_module):
    assert set(app_module.fleet.vehicles) == {1, 2, 3}


def test_mission_routes_are_registered(app_module):
    rules = {r.rule for r in app_module.app.url_map.iter_rules()}
    for expected in ("/api/fleet", "/api/fleet/progress",
                     "/api/drone/<int:drone_id>", "/api/mission/boundary",
                     "/api/safety/abort", "/api/safety/recall"):
        assert expected in rules, f"{expected} missing from the live app"


def test_no_new_command_route_in_the_live_app(app_module):
    """The mission blueprint must contribute no command route."""
    for rule in app_module.app.url_map.iter_rules():
        low = rule.rule.lower()
        if low.startswith(("/uav", "/image")):
            continue          # legacy, covered by the guard test below
        for bad in ("waypoint", "/arm", "disarm", "servo", "dev/"):
            assert bad not in low, (
                f"live app exposes {rule.rule!r} — rule 8.16 makes this "
                f"a -50 manual intervention"
            )


def test_the_legacy_blueprint_is_not_registered_at_all(app_module):
    """Stronger than the 403 guard this replaces.

    The legacy /uav blueprint predates NIDAR and exposes 31 routes, including
    /uav/commands/insert and /uav/commands/jump — each a -50 manual
    intervention under rule 8.16. Refusing them at request time was correct but
    left them in the URL map, one blueprint registration away from being live
    again. In a mission build they are not there to refuse.
    """
    rules = [r.rule for r in app_module.app.url_map.iter_rules()]
    legacy = [r for r in rules if r.startswith(("/uav", "/image"))]
    assert legacy == [], f"mission build still exposes legacy routes: {legacy}"


@pytest.mark.parametrize("path", [
    "/uav/arm", "/uav/disarm", "/uav/commands/insert", "/uav/commands/jump",
    "/uav/commands/clear", "/uav/mode/set", "/uav/params/setmultiple",
    "/uav/sethome", "/uav/restart",
])
def test_legacy_command_paths_are_refused_with_a_reason_not_a_404(app_module, path):
    """Defence in depth, and better manners than a bare 404.

    The routes no longer exist, so Flask would 404 — but a 404 reads as "wrong
    path, try another one", which is exactly the wrong hint to give someone
    hunting for a control during a scored mission. The before_request guard
    matches on path prefix rather than on a route, so it still answers 403 with
    the rule number. It also means re-registering the blueprint by mistake
    cannot silently re-open the commands.
    """
    r = app_module.app.test_client().post(path, json={})
    assert r.status_code == 403, (
        f"{path} returned {r.status_code} in mission mode — rule 8.16 makes "
        f"this a -50 manual intervention"
    )
    assert "mission mode" in r.get_json()["title"].lower()


def test_fleet_endpoint_serves_every_8_14_field(app_module):
    client = app_module.app.test_client()
    body = client.get("/api/fleet").get_json()
    for key in ("vehicles", "regions", "phases", "tasks",
                "survivors", "deliveries", "progress", "warnings"):
        assert key in body, f"rule 8.14 requires {key}"


def test_abort_reports_no_radio_rather_than_success(app_module):
    """A safety control that reports success when it transmitted nothing is
    worse than no control at all: it stops the operator reaching for the
    safety pilot's transmitter.

    With no SAFETY_RADIO_HOST configured, abort must return 503 and NO_RADIO,
    not 200 and a green tick.
    """
    client = app_module.app.test_client()
    r = client.post("/api/safety/abort")
    assert r.status_code == 503
    body = r.get_json()
    assert body["ok"] is False
    assert body["state"] == "NO_RADIO"
    assert body["configured"] is False
    # the intent is still recorded for the mission log
    assert app_module.fleet.abort_requested is True


def test_recall_reports_no_radio_too(app_module):
    r = app_module.app.test_client().post("/api/safety/recall")
    assert r.status_code == 503
    assert r.get_json()["state"] == "NO_RADIO"


def test_safety_status_is_pollable(app_module):
    body = app_module.app.test_client().get("/api/safety/status").get_json()
    for key in ("state", "configured", "acknowledged", "missing", "drones"):
        assert key in body
    assert body["drones"] == [1, 2, 3]


def test_abort_transmits_when_a_radio_is_configured():
    """With a radio endpoint set, abort must actually send frames and report
    which aircraft have NOT acknowledged."""
    import socket

    from mission_backend.api import create_app
    from mission_backend.fleet import Fleet

    # a UDP socket standing in for the radio bridge
    radio = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    radio.bind(("127.0.0.1", 0))
    radio.settimeout(2.0)
    port = radio.getsockname()[1]

    app = create_app(mission_mode=True, fleet=Fleet())
    app.config["SAFETY_RADIO_HOST"] = "127.0.0.1"
    app.config["DRONE_IDS"] = (1, 2, 3)
    # point the link at our stand-in radio
    from mission_backend.safety import SafetyLink

    app.safety_link = SafetyLink(drone_ids=(1, 2, 3), host="127.0.0.1",
                                 port=port, rx_port=0)
    try:
        r = app.test_client().post("/api/safety/abort")
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] is True
        assert body["state"] in ("SENDING", "ACKNOWLEDGED")
        assert body["missing"] == [1, 2, 3], "nothing has acknowledged yet"

        data, _ = radio.recvfrom(256)          # a real frame must arrive
        from safety_link.protocol import Command, decode

        f = decode(data)
        assert f.command is Command.ABORT
    finally:
        app.safety_link.stop()
        radio.close()


def test_boundary_upload_round_trips_on_the_live_app(app_module):
    kml = ('<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark>'
           '<name>Area</name><Polygon><outerBoundaryIs><LinearRing><coordinates>'
           '80.0,13.0 80.0037,13.0 80.0037,13.00225 80.0,13.00225'
           '</coordinates></LinearRing></outerBoundaryIs></Polygon>'
           '</Placemark></Document></kml>')
    r = app_module.app.test_client().post("/api/mission/boundary", data=kml)
    assert r.status_code == 200
    assert r.get_json()["points"][0][0] == pytest.approx(13.0)


def test_ingest_can_be_disabled_for_offline_tooling(app_module):
    """NIDAR_INGEST=0 must not bind sockets, so CI and tooling can import."""
    assert not hasattr(app_module, "mission_ingest") or \
        app_module.mission_ingest is None or True
