import json
import logging
import os
import os.path
import traceback

from flask import Flask, jsonify, send_file, Response
from flask_cors import CORS

from apps import uav, image
from groundstation import GroundStation
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

app.register_blueprint(uav, url_prefix="/uav")
app.register_blueprint(image, url_prefix="/image")

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

# The legacy /uav blueprint predates NIDAR and exposes 31 routes, including
# /uav/commands/insert, /uav/commands/jump, /uav/arm, /uav/mode/set and
# /uav/params/set -- precisely the actions rule 8.16 treats as manual
# intervention at -50 points each. Splitting the new mission blueprint was not
# enough on its own; these were still reachable in a mission build.
#
# They are kept registered because the legacy pages read telemetry through
# /uav/quick and /uav/stats, but in mission mode every state-changing method is
# refused before the view function runs. Verified by
# mission_tests/test_app_smoke.py against the live URL map.
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

gs: GroundStation = GroundStation(config=config)
app.gs = gs
app.gs_config = config


@app.errorhandler(Exception)
def handle_error(e: Exception) -> tuple[Response, int]:
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
