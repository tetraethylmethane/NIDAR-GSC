"""Tests for the fleet / mission-state model behind rule 8.14."""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mission_backend.fleet import Fleet, VehicleState  # noqa: E402


def doc(drone, **kw):
    d = {"drone": drone, "state": "SEARCH", "region": [], "task": {},
         "detections": [], "deliveries": []}
    d.update(kw)
    return d


def test_fleet_defaults_to_three_drones():
    f = Fleet()
    assert set(f.vehicles) == {1, 2, 3}
    assert f.progress()["drones_total"] == 3


def test_single_interface_merges_all_three_drones():
    """4D-4, 50 binary points: one interface, all drones."""
    f = Fleet()
    for i in (1, 2, 3):
        f.update_vehicle(i, lat=13.0 + i, lon=80.0, gnss_fix="RTK_FIXED", armed=True)
        f.update_mission(doc(i, region=[[13.0, 80.0], [13.0, 80.1], [13.1, 80.1]]))
    snap = f.snapshot()
    assert len(snap["vehicles"]) == 3
    assert len(snap["regions"]) == 3
    assert all(len(r) == 3 for r in snap["regions"].values())


def test_survivor_dedup_prefers_rtk_fixed_over_more_recent_float():
    """Two drones see the same survivor. The better FIX must win, not the newer
    report -- an RTK_FLOAT tag is metres worse than an RTK_FIXED one."""
    f = Fleet()
    f.update_mission(doc(1, detections=[
        {"id": 4, "lat": 13.0001, "lon": 80.0001, "conf": 0.70,
         "frames": 9, "fix": "RTK_FIXED"}]))
    f.update_mission(doc(2, detections=[
        {"id": 4, "lat": 13.0009, "lon": 80.0009, "conf": 0.99,
         "frames": 3, "fix": "RTK_FLOAT"}]))
    s = f.survivors()
    assert len(s) == 1, "the same survivor must not appear twice"
    assert s[4].fix == "RTK_FIXED"
    assert s[4].reported_by == 1
    assert s[4].lat == pytest.approx(13.0001)


def test_survivor_dedup_uses_frames_when_fix_is_equal():
    f = Fleet()
    f.update_mission(doc(1, detections=[
        {"id": 7, "lat": 13.0, "lon": 80.0, "conf": 0.9, "frames": 2, "fix": "RTK_FIXED"}]))
    f.update_mission(doc(2, detections=[
        {"id": 7, "lat": 13.5, "lon": 80.5, "conf": 0.5, "frames": 12, "fix": "RTK_FIXED"}]))
    assert f.survivors()[7].frames == 12


def test_delivery_status_takes_furthest_progressed():
    f = Fleet()
    f.update_mission(doc(1, deliveries=[{"survivor": 2, "state": "ASSIGNED"}]))
    f.update_mission(doc(3, deliveries=[{"survivor": 2, "state": "RELEASED"}]))
    assert f.deliveries()[2].state == "RELEASED"


def test_progress_counts_found_and_delivered():
    """8.14 item 8 — consolidated mission progress."""
    f = Fleet()
    f.started_at = time.time() - 132
    f.update_mission(doc(1, detections=[
        {"id": 1, "lat": 13, "lon": 80, "fix": "RTK_FIXED"},
        {"id": 2, "lat": 13, "lon": 80, "fix": "RTK_FIXED"}]))
    f.update_mission(doc(2,
        detections=[{"id": 3, "lat": 13, "lon": 80, "fix": "RTK_FIXED"}],
        deliveries=[{"survivor": 1, "state": "CONFIRMED"}]))
    p = f.progress()
    assert p["found"] == 3
    assert p["delivered"] == 1
    assert p["elapsed"] == "2:12"


def test_progress_tracks_the_fifteen_minute_bonus_window():
    """4D-5 is binary at 15 min. The operator must see the clock."""
    f = Fleet()
    f.started_at = time.time() - 600
    assert f.progress()["bonus_window_s"] == pytest.approx(300, abs=2)
    f.started_at = time.time() - 1000
    assert f.progress()["bonus_window_s"] == 0.0


def test_health_degrades_with_telemetry_age():
    v = VehicleState(drone_id=1)
    assert v.health == "OK"
    v.updated = time.time() - 5
    assert v.health == "STALE"
    v.updated = time.time() - 30
    assert v.health == "LOST"


def test_warns_when_armed_without_rtk():
    """Geotagging without RTK costs ~100 of the 200 delivery points."""
    f = Fleet()
    f.update_vehicle(2, armed=True, gnss_fix="3D")
    assert any("no RTK" in w for w in f.warnings())


def test_warns_when_a_survivor_was_tagged_without_rtk():
    f = Fleet()
    f.update_mission(doc(1, detections=[
        {"id": 5, "lat": 13, "lon": 80, "fix": "3D"}]))
    assert any("survivor 5" in w for w in f.warnings())


def test_no_spurious_warnings_when_healthy():
    f = Fleet()
    for i in (1, 2, 3):
        f.update_vehicle(i, armed=True, gnss_fix="RTK_FIXED", battery_pct=88)
    assert f.warnings() == []


def test_snapshot_covers_every_8_14_display():
    f = Fleet()
    for i in (1, 2, 3):
        f.update_vehicle(i, lat=13.0, lon=80.0, gnss_fix="RTK_FIXED")
        f.update_mission(doc(i, region=[[13.0, 80.0]], task={"type": "SEARCH"}))
    snap = f.snapshot()
    for key in ("vehicles", "regions", "phases", "tasks",
                "survivors", "deliveries", "progress", "warnings"):
        assert key in snap, f"8.14 requires {key}"


def test_unknown_drone_id_is_accepted_not_crashed():
    """A fourth SYSID appearing mid-mission must not take the GCS down."""
    f = Fleet()
    f.update_mission(doc(9, detections=[{"id": 1, "lat": 13, "lon": 80}]))
    assert 9 in f.mission
    assert f.progress()["found"] == 1
