#!/usr/bin/env bash
# Fail if the client can make an outbound INTERNET call during the mission.
#
# Rule 8.4 prohibits internet connectivity during mission execution; 8.6 lets the
# jury inspect source configuration. This ground station previously polled
# https://g.co every 5 seconds and switched to online ArcGIS tiles whenever
# connectivity existed. This script exists so that cannot come back unnoticed.
#
# Private/LAN addresses are ALLOWED: the GCS backend and the mesh are local, and
# rule 8.5 only prohibits EXTERNAL networks, not our own link.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2

fail=0

# Absolute http(s) URLs in client source, excluding: comments, CRA service
# worker boilerplate, template placeholders, XML namespaces, and RFC1918 /
# loopback addresses.
mapfile -t urls < <(
  grep -rnE 'https?://' client/src --include='*.js' --include='*.jsx' \
    | grep -v 'serviceWorker.js' \
    | grep -vE ':[0-9]+:[[:space:]]*(//|\*|/\*)' \
    | grep -vE 'localhost|127\.0\.0\.1|0\.0\.0\.0' \
    | grep -vE '10\.[0-9]+\.[0-9]+\.[0-9]+' \
    | grep -vE '192\.168\.[0-9]+\.[0-9]+' \
    | grep -vE '172\.(1[6-9]|2[0-9]|3[01])\.[0-9]+\.[0-9]+' \
    | grep -vE 'w3\.org|schema|\{' || true
)
if ((${#urls[@]})); then
  echo "OUTBOUND INTERNET URLS IN CLIENT SOURCE:"
  printf '  %s\n' "${urls[@]}"
  fail=1
fi

# Connectivity probes and ICE servers. 'turn:'/'stun:' only count as URL schemes
# -- quoted -- so "Turn Loiter" and icon-turn.png do not false-positive.
declare -A patterns=(
  ['g\.co']='connectivity probe'
  ['arcgisonline']='online tile server'
  ['navigator\.onLine']='connectivity probe'
  ['["'"'"']stun:']='public STUN server'
  ['["'"'"']turn:']='public TURN server'
)
for pat in "${!patterns[@]}"; do
  mapfile -t hits < <(
    grep -rnE "$pat" client/src --include='*.js' \
      | grep -vE ':[0-9]+:[[:space:]]*(//|\*|/\*)' || true
  )
  if ((${#hits[@]})); then
    echo "PROHIBITED (${patterns[$pat]}):"
    printf '  %s\n' "${hits[@]}"
    fail=1
  fi
done

if ((fail)); then
  echo
  echo "Rule 8.4 prohibits internet connectivity during mission execution."
  echo "Map tiles must come from /map/{z}/{x}/{y}.png (slippy_map_getter.py)."
  echo "WebRTC must use host ICE candidates only -- the mesh is same-subnet."
  exit 1
fi
echo "OK -- no outbound internet calls in client source."
