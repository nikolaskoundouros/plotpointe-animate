#!/bin/bash
# Runs ON the 3D System box, as nick, AFTER `workbench up`. One live Blender session:
#   box_run.sh <minutes> <first shot> [vulkan|opengl]
# 1. copies this folder (the tools and every earlier saved copy) and the built navy scenes to the cloud machine
# 2. starts the live Blender there (pod_start.sh) and waits until it ends
# 3. meanwhile, once a minute, copies the animator's saved copies back into /Users/nick/plotpointe-live/saves
# 4. copies them back one last time when Blender has ended
# If $HERE/key exists (one line, the session key), the model's door in the live Blender is opened with it.
# It reads the built scenes and never writes to them or to anything else on the box.
set -uo pipefail
MINUTES="${1:-60}"; FIRST="${2:-dock}"; BACKEND="${3:-vulkan}"
HERE=/Users/nick/plotpointe-live
WB=/Users/nick/Desktop/render-desk/bin/workbench
SCENES=/Users/nick/Desktop/aow-modules/navy_preview/work
mkdir -p "$HERE/saves"

"$WB" push "$HERE" || { echo "BOX could not copy the tools to the machine"; exit 21; }
"$WB" push "$SCENES" || { echo "BOX could not copy the scenes to the machine"; exit 22; }

( while sleep 60; do "$WB" pull "$HERE/saves/" "$HERE/saves" >/dev/null 2>&1; done ) &
LOOP=$!
"$WB" run "PP_BACKEND=$BACKEND bash $HERE/tools/pod_start.sh $MINUTES $HERE/saves $HERE/tools/shots.json $FIRST $HERE/key"
kill "$LOOP" 2>/dev/null
"$WB" pull "$HERE/saves/" "$HERE/saves" && echo "BOX saved copies are in $HERE/saves: $(find "$HERE/saves" -name '*_v[0-9][0-9][0-9].blend' | wc -l) files"
