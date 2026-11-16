#!/bin/bash
# Copies the animator's saved copies and the chat from the cloud machine to this Mac (project saves/), then on to the
# box (/Users/nick/plotpointe-live/saves), the durable place. Run from the Mac; reads the machine's address from
# POD_HOST and POD_PORT (set by the session). The direct line from the Mac to the machine is the fast one.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
: "${POD_HOST:?}"; : "${POD_PORT:?}"
SSH="ssh -p $POD_PORT -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o BatchMode=yes"
rsync -az -e "$SSH" "root@$POD_HOST:/Users/nick/plotpointe-live/saves/" saves/ && echo "machine -> Mac: $(find saves -name '*_v[0-9][0-9][0-9].blend' | wc -l) saved copies"
rsync -az -e "ssh -o BatchMode=yes" saves/ root@37.27.148.115:/Users/nick/plotpointe-live/saves/ && echo "Mac -> box done"
