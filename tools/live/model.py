"""The model's side of the live Blender (run on the Mac, through the tunnel). Four commands:

  model.py wait [seconds]        wait until the animator writes in the chat, print what they wrote, and stop
  model.py step "<name>" FILE.py [OBJECTS]
                                 run one build step in the live Blender; the name shows in the chat while it runs.
                                 OBJECTS (names, comma separated) are what the step works on: the view glides to
                                 them and a ring with the step's name marks them, then the view glides back
  model.py working "<name>"      show a "working" line in the chat with that name, at once
  model.py say "<text>"          answer in the chat (this also ends the "working" line there)
  model.py look                  what is open, what was saved last, the last chat lines

A step is refused (exit 3) when the animator has written something the model has not read yet, so a "stop" or a
correction always reaches the model before its next step.

PP_API       the live Blender's door (default http://127.0.0.1:8577)
PP_KEY_FILE  the file holding the session key
PP_READ_FILE where the number of the last chat line the model has read is kept
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = os.environ.get("PP_API", "http://127.0.0.1:8577")
KEY = Path(os.environ["PP_KEY_FILE"]).read_text().strip()
READ = Path(os.environ["PP_READ_FILE"])


def get(path):
    with urllib.request.urlopen(API + path, timeout=20) as r:
        return json.loads(r.read())


def post(path, text, timeout=620):
    req = urllib.request.Request(API + path, data=text.encode(), method="POST", headers={"X-PP-Key": KEY, "Content-Type": "text/plain"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def unread(status):
    """The animator's chat lines the model has not read yet; reading them marks them read."""
    seen = int(READ.read_text()) if READ.exists() else 0
    new = [m for m in status.get("chat", []) if m["who"] == "you" and m["id"] > seen]
    if new:
        READ.write_text(str(new[-1]["id"]))
    return new


def show(lines):
    for m in lines:
        print(f"[{time.strftime('%H:%M:%S', time.localtime(m['at']))}] on the {m['shot']} shot (saved copy {m['copy']}): {m['text']}")


def main():
    cmd = sys.argv[1]
    if cmd == "wait":
        end = time.time() + float(sys.argv[2] if len(sys.argv) > 2 else 3300)
        while time.time() < end:
            try:
                status = get("/status")
            except (urllib.error.URLError, OSError, ValueError):
                time.sleep(3)
                continue
            new = unread(status)
            if new:
                print("THE ANIMATOR WROTE:")
                show(new)
                return 0
            if time.time() > status["until"]:
                print("the live Blender has stopped")
                return 4
            time.sleep(2)
        print("nobody wrote in the chat")
        return 5
    if cmd == "step":
        new = unread(get("/status"))
        if new:
            print("NOT RUN. The animator wrote this first; read it before the next step:")
            show(new)
            return 3
        focus = "&focus=" + urllib.parse.quote(sys.argv[4]) if len(sys.argv) > 4 else ""
        answer = post("/run?step=" + urllib.parse.quote(sys.argv[2]) + focus, Path(sys.argv[3]).read_text())
        print(answer.get("out", ""), end="")
        if answer.get("error"):
            print("STEP FAILED:\n" + answer["error"])
            return 1
        return 0
    if cmd == "say":
        post("/reply", sys.argv[2], timeout=20)
        return 0
    if cmd == "working":                           # say what the model is doing, before a slow step or a restart
        post("/working?step=" + urllib.parse.quote(sys.argv[2]), "", timeout=20)
        return 0
    if cmd == "look":
        s = get("/status")
        print({k: s[k] for k in ("shot", "from", "count", "last", "model", "error")})
        show(s.get("chat", [])[-6:])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
