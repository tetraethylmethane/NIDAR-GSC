#!/usr/bin/env zsh
#
# ⚠ THIS FLIES A FIXED-WING AIRCRAFT. RescueSwarm is a quadrotor.
#
# Inherited from the ground station this repo started as. It launches
# `-v ArduPlane` with sim.parm, which is an airspeed-based plane configuration
# -- TRIM_ARSPD_CM, ARSPD_FBW_MIN/MAX, LAND_FLARE_SEC, NAVL1_PERIOD, RLL2SRV_*.
# None of it applies to a multirotor, and none of the project's own parameters
# in firmware/ardupilot-params/ are loaded, so every failsafe is at its stock
# default: BATT_FS_LOW_ACT = 0, no return-to-pad on low battery.
#
# scripts/README.md still points here, which means the documented way to run
# "the simulation" has been the wrong airframe with no failsafes.
#
# USE INSTEAD:
#   ./scripts/sim-flight.sh          three ArduCopter + GCS, project params
#   ./scripts/gz-flight.sh           one copter with Gazebo physics and camera
#   ./scripts/test-battery-failsafe.sh   proves low battery triggers RTL
#
# Kept because it is the only script wired to sim_locations.txt, and deleting
# it would lose that. Set NIDAR_ALLOW_PLANE_SIM=1 if you genuinely want a plane.
if [ "${NIDAR_ALLOW_PLANE_SIM:-0}" != "1" ]; then
  echo "run-sim.sh launches ArduPlane (fixed wing) with no project parameters."
  echo "RescueSwarm is a quadrotor. Use ./scripts/sim-flight.sh instead."
  echo "To run it anyway: NIDAR_ALLOW_PLANE_SIM=1 ./scripts/run-sim.sh"
  exit 2
fi

ARDUPILOT_DIRECTORY="$HOME"/ardupilot

SCRIPT_DIR=${0:a:h}

export PYENV_VERSION="3.10.11"
source "$HOME"/.zshrc  # to support pyenv

# Handle location input
location_input=""
vared -p "Enter location (leave blank for FARM_RC): " location_input
if [ "$location_input" = "" ]
then
    location_input="FARM_RC"
fi
cp "$SCRIPT_DIR"/sim_locations.txt "$ARDUPILOT_DIRECTORY"/Tools/autotest/locations.txt

pyenv exec python "$ARDUPILOT_DIRECTORY"/Tools/autotest/sim_vehicle.py --no-mavproxy -v ArduPlane --add-param-file "$SCRIPT_DIR"/sim.parm -L "$location_input"

wait
