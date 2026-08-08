import json
import logging
import os
import os.path
import traceback

from flask import Flask, jsonify, send_file, Response
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from utils.errors import (
    InvalidRequestError,
    InvalidStateError,
    GeneralError,
    ServiceUnavailableError,
)
from utils.logging_setup import ROLLING_LOGS
import sys

# Force UTF-8 on the console streams. Guarded because `reconfigure` only exists
# on a real TextIOWrapper: under pytest, gunicorn, or systemd without a tty,
# stdin/stdout are replaced and this raises AttributeError, taking the whole
# app down before Flask is even constructed.
for _stream in (sys.stdin, sys.stdout):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

log: logging.Logger = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

with open(os.path.join(os.getcwd(), "config.json"), "r", encoding="utf-8") as file:
    config: dict = json.load(file)

app: Flask = Flask(__name__)
app.config["JSONIFY_PRETTYPRINT_REGULAR"] = True
CORS(app)

# ---------------------------------------------------------------------------
# NIDAR mission layer.
#
# MISSION_MODE controls the SYS-20 split. In mission mode the vehicle-command
# blueprint is never imported, so there is no route capable of a retask,
# waypoint change or drop command -- the actions rule 8.16 penalises at -50
# each. Abort and recall remain in both builds, because 8.19 requires them.
#
# This is structural, not a feature flag: `mission_backend.dev_commands` is
# imported inside a branch, so in mission mode the module is never loaded at
# all. server/mission_tests/test_sys20.py asserts this against the live URL map.
#
#   MISSION_MODE=1  competition build   (default -- fail safe)
#   MISSION_MODE=0  flight-test build   (arm, mode change, manual waypoints)
# ---------------------------------------------------------------------------
MISSION_MODE: bool = os.environ.get("MISSION_MODE", "1") != "0"

# ---------------------------------------------------------------------------
# The legacy layer -- and why a mission build does not load it at all.
#
# `apps.uav` -> `handlers` -> `handlers/uav.py` -> `dronekit`. DroneKit is
# unmaintained and does `collections.MutableMapping`, which moved to
# `collections.abc` in Python 3.10, so on any current interpreter that import
# chain raises before Flask is even constructed. The mission server simply
# could not start.
#
# Pinning Python 3.9 would "fix" it, and would be the wrong fix. In a mission
# build the legacy UAVHandler is REDUNDANT: mavlink_ingest.py already carries
# position, mode, battery and GNSS fix for all three aircraft over pymavlink,
# which DroneKit cannot do at all (it is single-vehicle by construction). So
# the mission build does not import it, and DroneKit is absent from the process
# rather than merely unused. mission_tests/test_app_smoke.py asserts
# `"dronekit" not in sys.modules` after importing this file.
#
# It also settles SYS-20 more strongly than the 403 guard below did. That
# blueprint exposed 31 routes including /uav/commands/insert, /uav/commands/jump,
# /uav/arm, /uav/mode/set and /uav/params/set -- precisely the actions rule 8.16
# treats as manual intervention at -50 each. Refusing them is good; not having
# them is better.
# ---------------------------------------------------------------------------
#
# KNOWN LIMITATION, recorded rather than hidden: the DEV build still needs
# DroneKit, so MISSION_MODE=0 still requires Python 3.9. mission_backend/
# dev_commands.py is a route stub that acknowledges commands without sending
# them, so the real arm/mode/waypoint capability is still the legacy handler.
# That is tolerable because the dev build is not the scored artefact and
# QGroundControl or Mission Planner does the same job better during bring-up.
# It is NOT tolerable to discover it from a traceback about MutableMapping, so
# the failure is caught and explained below.
# ---------------------------------------------------------------------------
if not MISSION_MODE:
    try:
        from apps import uav, image                   # noqa: E402
        from groundstation import GroundStation       # noqa: E402
    except Exception as exc:  # pragma: no cover - depends on interpreter
        raise SystemExit(
            f"\nThe DEV build (MISSION_MODE=0) could not load the legacy "
            f"DroneKit layer:\n    {type(exc).__name__}: {exc}\n\n"
            f"DroneKit is unmaintained and cannot be imported on Python "
            f">= 3.10 (collections.MutableMapping). Options:\n"
            f"  - Run the MISSION build instead:  MISSION_MODE=1 python app.py\n"
            f"    It does not use DroneKit and runs on any current Python.\n"
            f"  - For aircraft bring-up, use QGroundControl or Mission Planner\n"
            f"    against mavlink-router (scripts/mavlink-router.conf).\n"
            f"  - Only if you really need these legacy pages: Python 3.9.\n"
        ) from exc

    app.register_blueprint(uav, url_prefix="/uav")
    app.register_blueprint(image, url_prefix="/image")

