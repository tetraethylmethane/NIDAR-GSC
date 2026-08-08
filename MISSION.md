# NIDAR Mission Build — what changed and why

This ground station began as Team Sammpaati's AUVSI SUAS ground station. That
lineage is why several defaults were wrong for NIDAR: different rules, different
scoring, different prohibitions. This file records what was changed for
NIDAR 2026–27 Mission 1 and, more importantly, **what must not be changed back**.

Full engineering context lives in the systems repo:
`Drikr-NIDAR/ground-station/` — [`README.md`](../Drikr-NIDAR/ground-station/README.md)
and [`PLAN.md`](../Drikr-NIDAR/ground-station/PLAN.md).

---

## 1. The internet poller is gone — do not bring it back

`client/src/components/FlightMap.js` used to run:

```js
fetch("https://g.co", { mode: "no-cors" }).then(() => {
    tileRef.current.setUrl("https://server.arcgisonline.com/...")
})
useInterval(5000, checkInternet)
```

It probed the internet every five seconds and switched to online ArcGIS tiles
whenever connectivity existed.

- **Rule 8.4** prohibits internet connectivity during mission execution outright.
- **Rule 8.17** prohibits relying on any external network.
- **Rule 8.6** gives the jury the right to inspect source configuration.
- **Mission Brief §5** makes use of an external network interface "a violation or
  manual/external intervention".

Tiles now always come from `/map/{z}/{x}/{y}.png`, populated ahead of time by
`server/utils/slippy_map_getter.py`.

> **Operational note.** The mission area is not known until the KML arrives
> *during* the 5-minute setup window, so tiles must be pre-cached for a generous
> region around the venue **weeks in advance** — not for the search box on the
> day.

```bash
cd server
python utils/slippy_map_getter.py --center LAT,LON --radius-km 10 --zoom 10-18 --dry-run
python utils/slippy_map_getter.py --center LAT,LON --radius-km 10 --zoom 10-16 --yes
python utils/slippy_map_getter.py --verify     # run this again on the morning
```

The getter had a defect that would have surfaced at the worst possible moment:
it wrote the response body to a `.png` **without ever looking at it**, so a 404
page or a rate-limit body landed on disk as a plausible tile — and because the
resume check was `os.path.isfile`, it was skipped forever after. The cache would
have reported complete, errored never, and rendered grey squares on mission day.
Every tile is now checked by magic number before it is written, `--verify`
re-checks what is already cached, and an **empty** cache directory fails
verification rather than passing (the directory is created by the download
itself, so "it exists" proves nothing).

One trap worth knowing: ArcGIS answers a `.png` request with **JPEG** data.
Validating a PNG signature specifically — the obvious way to write the check —
rejects every real tile and caches nothing at all, which is a worse failure than
the one being fixed because it is silent and total.

`scripts/check-no-network.sh` fails the build if an outbound call reappears in
`client/src`. It does not scan `server/utils/slippy_map_getter.py`, which is the
one place in the repo that is *supposed* to touch the internet — weeks before
the competition, never during it.

## 2. Mission mode — the SYS-20 split

`server/app.py` now reads `MISSION_MODE` (default `1`, fail-safe):

| | `MISSION_MODE=1` competition | `MISSION_MODE=0` flight test |
|---|---|---|
| Telemetry, map, video, mission state | ✔ | ✔ |
| Abort / recall | ✔ *(8.19 requires these)* | ✔ |
| Arm, mode change, waypoint insert, servo, params | **module never imported** | ✔ |

Rule **8.16** treats a manual waypoint change, flight-path correction or payload
command during the mission as manual intervention at **−50 points each**. The
capability is not illegal — *using* it is — but `FlightMap.js` inserts a waypoint
on a **map click**, and the operator watches that map for eight minutes under
competition pressure. One stray click is −50, more than the entire
fast-completion bonus.

The split is **structural, not a feature flag**: `mission_backend.dev_commands`
is imported inside a branch, so in mission mode the module is never loaded and
there is no route to reach. A flag can be flipped by a config file; an unimported
module cannot.

