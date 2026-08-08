"""Ingest tests — real pymavlink messages, real UDP sockets, no mocks.

The point of these is that every field mapping is exercised against messages
built by pymavlink itself, so a wrong scale factor or a wrong enum value fails
here rather than on the flight line.
"""
import json
import os
import socket
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mission_backend.fleet import Fleet  # noqa: E402
from mission_backend.mission_ingest import (  # noqa: E402
    MissionIngest, MissionIngestStats, handle_datagram, send,
)

mavutil = pytest.importorskip("pymavlink.mavutil", reason="pymavlink missing")
from mission_backend.mavlink_ingest import GPS_FIX_TYPE, handle_message  # noqa: E402


@pytest.fixture
def mav():
    """A MAVLink2 encoder we can build genuine messages with."""
    f = mavutil.mavlink.MAVLink(None)
    f.srcSystem = 1
    f.srcComponent = 1
    return f


def as_from(msg, sysid):
    """Round-trip a message so get_srcSystem() reflects the sending vehicle."""
    m = mavutil.mavlink.MAVLink(None)
    m.srcSystem = sysid
    m.srcComponent = 1
    data = msg.pack(m)
    parser = mavutil.mavlink.MAVLink(None)
    parser.robust_parsing = True
    out = parser.parse_char(data)
    assert out is not None, "message did not round-trip"
    return out


# ------------------------------------------------------------------ MAVLink
def test_global_position_scales_correctly(mav):
    f = Fleet()
    msg = as_from(mavutil.mavlink.MAVLink_global_position_int_message(
        time_boot_ms=1000, lat=130123456, lon=800654321,
        alt=45000, relative_alt=40000, vx=0, vy=0, vz=0, hdg=9000), 2)
    assert handle_message(f, msg)
    v = f.vehicles[2]
    assert v.lat == pytest.approx(13.0123456)
    assert v.lon == pytest.approx(80.0654321)
    assert v.alt_m == pytest.approx(40.0), "relative_alt is mm and is AGL"
    assert v.heading_deg == pytest.approx(90.0)


def test_heading_unknown_sentinel_is_not_654_degrees(mav):
    """hdg == 65535 means unknown. Naively dividing gives 655.35 deg."""
    f = Fleet()
    msg = as_from(mavutil.mavlink.MAVLink_global_position_int_message(
        time_boot_ms=1, lat=0, lon=0, alt=0, relative_alt=0,
        vx=0, vy=0, vz=0, hdg=65535), 1)
    handle_message(f, msg)
    assert f.vehicles[1].heading_deg is None


@pytest.mark.parametrize("fix_type,expected", [
    (0, "NONE"), (1, "NONE"), (2, "2D"), (3, "3D"),
    (4, "DGPS"), (5, "RTK_FLOAT"), (6, "RTK_FIXED"),
])
def test_gps_fix_type_mapping(fix_type, expected):
    """RTK_FLOAT vs RTK_FIXED is worth ~20 delivery points; no RTK ~100.
    Fleet.survivors() ranks on this string, so the enum must be exact."""
    f = Fleet()
    msg = as_from(mavutil.mavlink.MAVLink_gps_raw_int_message(
        time_usec=0, fix_type=fix_type, lat=0, lon=0, alt=0,
        eph=100, epv=100, vel=0, cog=0, satellites_visible=14), 3)
    assert handle_message(f, msg)
    assert f.vehicles[3].gnss_fix == expected
    assert f.vehicles[3].satellites == 14


def test_gps_fix_constants_match_pymavlink():
    """Guard against the MAVLink enum drifting away from our table."""
    assert GPS_FIX_TYPE[mavutil.mavlink.GPS_FIX_TYPE_RTK_FIXED] == "RTK_FIXED"
    assert GPS_FIX_TYPE[mavutil.mavlink.GPS_FIX_TYPE_RTK_FLOAT] == "RTK_FLOAT"
    assert GPS_FIX_TYPE[mavutil.mavlink.GPS_FIX_TYPE_3D_FIX] == "3D"


def test_heartbeat_sets_mode_and_armed():
    f = Fleet()
    armed = as_from(mavutil.mavlink.MAVLink_heartbeat_message(
        type=2, autopilot=3, base_mode=128 | 64, custom_mode=3,
        system_status=4, mavlink_version=3), 1)
    assert handle_message(f, armed)
    assert f.vehicles[1].armed is True
    assert f.vehicles[1].mode == "AUTO"

    disarmed = as_from(mavutil.mavlink.MAVLink_heartbeat_message(
        type=2, autopilot=3, base_mode=64, custom_mode=6,
        system_status=3, mavlink_version=3), 1)
    handle_message(f, disarmed)
    assert f.vehicles[1].armed is False
    assert f.vehicles[1].mode == "RTL"


def test_gcs_heartbeat_is_ignored():
    """The GCS hears its own heartbeat. It must not become a fourth drone."""
    f = Fleet()
    msg = as_from(mavutil.mavlink.MAVLink_heartbeat_message(
        type=6, autopilot=8, base_mode=0, custom_mode=0,
        system_status=4, mavlink_version=3), 255)
    assert handle_message(f, msg) is False
    assert 255 not in f.vehicles


