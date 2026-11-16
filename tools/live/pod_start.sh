#!/bin/bash
# Runs ON the cloud machine. Starts one real Blender with a screen, and a web page that shows that screen.
#   pod_start.sh <minutes> <save dir> <shots.json> <first shot> [key file]
# PP_BACKEND picks what draws Blender's screen: vulkan (default) draws on the graphics card, opengl falls back to
# the processor (slow). Checked 13 Nov 2026 on an RTX 4090 machine: vulkan = "NVIDIA GeForce RTX 4090", opengl = "llvmpipe".
# The key file holds the session key for the model's door (see pp_live.py); without it that door stays shut.
# The screen (port 6080) and Blender's own small web door (port 6081, see pp_live.py) are only reachable through an
# ssh tunnel; nothing is opened to the internet.
# Blender is killed after <minutes>, so this command ends and the machine then idles out and is destroyed by the
# workbench watchdog. $BLENDER is set by `workbench run`.
set -uo pipefail
MINUTES="${1:?minutes}"; SAVE="${2:?save dir}"; SHOTS="${3:?shots.json}"; FIRST="${4:?first shot}"; KEYFILE="${5:-}"
KEY=""; [ -n "$KEYFILE" ] && [ -f "$KEYFILE" ] && KEY="$(cat "$KEYFILE")"
HERE="$(cd "$(dirname "$0")" && pwd)"
: "${BLENDER:?BLENDER is not set}"
export DEBIAN_FRONTEND=noninteractive

if ! command -v Xtigervnc >/dev/null 2>&1 || ! command -v websockify >/dev/null 2>&1; then
  echo "LIVE installing the screen and the web viewer (Ubuntu packages)"
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends \
    tigervnc-standalone-server tigervnc-common novnc websockify openbox \
    libgl1-mesa-dri libglx-mesa0 libegl1 libegl-mesa0 mesa-utils \
    libxcursor1 libxrandr2 libxinerama1 libxkbcommon-x11-0 libice6 libsm6 dbus-x11 xfonts-base >/dev/null || { echo "LIVE install failed"; exit 11; }
fi

pkill -f "Xtigervnc :1" 2>/dev/null; pkill -f "websockify.*6080" 2>/dev/null; sleep 1
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
Xtigervnc :1 -geometry 1600x900 -depth 24 -rfbport 5901 -localhost yes -SecurityTypes None -AlwaysShared >/tmp/live_x.log 2>&1 &
sleep 2
export DISPLAY=:1
openbox >/tmp/live_wm.log 2>&1 &
cp "$HERE/viewer.html" /usr/share/novnc/pp.html      # the plain Blender screen the Animate page shows
websockify --web /usr/share/novnc 127.0.0.1:6080 127.0.0.1:5901 >/tmp/live_web.log 2>&1 &
sleep 1

# The first shot opens from the animator's latest saved copy if there is one, else from the built scene.
mkdir -p "$SAVE"
OPEN="$(ls "$SAVE/$FIRST/${FIRST}"_v[0-9][0-9][0-9].blend 2>/dev/null | sort | tail -1)"
[ -n "$OPEN" ] || OPEN="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$SHOTS" "$FIRST")"

echo "LIVE drawing with: ${PP_BACKEND:-vulkan}; card: $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo none)"
echo "LIVE cpu cores: $(nproc)"
echo "LIVE opening $OPEN for $MINUTES minutes, saving to $SAVE"
timeout "${MINUTES}m" "$BLENDER" --gpu-backend "${PP_BACKEND:-vulkan}" --window-geometry 0 0 1600 900 "$OPEN" --python "$HERE/pp_live.py" -- "$SHOTS" "$SAVE" 6081 "$MINUTES" "$FIRST" "$KEY" >/tmp/live_blender.log 2>&1
RC=$?
echo "LIVE blender ended rc=$RC"; grep -E "PP_LIVE|Error|Traceback" /tmp/live_blender.log | tail -8
pkill -f "websockify.*6080" 2>/dev/null; pkill -f "Xtigervnc :1" 2>/dev/null
exit 0
