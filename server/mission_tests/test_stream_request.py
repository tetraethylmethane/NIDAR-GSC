"""Telemetry has to be REQUESTED — measured against a real autopilot.

These tests exist because of something no synthetic test could have found.
Against a real ArduCopter SITL over UDP:

    passive listener        HEARTBEAT only, 1 Hz. Nothing else.
    + GCS heartbeat         still HEARTBEAT only.
    + SET_MESSAGE_INTERVAL  everything, at the rates requested.

The ingest was a passive listener. On mission day the operator would have seen
flight mode and armed state and nothing else -- rule 8.14 items 3 and 4 blank,
and the survivor geotag fix quality, worth ~100 points, unknown.

The existing tests call handle_message() with constructed messages. That checks
the mapping and says nothing whatever about whether the messages ever arrive.

The second thing these lock down is what the GCS is ALLOWED to transmit. SYS-20
requires the mission build be incapable of originating a retask, waypoint change
or drop command. MAV_CMD_SET_MESSAGE_INTERVAL configures the telemetry stream
and cannot alter what the aircraft does -- but "the ingest sends MAVLink now" is
exactly the kind of change that invites a helpful addition later, so the test
below enumerates every transmission and fails on anything else.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mission_backend.fleet import Fleet  # noqa: E402
from mission_backend.mavlink_ingest import (  # noqa: E402
    MAV_CMD_SET_MESSAGE_INTERVAL, MAV_TYPE_GCS, REQUESTED_STREAMS, REREQUEST_S,
    MavlinkIngest, stream_requests,
)


class FakeMav:
    """Records every transmission the ingest makes."""

    def __init__(self):
        self.sent = []

    def heartbeat_send(self, mtype, autopilot, base, custom, status):
        self.sent.append(("HEARTBEAT", mtype))

    def command_long_send(self, target, comp, command, confirm, *params):
        self.sent.append(("COMMAND_LONG", target, comp, command, params))

    def __getattr__(self, name):
        # Any other *_send is a transmission we did not intend. Record it so
        # test_transmits_nothing_but_heartbeat_and_stream_requests catches it
        # rather than letting an AttributeError look like a passing test.
        def _catch_all(*a, **k):
            self.sent.append((name.upper(), a))
        if name.endswith("_send"):
            return _catch_all
        raise AttributeError(name)


class FakeConn:
    def __init__(self):
        self.mav = FakeMav()


def ingest_with(*sysids):
    f = Fleet(drone_ids=sysids or (1, 2, 3))
    ing = MavlinkIngest(f)
    ing.conn = FakeConn()
    return ing, f


# --------------------------------------------------------------- the request
def test_every_message_the_displays_need_is_requested():
    """Each of these maps to something rule 8.14 requires on screen."""
    ids = set(REQUESTED_STREAMS)
    assert 33 in ids, "GLOBAL_POSITION_INT — 8.14 item 3, drone position"
    assert 24 in ids, "GPS_RAW_INT — fix type, decides the geotag budget"
    assert 1 in ids, "SYS_STATUS — battery, 8.14 item 4"
    assert 74 in ids, "VFR_HUD — groundspeed"


def test_requests_are_addressed_per_aircraft_with_the_right_interval():
    reqs = stream_requests(2)
    assert {t for t, _, _ in reqs} == {2}, "must target one specific aircraft"
    by_id = {mid: us for _, mid, us in reqs}
    assert by_id[33] == 250_000      # 4 Hz
    assert by_id[24] == 500_000      # 2 Hz
    assert by_id[1] == 1_000_000     # 1 Hz


def test_a_request_goes_out_for_each_aircraft_we_can_see():
    ing, fleet = ingest_with(1, 2, 3)
    ing.tick(now=100.0)
    cmds = [s for s in ing.conn.mav.sent if s[0] == "COMMAND_LONG"]
    assert len(cmds) == 3 * len(REQUESTED_STREAMS)
    assert {c[1] for c in cmds} == {1, 2, 3}
    assert all(c[3] == MAV_CMD_SET_MESSAGE_INTERVAL for c in cmds)


def test_requests_stop_once_position_is_actually_flowing():
    """A healthy link must not carry repeat requests forever."""
    ing, fleet = ingest_with(1)
    ing.tick(now=100.0)
    first = ing.requests_sent
    assert first == len(REQUESTED_STREAMS)

    fleet.update_vehicle(1, lat=13.0, lon=80.0)      # telemetry arrived
    for t in range(101, 140):
        ing.tick(now=float(t))
    assert ing.requests_sent == first, "kept asking after telemetry arrived"


def test_it_asks_again_when_position_never_arrives():
    """Covers an autopilot that rebooted, a dropped request, and
    mavlink-router starting after us."""
    ing, _ = ingest_with(1)
    ing.tick(now=100.0)
    assert ing.requests_sent == len(REQUESTED_STREAMS)

    ing.tick(now=100.0 + REREQUEST_S - 1)            # too soon
    assert ing.requests_sent == len(REQUESTED_STREAMS)

    ing.tick(now=100.0 + REREQUEST_S + 0.1)          # now
    assert ing.requests_sent == 2 * len(REQUESTED_STREAMS)


def test_an_aircraft_that_appears_late_still_gets_asked():
    """mavlink-router may bring drone 3 up after the GCS started."""
    ing, fleet = ingest_with(1)
    ing.tick(now=100.0)
    fleet.update_vehicle(7, mode="AUTO")             # a new system id appears
    ing.tick(now=101.0)
    targets = {c[1] for c in ing.conn.mav.sent if c[0] == "COMMAND_LONG"}
    assert 7 in targets


def test_heartbeat_identifies_us_as_a_GCS():
    ing, _ = ingest_with(1)
    ing.tick(now=100.0)
    hb = [s for s in ing.conn.mav.sent if s[0] == "HEARTBEAT"]
    assert hb and hb[0][1] == MAV_TYPE_GCS


# ------------------------------------------------------------- SYS-20 guard
def test_transmits_nothing_but_heartbeat_and_stream_requests():
    """The ingest now transmits. This is the fence around that.

    Rule 8.16 charges -50 for a manual intervention. If a COMMAND_LONG other
    than SET_MESSAGE_INTERVAL ever leaves this module -- arm, set mode, a
    waypoint, a servo -- it fails here.
    """
    ing, fleet = ingest_with(1, 2, 3)
    for t in range(100, 160):
        ing.tick(now=float(t))
        if t == 120:
            fleet.update_vehicle(1, lat=13.0, lon=80.0)

    for s in ing.conn.mav.sent:
        kind = s[0]
        assert kind in ("HEARTBEAT", "COMMAND_LONG"), (
            f"the mission GCS transmitted {kind}, which is not a heartbeat or "
            f"a stream request"
        )
        if kind == "COMMAND_LONG":
            assert s[3] == MAV_CMD_SET_MESSAGE_INTERVAL, (
                f"the mission GCS sent MAV_CMD {s[3]} — rule 8.16 makes a "
                f"vehicle command a -50 manual intervention"
            )
            assert s[4][0] in REQUESTED_STREAMS, (
                f"requested an unlisted message id {s[4][0]}"
            )


def test_a_transmit_failure_does_not_take_the_ingest_down():
    """Losing the link must degrade the display, not kill the process."""
    ing, _ = ingest_with(1)

    def boom(*a, **k):
        raise OSError("network unreachable")

    ing.conn.mav.heartbeat_send = boom
    with pytest.raises(OSError):
        ing.tick(now=100.0)          # tick propagates; the LOOP swallows
    # the loop wrapper is what must survive, and it catches Exception
    import inspect
    src = inspect.getsource(MavlinkIngest._tx_loop)
    assert "except Exception" in src
