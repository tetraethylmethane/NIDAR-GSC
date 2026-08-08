#!/usr/bin/env bash
# Gazebo Harmonic + ardupilot_gazebo, for the ONE thing SITL cannot do:
# render a camera.
#
# WHY
# SITL gives real flight dynamics, the real EKF and the real failsafe logic,
# and scripts/sim-flight.sh already flies the coverage plan on three of them.
# But SITL has no world and no sensor imagery, so the perception half of the
# mission -- detection, geotagging, and the mission-state feed that carries
# survivors to the GCS -- has nothing to run against. Survivors have only ever
# come from sim_mission.py.
#
# WHAT IT WILL BE GOOD FOR
# Plumbing: does a detection become a geotag, does the geotag reach the GCS,
# does a delivery get assigned, does the chain hold together for eight minutes.
# Plumbing is what breaks.
#
# WHAT IT WILL NOT BE GOOD FOR
# RECALL. Synthetic humanoids on a synthetic flood plane flatter a detector
# badly, and recall is 250 points. Measure that on real imagery and real
# dummies. A simulator that inflates recall is worse than no simulator.
#
# RUN IT FROM AN INTERACTIVE WSL TERMINAL -- it needs sudo and will prompt for
# your password:
#
#     wsl -d Ubuntu
#     cd /mnt/c/path/to/NIDAR-GSC
#     ./scripts/install-gazebo.sh
#
# Safe to re-run; every step checks before acting.
set -euo pipefail

AP="${ARDUPILOT:-$HOME/ardupilot}"
PLUGIN_DIR="${ARDUPILOT_GAZEBO:-$HOME/ardupilot_gazebo}"

command -v sudo >/dev/null || { echo "sudo not available"; exit 2; }
if ! sudo -v; then
  echo "sudo authentication failed -- run this from an interactive terminal"
  exit 2
fi

# ---------------------------------------------------------------- gazebo
if command -v gz >/dev/null 2>&1; then
  echo "=== gazebo already installed: $(gz sim --versions 2>/dev/null | head -1) ==="
else
  echo "=== installing Gazebo Harmonic (this is a large download) ==="
  sudo apt-get update -qq
  sudo apt-get install -y lsb-release gnupg curl

  if [ ! -f /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg ]; then
    curl -sSL https://packages.osrfoundation.org/gazebo.gpg \
      | sudo tee /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg > /dev/null
  fi
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] http://packages.osrfoundation.org/gazebo/ubuntu-stable $(lsb_release -cs) main" \
    | sudo tee /etc/apt/sources.list.d/gazebo-stable.list > /dev/null
  sudo apt-get update -qq
  sudo apt-get install -y gz-harmonic
fi

echo "=== build dependencies ==="
sudo apt-get install -y cmake build-essential libgz-sim8-dev rapidjson-dev \
    libopencv-dev git

# ------------------------------------------------------------ GPU access
# WSL exposes the GPU at /dev/dri/renderD128, owned root:render mode 660.
# Ubuntu puts you in `video` by default but NOT in `render`, so Gazebo cannot
# open it and silently falls back to software rendering:
#
#     libEGL warning: failed to open /dev/dri/renderD128: Permission denied
#     libEGL warning: NEEDS EXTENSION: falling back to kms_swrast
#
# That is not just slow, it BREAKS THE FLIGHT. Measured real-time factor on
# swrast is 0.31, so SITL's JSON sensor packets arrive at a third of the rate
# the EKF needs, the estimate never converges, and the aircraft refuses to arm
# with no obvious clue as to why. Chased that for a while before reading the
# EGL warning properly.
if [ -e /dev/dri/renderD128 ] && ! id -nG | grep -qw render; then
  echo "adding $USER to the 'render' group for GPU access"
  sudo usermod -aG render "$USER"
  echo
  echo "  *** RESTART WSL FOR THIS TO TAKE EFFECT ***"
  echo "  From Windows PowerShell:   wsl --shutdown"
  echo "  Then reopen the terminal and check:"
  echo "      gz sim -s -r -v1 iris_runway.sdf &   # no 'kms_swrast' warning"
  echo
  NEEDS_RESTART=1
else
  echo "GPU access: $( [ -e /dev/dri/renderD128 ] && echo 'render group OK' || echo 'no /dev/dri/renderD128 -- software rendering only' )"
fi

# ------------------------------------------------------- ardupilot_gazebo
echo "=== ardupilot_gazebo plugin ==="
if [ ! -d "$PLUGIN_DIR" ]; then
  git clone --depth 1 https://github.com/ArduPilot/ardupilot_gazebo "$PLUGIN_DIR"
fi
mkdir -p "$PLUGIN_DIR/build"
cd "$PLUGIN_DIR/build"
cmake .. -DCMAKE_BUILD_TYPE=RelWithDebInfo
make -j"$(nproc)"
ls -la "$PLUGIN_DIR/build"/*.so

# ------------------------------------------------------------ environment
# Guarded, so re-running does not stack duplicate exports in .bashrc.
if ! grep -q 'ardupilot_gazebo' "$HOME/.bashrc" 2>/dev/null; then
  cat >> "$HOME/.bashrc" <<EOF

# ardupilot_gazebo (added by NIDAR-GSC scripts/install-gazebo.sh)
export GZ_SIM_SYSTEM_PLUGIN_PATH=$PLUGIN_DIR/build:\${GZ_SIM_SYSTEM_PLUGIN_PATH:-}
export GZ_SIM_RESOURCE_PATH=$PLUGIN_DIR/models:$PLUGIN_DIR/worlds:\${GZ_SIM_RESOURCE_PATH:-}
EOF
  echo "added GZ_SIM_* exports to ~/.bashrc"
else
  echo "~/.bashrc already has the GZ_SIM_* exports"
fi

[ -x "$AP/build/sitl/bin/arducopter" ] \
  && echo "SITL binary present: $AP/build/sitl/bin/arducopter" \
  || echo "NOTE: SITL not built yet -- cd $AP && ./waf configure --board sitl && ./waf copter"

cat <<'EOF'

GAZEBO_INSTALL_OK

If you were just added to the 'render' group, run `wsl --shutdown` from Windows
PowerShell FIRST and reopen the terminal. Without GPU access the real-time
factor is ~0.31 and SITL will not arm.

Then, in a NEW terminal so the exports are loaded:

    gz sim -s -r -v2 iris_runway.sdf &     # headless; drop -s for a window

    ~/ardupilot/build/sitl/bin/arducopter -M JSON \
        --home -35.363262,149.165237,584,353 \
        --serial0 udpclient:127.0.0.1:14550

Check it is healthy before anything else:

    gz topic -e -t /stats -n 1 | grep real_time_factor    # want ~1.0, not 0.3
    grep 'No JSON sensor' ~/…/sitl.log                    # want NOTHING

The -M JSON model replaces SITL's internal physics with the Gazebo model over
the plugin's UDP 9002/9003 link. Everything above it -- EKF, modes, failsafes,
mission logic -- is the same firmware that flew the coverage plan.

The camera is already there:

    gz topic -l | grep image

Once the aircraft flies in Gazebo, that topic is what finally gives the
detection -> geotag -> mission-state -> GCS chain real pixels to run on.
Measure PLUMBING with it. Do not measure recall: synthetic humanoids flatter a
detector, and recall is 250 points.
EOF