def test_sys_status_battery_and_unknown_sentinels():
    f = Fleet()
    ok = as_from(mavutil.mavlink.MAVLink_sys_status_message(
        onboard_control_sensors_present=0, onboard_control_sensors_enabled=0,
        onboard_control_sensors_health=0, load=250, voltage_battery=22200,
        current_battery=1500, battery_remaining=73, drop_rate_comm=0,
        errors_comm=0, errors_count1=0, errors_count2=0, errors_count3=0,
        errors_count4=0), 2)
    handle_message(f, ok)
    assert f.vehicles[2].battery_pct == 73
    assert f.vehicles[2].battery_v == pytest.approx(22.2)

    unknown = as_from(mavutil.mavlink.MAVLink_sys_status_message(
        onboard_control_sensors_present=0, onboard_control_sensors_enabled=0,
        onboard_control_sensors_health=0, load=0, voltage_battery=0,
        current_battery=-1, battery_remaining=-1, drop_rate_comm=0,
        errors_comm=0, errors_count1=0, errors_count2=0, errors_count3=0,
        errors_count4=0), 2)
    handle_message(f, unknown)
    assert f.vehicles[2].battery_pct is None, "-1 means unknown, not 'flat'"


def test_three_sysids_populate_three_drones():
    """Rule 8.13, 50 binary points: all drones through one interface."""
    f = Fleet()
    for sysid in (1, 2, 3):
        handle_message(f, as_from(
            mavutil.mavlink.MAVLink_global_position_int_message(
                time_boot_ms=1, lat=int((13.0 + sysid) * 1e7), lon=800000000,
                alt=0, relative_alt=40000, vx=0, vy=0, vz=0, hdg=0), sysid))
    assert {1, 2, 3} <= set(f.vehicles)
    assert f.vehicles[1].lat != f.vehicles[3].lat


def test_unknown_message_type_is_ignored_not_fatal():
    f = Fleet()
    msg = as_from(mavutil.mavlink.MAVLink_attitude_message(
        time_boot_ms=1, roll=0.1, pitch=0.0, yaw=1.5,
        rollspeed=0, pitchspeed=0, yawspeed=0), 1)
    assert handle_message(f, msg) is False       # ignored, no exception


def test_vfr_hud_groundspeed():
    f = Fleet()
    msg = as_from(mavutil.mavlink.MAVLink_vfr_hud_message(
        airspeed=9.1, groundspeed=8.0, heading=90, throttle=50,
        alt=40.0, climb=0.0), 2)
    assert handle_message(f, msg)
    assert f.vehicles[2].groundspeed_ms == pytest.approx(8.0)


# ------------------------------------------------------------- mission state
def doc(drone=1, **kw):
    d = {"drone": drone, "t": time.time(), "state": "SEARCH",
         "region": [[13.0, 80.0], [13.0, 80.1], [13.1, 80.1]],
         "task": {"type": "SEARCH"}, "detections": [], "deliveries": []}
    d.update(kw)
    return d


def test_valid_datagram_accepted():
    f, st = Fleet(), MissionIngestStats()
    assert handle_datagram(f, json.dumps(doc(2)).encode(), st)
    assert st.accepted == 1 and st.rejected == 0
    assert f.mission[2].phase == "SEARCH"
    assert len(f.mission[2].region) == 3


@pytest.mark.parametrize("payload", [
    b"", b"not json", b"{", b'"a string"', b"[1,2,3]",
    b'{"no_drone": 1}', b'{"drone": "abc"}', b'{"drone": 0}',
    b'{"drone": 999}', b"\xff\xfe\x00binary",
    b'{"drone": 1, "detections": [{"id": "x"}]}',
    b'{"drone": 1, "region": "not-a-list"}',
])
def test_malformed_datagrams_never_raise(payload):
    """A bad packet mid-mission must not take down the display that is the
    evidence for 250 points."""
    f, st = Fleet(), MissionIngestStats()
    assert handle_datagram(f, payload, st) is False
    assert st.rejected == 1
    assert st.last_error


def test_stale_datagram_rejected():
    """UDP reorders. An older document must not roll survivors backwards."""
    f, st = Fleet(), MissionIngestStats()
    handle_datagram(f, json.dumps(doc(1, t=1000.0, detections=[
        {"id": 1, "lat": 13, "lon": 80, "fix": "RTK_FIXED"}])).encode(), st)
    assert len(f.survivors()) == 1
    assert handle_datagram(f, json.dumps(doc(1, t=999.0, detections=[])).encode(), st) is False
    assert len(f.survivors()) == 1, "stale packet erased a survivor"


def test_newer_datagram_accepted():
    f, st = Fleet(), MissionIngestStats()
    handle_datagram(f, json.dumps(doc(1, t=1000.0)).encode(), st)
    assert handle_datagram(f, json.dumps(doc(1, t=1001.0, state="DELIVER")).encode(), st)
    assert f.mission[1].phase == "DELIVER"


def test_end_to_end_over_a_real_socket():
    """Bind a real listener, send real datagrams from three drones."""
    f = Fleet()
    ing = MissionIngest(f, host="127.0.0.1", port=0)
    ing.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ing.sock.bind(("127.0.0.1", 0))
    port = ing.sock.getsockname()[1]
    ing.sock.settimeout(1.0)
    import threading
    ing._thread = threading.Thread(target=ing._loop, daemon=True)
    ing._thread.start()
    try:
        for d in (1, 2, 3):
            send(doc(d, detections=[
                {"id": d, "lat": 13.0, "lon": 80.0, "conf": 0.9,
                 "frames": 5, "fix": "RTK_FIXED"}]),
                host="127.0.0.1", port=port)
        deadline = time.time() + 3.0
        while time.time() < deadline and ing.stats.accepted < 3:
            time.sleep(0.02)
    finally:
        ing.stop()
    assert ing.stats.accepted == 3, f"stats: {ing.stats.accepted}"
    assert len(f.survivors()) == 3
    assert f.progress()["found"] == 3


def test_oversized_region_does_not_break_ingest():
    f, st = Fleet(), MissionIngestStats()
    big = [[13.0 + i * 1e-5, 80.0] for i in range(2000)]
    assert handle_datagram(f, json.dumps(doc(1, region=big)).encode(), st)
    assert len(f.mission[1].region) == 2000