# Defence in depth. The routes are gone in a mission build, so this normally has
# nothing to refuse -- but a 403 saying WHY is a better answer than a bare 404,
# which invites someone to go looking for the path that still works. It also
# means re-registering the blueprint by mistake cannot silently re-open them.
_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


@app.before_request
def _block_legacy_commands():
    from flask import request as _req

    if not MISSION_MODE:
        return None
    if _req.method in _MUTATING and _req.path.startswith(("/uav", "/image")):
        logging.getLogger("groundstation").error(
            "BLOCKED %s %s in MISSION_MODE -- rule 8.16 manual intervention",
            _req.method, _req.path,
        )
        return (
            jsonify({
                "title": "Blocked in mission mode",
                "message": (
                    "Vehicle commands are disabled in a mission build. "
                    "Rule 8.16 treats a waypoint change, flight-path "
                    "correction or payload command during the mission as "
                    "manual intervention (-50 points). Set MISSION_MODE=0 "
                    "for flight testing."
                ),
                "path": _req.path,
            }),
            403,
        )
    return None


from mission_backend.fleet import Fleet  # noqa: E402
from mission_backend.api import safety, view  # noqa: E402

fleet: Fleet = Fleet(drone_ids=config.get("drones", [1, 2, 3]))
app.fleet = fleet
app.config["MISSION_MODE"] = MISSION_MODE
app.config["DRONE_IDS"] = tuple(config.get("drones", [1, 2, 3]))
# Endpoint of the 868 MHz safety radio bridge. Absent -> the abort UI shows
# NO RADIO instead of a green tick, which is the honest state.
app.config["SAFETY_RADIO_HOST"] = config.get("safety_radio_host")

app.register_blueprint(view)
app.register_blueprint(safety)

if not MISSION_MODE:
    from mission_backend.dev_commands import commands  # noqa: E402

    app.register_blueprint(commands)
    logging.getLogger("groundstation").warning(
        "MISSION_MODE=0 -- vehicle command routes are ENABLED. "
        "This build must not be used for the Final Mission."
    )


@app.before_request
def _attach_fleet() -> None:
    from flask import request

    request.app_fleet = fleet  # type: ignore[attr-defined]


# --- telemetry and mission-state ingest -------------------------------------
# Two separate paths, deliberately (see Drikr-NIDAR ground-station/PLAN.md 2.1):
#
#   MAVLink        via mavlink-router, SYSID 1/2/3 -> position, mode, battery.
#                  Uses pymavlink directly rather than DroneKit: DroneKit is
#                  unmaintained, single-vehicle, and broken on Python >= 3.10
#                  (collections.MutableMapping moved to collections.abc).
#   Mission state  5 Hz JSON over the mesh -> region, task, detections,
#                  deliveries. MAVLink has no message for "survivor at lat/lon,
#                  confidence 0.87, confirmed by 3 frames".
#
# Both are started unless NIDAR_INGEST=0, so tests and offline tooling can
# import app.py without opening sockets.
if os.environ.get("NIDAR_INGEST", "1") != "0":
    from mission_backend.mavlink_ingest import MavlinkIngest  # noqa: E402
    from mission_backend.mission_ingest import MissionIngest  # noqa: E402

    mavlink_ingest = MavlinkIngest(
        fleet, endpoint=config.get("mavlink_endpoint", "udpin:0.0.0.0:14550")
    )
    mission_ingest = MissionIngest(
        fleet, port=int(config.get("mission_state_port", 14660))
    )
    app.mavlink_ingest = mavlink_ingest
    app.mission_ingest = mission_ingest
    try:
        mavlink_ingest.start()
        mission_ingest.start()
    except Exception:  # pragma: no cover - never let ingest kill the GCS
        logging.getLogger("groundstation").exception(
            "ingest failed to start; the GCS will run without live telemetry"
        )

logger: logging.Logger = logging.getLogger("groundstation")

# The legacy GroundStation opens a DroneKit link to ONE aircraft and spawns a
# polling thread for it. In a mission build there is nothing for it to do -- the
# fleet has three aircraft and they arrive over mavlink_ingest -- so it is not
# constructed, and `app.gs` stays None. Anything that reaches for it in mission
# mode is a bug in the caller, and should fail loudly rather than be papered
# over with a stub that returns plausible-looking zeros.
gs = None
if not MISSION_MODE:
    gs = GroundStation(config=config)