`server/mission_tests/test_sys20.py` asserts this against the live Flask URL map.
**Run it before every competition build.**

## 3. Multi-vehicle mission layer

The original server held one vehicle object. NIDAR needs three drones on one
interface — **rule 8.13, worth 50 binary points**, with multi-drone collaborative
execution a further 50.

`server/mission_backend/` adds:

| Module | Purpose |
|---|---|
| `fleet.py` | Per-drone vehicle + mission state; survivor dedup; delivery status; consolidated progress (rule 8.14) |
| `kml.py` | KML boundary parsing (SYS-38) |
| `api.py` | Read-only mission routes + abort/recall |
| `dev_commands.py` | Flight-test commands, mission mode never loads it |

Two data paths, deliberately separate:

- **MAVLink** via mavlink-router, SYSID 1/2/3 → position, mode, battery, health.
- **Mission state**, 5 Hz JSON over the mesh → region, task, detections,
  deliveries. There is no sensible MAVLink message for *"survivor at lat/lon,
  confidence 0.87, confirmed by 3 frames"*, and bending `NAMED_VALUE_FLOAT` into
  that shape is a trap.

**Survivor dedup prefers fix quality over recency.** Two aircraft can see the
same survivor; the tag displayed — and aimed at — must be the *best* observation,
because a later `RTK_FLOAT` tag is metres worse than an earlier `RTK_FIXED` one.
Ranking is fix → frames → confidence. Confidence is last deliberately: it is
worth nothing in position terms.

## 4. Video: three feeds, H.264, WebRTC

Rule **8.14** requires a live camera feed from **each** drone. `VideoFeed.js`
served one MJPEG stream; three MJPEG feeds at 480p15 would cost 4.5–6 Mbps and
break the 2.5 Mbps link budget the RF design rests on.

`client/src/components/VideoWall.js` renders three WebRTC panes from MediaMTX
(`scripts/mediamtx.yml`).

**H.264, not H.265.** The RF budget assumed H.265 at 0.60 Mbps per feed, but
browser H.265 support is patchy and hardware-dependent — it may not render on the
day. H.264 at ~0.9 Mbps each gives 3.4 Mbps total, about **24 % utilisation at
MCS3**, still well inside the margin strategy.

**ICE servers are deliberately empty** in both the MediaMTX config and the client.
The defaults include public STUN servers, which would be an outbound internet
call during the mission. Everything is same-subnet over the mesh, so host
candidates suffice.

---

## 5. The legacy layer is not loaded in a mission build

Splitting the new blueprint was **not enough on its own.** The legacy `/uav`
blueprint predates NIDAR and exposes 31 routes, including
`/uav/commands/insert`, `/uav/commands/jump`, `/uav/arm`, `/uav/mode/set` and
`/uav/params/set` — precisely the −50 actions under rule 8.16. They were still
reachable in a mission build. A 403 guard was added first; that was found by the
smoke test, not by review.

**The routes are now gone entirely.** In mission mode `app.py` does not import
`apps.uav`, `apps.image` or `groundstation`, so the blueprint is never
registered and `app.gs` is `None`. Refusing a command is good; not having one is
better.

This also fixed something worse. That import chain is
`apps.uav` → `handlers/uav.py` → `dronekit`, and DroneKit does
`collections.MutableMapping`, which moved to `collections.abc` in **Python
3.10** — so *the mission server could not start on any current interpreter at
all.* The smoke test had been installing a fake `dronekit` module to get around
it, which meant the tests passed on 3.12 while the real program did not run on
3.12: a green tick over a server nobody could boot.

Pinning Python 3.9 would have been the wrong fix. In a mission build the legacy
`UAVHandler` is **redundant** — `mavlink_ingest.py` already carries position,
mode, battery and GNSS fix for all three aircraft over pymavlink, which DroneKit
cannot do at all, being single-vehicle by construction. Nothing is stubbed in
the smoke test any more, and `test_dronekit_is_not_in_the_mission_process`
asserts `"dronekit" not in sys.modules` after importing `app.py`. Absence is a
fact about the running process; "we do not call it" is only a claim about
intent.

