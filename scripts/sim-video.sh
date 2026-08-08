#!/usr/bin/env bash
# Three synthetic video feeds through MediaMTX — the video half of the P2 gate.
#
# Proves rule 8.14 item 2 ("live camera feed from EACH drone") works before the
# first real flight rather than at it. Pair with scripts/sim_mission.py, which
# drives the map and mission state.
#
#   ./scripts/sim-video.sh            # 3 test patterns at 480p15 H.264
#   ./scripts/sim-video.sh 10.0.0.5   # against a GCS on the mesh
#
# Requires: mediamtx on PATH (or ./mediamtx) and gstreamer1.0-plugins-{base,good,ugly}.
# On the aircraft the videotestsrc below is replaced by the camera source; the
# encoder and sink stay identical.
set -uo pipefail
HOST="${1:-127.0.0.1}"
cd "$(dirname "$0")/.." || exit 2

command -v gst-launch-1.0 >/dev/null || { echo "gst-launch-1.0 not found"; exit 1; }

MTX=""
command -v mediamtx >/dev/null && MTX="mediamtx"
[ -x ./mediamtx ] && MTX="./mediamtx"
if [ -z "$MTX" ]; then
  echo "mediamtx not found. Download from github.com/bluenviron/mediamtx/releases"
  echo "and place the binary here or on PATH."
  exit 1
fi

pids=()
cleanup() { echo; echo "stopping..."; for p in "${pids[@]}"; do kill "$p" 2>/dev/null; done; }
trap cleanup EXIT INT TERM

echo "starting mediamtx with scripts/mediamtx.yml"
"$MTX" scripts/mediamtx.yml & pids+=($!)
sleep 2

# 480p15 H.264 at ~900 kbps each. Three of these is 2.7 Mbps of video; with
# 0.7 Mbps of telemetry and detection metadata that is 3.4 Mbps total, about
# 24 % utilisation at MCS3 -- inside the link budget's margin strategy.
for i in 1 2 3; do
  echo "publishing drone$i -> rtsp://$HOST:8554/drone$i"
  gst-launch-1.0 -q \
    videotestsrc pattern=$((i - 1)) is-live=true \
    ! video/x-raw,width=640,height=480,framerate=15/1 \
    ! timeoverlay text="DRONE $i" halignment=left valignment=top font-desc="Sans 20" \
    ! videoconvert \
    ! x264enc bitrate=900 speed-preset=ultrafast tune=zerolatency key-int-max=15 \
    ! h264parse ! rtspclientsink location="rtsp://$HOST:8554/drone$i" \
    & pids+=($!)
done

sleep 3
echo
echo "Three feeds publishing. Open the ground station and confirm:"
echo "  1. all three panes show LIVE, not OFFLINE"
echo "  2. each pane is a different test pattern -- not the same feed three times"
echo "  3. the timestamps advance (frames are flowing, not one stuck keyframe)"
echo "  4. killing one publisher shows that pane reconnecting, and it recovers"
echo
echo "WebRTC directly: http://$HOST:8889/drone1"
echo "Ctrl-C to stop."
wait