app.gs = gs
app.gs_config = config


@app.errorhandler(Exception)
def handle_error(e: Exception) -> tuple[Response, int]:
    # HTTPException is werkzeug telling us the status it already decided --
    # 404 for a route that does not exist, 405 for a wrong method. Catching
    # Exception swallowed those and reported 500, so every missing route looked
    # like a crashed server. That mattered here: in a mission build the legacy
    # /uav routes are deliberately absent, and the browser check found a page
    # still requesting one and getting "500 INTERNAL SERVER ERROR" back.
    #
    # A 500 says "the ground station is broken". A 404 says "that is not a
    # thing here". During a scored mission, with a jury entitled to inspect,
    # the difference is worth having.
    if isinstance(e, HTTPException):
        return (
            jsonify({
                "title": e.name,
                "message": e.description,
                "exception": type(e).__name__,
            }),
            e.code or 500,
        )
    logger.error(type(e).__name__)
    logger.info("Traceback of %s : ", type(e).__name__, exc_info=e)
    return (
        jsonify(
            {
                "title": "Unhandled Server Error",
                "message": str(e),
                "exception": type(e).__name__,
                "traceback": traceback.format_tb(e.__traceback__),
            }
        ),
        500,
    )


@app.errorhandler(InvalidRequestError)
def handle_400(e: InvalidRequestError) -> tuple[Response, int]:
    logger.error(type(e).__name__)
    logger.info("Traceback of %s : ", type(e).__name__, exc_info=e)
    return (
        jsonify(
            {
                "title": "Invalid Request",
                "message": str(e),
                "exception": type(e).__name__,
                "traceback": traceback.format_tb(e.__traceback__),
            }
        ),
        400,
    )


@app.errorhandler(InvalidStateError)
def handle_409(e: InvalidStateError) -> tuple[Response, int]:
    logger.error(type(e).__name__)
    logger.info("Traceback of %s : ", type(e).__name__, exc_info=e)
    return (
        jsonify(
            {
                "title": "Invalid State Error",
                "message": str(e),
                "exception": type(e).__name__,
                "traceback": traceback.format_tb(e.__traceback__),
            }
        ),
        409,
    )


@app.errorhandler(GeneralError)
def handle_500(e: GeneralError) -> tuple[Response, int]:
    logger.error(type(e).__name__)
    logger.info("Traceback of %s : ", type(e).__name__, exc_info=e)
    return (
        jsonify(
            {
                "title": "Server Error",
                "message": str(e),
                "exception": type(e).__name__,
                "traceback": traceback.format_tb(e.__traceback__),
            }
        ),
        500,
    )


@app.errorhandler(ServiceUnavailableError)
def handle_503(e: ServiceUnavailableError) -> tuple[Response, int]:
    logger.error(type(e).__name__)
    logger.info("Traceback of %s : ", type(e).__name__, exc_info=e)
    return (
        jsonify(
            {
                "title": "Service Unavailable Error",
                "message": str(e),
                "exception": type(e).__name__,
                "traceback": traceback.format_tb(e.__traceback__),
            }
        ),
        503,
    )


@app.route("/")
def index() -> str:
    return "Ground Station Backend "


@app.route("/log/<string:type_>")
def create_log(type_: str) -> str:
    if type_ == "debug":
        logger.debug("This is for debugging")
    elif type_ == "info":
        logger.info("This is info")
    elif type_ == "warning":
        logger.warning("This is a warning")
    elif type_ == "important":
        logger.important("This is important")  # type: ignore[attr-defined]
    elif type_ == "error":
        logger.error("This is an error")
    elif type_ == "critical":
        logger.critical("This is critical")
    else:
        pass
    return ""


@app.route("/favicon.ico")
def favicon() -> str:
    return ""


@app.route("/rollinglogs")
def rollinglogs():
    return {"result": ROLLING_LOGS.getvalue()}


@app.route("/file/infolog")
def logfile() -> Response:
    return send_file(os.path.join(os.getcwd(), "logs", "info.log"))


@app.route("/file/debuglog")
def debuglogfile() -> Response:
    return send_file(os.path.join(os.getcwd(), "logs", "debug.log"))


@app.route("/file/telemlog")
def telemlogfile() -> Response:
    return send_file(os.path.join(os.getcwd(), "logs", "telem.log"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