The 403 guard stays as defence in depth. It matches on path prefix rather than
on a route, so a legacy path answers 403-with-a-reason instead of a bare 404 —
a 404 reads as *"wrong path, try another"*, the worst hint to give someone
hunting for a control mid-mission — and re-registering the blueprint by mistake
cannot silently reopen the commands.

> **Known limitation, recorded rather than hidden.** The **dev** build
> (`MISSION_MODE=0`) still needs DroneKit and therefore still needs Python 3.9;
> `mission_backend/dev_commands.py` is a route stub that acknowledges commands
> without sending them. This is tolerable because the dev build is not the
> scored artefact and QGroundControl does bring-up better anyway. `app.py`
> catches the import failure and explains all of this instead of raising a
> traceback about `MutableMapping`.

## 5a. The dev UI does not render in a mission build

`Servo`, `FlightPlanToolbar`, `Main` and the `Params` page still shipped in the
mission build. The server refused them, so no rule was broken — that is not the
argument. **A control that silently does nothing is its own hazard:** under
pressure someone clicks *Write To*, sees no error, and believes the aircraft
took it. The same reasoning removed waypoint insertion from the map.

In a mission build the left column is **mission status and abort, and nothing
else**. The `Params` page refuses to render and says why, because `/params` is
a URL and browsers remember URLs. The client learns the mode from
`mission_mode` on the `/api/fleet` snapshot, which defaults to **true** in every
path — before the first poll returns, after the backend goes away, and when the
field is missing — so only an explicit `false` unlocks anything.

## 6. Abort and recall are wired — but the radio is not

`/api/safety/abort` no longer sets a flag and returns a green tick. It now
transmits framed, sequenced commands through `safety_link/protocol.py` and
collects per-aircraft acknowledgements, and `AbortPanel.js` shows **which**
aircraft accepted. On a lossy 868 MHz link "abort sent" and "abort received" are
different claims, and only the second one means an aircraft is coming home.

**With no radio configured the endpoint returns 503 and `NO_RADIO`, not 200.**
The panel renders a red *NOT IMPLEMENTED* banner telling the operator to use the
safety pilot's transmitter. A green tick over a dead radio is worse than no
button at all, because it stops someone reaching for the one thing that works.

Set `safety_radio_host` in `config.json` when the radio bridge exists.

Two further safeguards in the UI:

- **Two-step arm-then-confirm**, with the arm lapsing after five seconds. These
  are the buttons an operator reaches for under pressure, and a misclick during
  a nominal mission ends it.
- **This is the secondary path.** The primary is the safety receiver driving
  `RC7_OPTION=4` (RTL) straight into the flight controller, which works with a
  hung companion — and a hung companion is a reason to abort.

## 7. Proving it works without aircraft

```bash
python scripts/sim_mission.py --speed 8   # 3 drones, 6 survivors, deliveries
./scripts/sim-video.sh                    # 3 H.264 feeds through MediaMTX
```

`sim_mission.py` deliberately includes the awkward cases: drone 2 drops off the
mesh mid-search, survivor 3 is tagged `RTK_FLOAT` then re-tagged `RTK_FIXED` by
a different drone (dedup must prefer the better fix, not the newer report), and
survivor 6 is tagged with a 3D fix only, which must raise a visible warning —
that is a ~100-point problem and has to be obvious while there is still time to
re-acquire.

Verified end to end: 5287 datagrams, 0 rejected, 6 survivors, correct dedup.

## Before every competition build

```bash
cd server && MISSION_MODE=1 python -m pytest mission_tests -q   # 107 tests
python utils/slippy_map_getter.py --verify                      # tiles intact
./scripts/check-no-network.sh                                   # no outbound calls
```

Then confirm, with the machine's network interfaces **physically down**:

1. Map tiles render from the local cache
2. Three video panes connect over the mesh
3. `/api/fleet` returns all three drones
4. Abort and recall respond
5. No route exists that can insert a waypoint
6. No dev control is on screen — no tab bar, no Params link
