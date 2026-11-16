"""The quick lane: reads the animator's chat lines and carries them out with the ready-made tools in the live Blender
(tools/live/pp_live.py), without the big assistant. Runs on the Mac, through the tunnel.

    router.py [seconds]      run until a line needs the big assistant (then print it and stop), or the time is up

For each new line:
  1. at once: the chat shows the model is working (a few tenths of a second)
  2. a plain command ("stop", "undo", "show the bones", ...) is carried out right away, no model at all
  3. anything else goes to a small Claude (Haiku, 4 to 5 seconds measured on 13 Nov 2026) together with the list of
     tools and the objects in the scene; it chooses tools and their arguments, never writes Blender code
  4. every chosen tool and argument is checked here before it is sent, and again inside Blender
  5. a line no tool can do (colours, new objects, animation, questions) is handed to the big assistant: the chat says
     so, this script prints the line and stops, which wakes the big assistant

PP_API       the live Blender's door (default http://127.0.0.1:8577)
PP_KEY_FILE  the file holding the session key
PP_READ_FILE the number of the last chat line already read; shared with model.py so the big assistant is never asked
             to look at a line the router already took
"""
import functools
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

print = functools.partial(print, flush=True)       # so a log file shows each line as it happens
API = os.environ.get("PP_API", "http://127.0.0.1:8577")
SMALL_MODEL = "haiku"
ASK_TIMEOUT = 45
NEUTRAL = Path("/private/tmp")                     # the small model runs from a folder with no project instructions in it
JSON_ONLY = "You choose tools for a 3D animation program. Reply with one JSON object and nothing else: no code, no notes."


# ---- pure parts: no network, tested in checks/check_page.py ----
def norm(text):
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


SHORTCUTS = {
    "stop": ([("play", {"on": False})], "Stopped."),
    "stop it": ([("play", {"on": False})], "Stopped."),
    "pause": ([("play", {"on": False})], "Stopped."),
    "play": ([("play", {"on": True})], "Playing."),
    "play it": ([("play", {"on": True})], "Playing."),
    "undo": ([("undo", {})], "Undone."),
    "undo that": ([("undo", {})], "Undone."),
    "show the bones": ([("bones", {"show": True})], "Bones shown."),
    "show bones": ([("bones", {"show": True})], "Bones shown."),
    "hide the bones": ([("bones", {"show": False})], "Bones hidden."),
    "hide bones": ([("bones", {"show": False})], "Bones hidden."),
    "full shot": ([("camera_view", {})], "Back on the shot's camera."),
    "camera view": ([("camera_view", {})], "Back on the shot's camera."),
    "go back": ([("camera_view", {})], "Back on the shot's camera."),
    "zoom in on his face": ([("face", {})], "Zoomed to his face."),
    "zoom to his face": ([("face", {})], "Zoomed to his face."),
    "look at his face": ([("face", {})], "Zoomed to his face."),
    "face": ([("face", {})], "Zoomed to his face."),
}


def shortcut(text):
    """A plain command that needs no model: (calls, reply) or None."""
    return SHORTCUTS.get(norm(text))


def _number(args, key, low, high, default=0.0):
    value = args.get(key, default)
    if isinstance(value, str):                     # the small model sometimes writes "-1" instead of -1
        try:
            value = float(value)
        except ValueError:
            raise ValueError(f"{key} is not a number") from None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} is not a number")
    if not low <= value <= high:
        raise ValueError(f"{key} must be between {low} and {high}")
    return value


def check_call(tool, args, tools, objects, frames):
    """Check one tool call the model chose; return the arguments to send, or raise ValueError."""
    if tool not in tools:
        raise ValueError(f"no such tool: {tool}")
    if not isinstance(args, dict):
        raise ValueError("arguments must be an object")
    names = {o[0] for o in objects}
    if tool in ("face", "camera_view", "undo"):
        return {}
    if tool in ("bones", "play"):
        key = "show" if tool == "bones" else "on"
        value = args.get(key, "toggle")
        if value not in (True, False, "toggle"):
            raise ValueError(f"{key} must be true, false or toggle")
        return {key: value}
    if tool == "focus":
        picked = args.get("objects")
        if not isinstance(picked, list) or not picked or not all(n in names for n in picked):
            raise ValueError("focus needs names of objects that are in this shot")
        return {"objects": picked}
    if tool == "frame":
        return {"n": int(_number(args, "n", frames[0], frames[1], frames[0]))}
    if tool == "shading":
        if args.get("mode") not in ("material", "solid", "wire"):
            raise ValueError("mode must be material, solid or wire")
        return {"mode": args["mode"]}
    if args.get("object") not in names:
        raise ValueError(f"{tool} needs the name of an object in this shot")
    if tool == "scale":
        return {"object": args["object"], "factor": _number(args, "factor", 0.05, 20, 1.0)}
    limit = 50 if tool == "move" else 720
    return {"object": args["object"], **{k: _number(args, k, -limit, limit) for k in "xyz"}}


def parse_plan(raw, tools, objects, frames):
    """The small model's answer -> ("calls", [(tool, args)], reply) or ("handoff", reason)."""
    start, end = raw.find("{"), raw.rfind("}")
    try:
        plan = json.loads(raw[start:end + 1])
    except ValueError:
        return "handoff", "the quick model did not give a usable answer"
    if not isinstance(plan, dict):
        return "handoff", "the quick model did not give a usable answer"
    if plan.get("handoff"):
        return "handoff", str(plan["handoff"])[:160]
    if isinstance(plan.get("answer"), str) and plan["answer"].strip():          # a question the scene facts answer
        return "calls", [], plan["answer"].strip()[:240]
    calls = plan.get("calls")
    if not isinstance(calls, list) or not calls or len(calls) > 4:
        return "handoff", "no ready-made tool fits"
    checked = []
    try:
        for c in calls:
            checked.append((c["tool"], check_call(c["tool"], c.get("args", {}), tools, objects, frames)))
    except (KeyError, TypeError, ValueError) as exc:
        return "handoff", f"I could not match that to a tool ({exc})"
    reply = str(plan.get("say") or "Done.").strip()[:240]
    return "calls", checked, reply


def prompt_for(line, history, status):
    scene = status.get("scene") or {}
    tools = "\n".join(f'- {t["name"]}: {t["does"]}. args: {json.dumps(t["args"])}' for t in status.get("tools", []))
    objects = "\n".join(f"{n} ({t}){' <- ' + p if p else ''}" for n, t, p in scene.get("objects", [])[:120])
    chat = "\n".join(f'{"animator" if m["who"] == "you" else "assistant"}: {m["text"][:200]}' for m in history[-4:])
    return f"""You are the quick assistant inside a 3D animation tool (Blender). The animator typed one instruction. Carry it out with the ready-made tools below, or say it needs the big assistant.

Tools:
{tools}

Right now: shot "{status.get("shot")}", frame {scene.get("frame")} of {scene.get("range")}, playing: {scene.get("playing")}, bones shown: {scene.get("bones")}, view: {scene.get("view")}.
Objects in this shot (name, type, parent):
{objects}

Recent chat:
{chat}

Rules:
- Use only tool names from the list and only object names from the list.
- To move or turn a whole character, use its ARMATURE object (the rig), not a single body part.
- Positions: x is right, y is away from the camera, z is up, in metres. Rotation is in degrees. Write numbers as JSON numbers (-1, not "-1").
- Only act when a tool does exactly what was asked. If it asks to change how something looks (colours, materials, details), to add, remove or build something, to animate, or is a question, reply with a handoff.

Reply with JSON only, no other text:
{{"say": "<one short plain sentence telling the animator what you did>", "calls": [{{"tool": "<name>", "args": {{...}}}}]}}
or, for a plain question about the facts above (frame, bones, view, what is in the shot):
{{"answer": "<the answer in one short sentence>"}}
or, when no tool does it:
{{"handoff": "<one short reason>"}}

The animator's instruction: {json.dumps(line)}"""


# ---- the live parts ----
def key():
    return Path(os.environ["PP_KEY_FILE"]).read_text().strip()


def get(path):
    with urllib.request.urlopen(API + path, timeout=15) as r:
        return json.loads(r.read())


def post(path, text="", timeout=45):
    req = urllib.request.Request(API + path, data=text.encode(), method="POST", headers={"X-PP-Key": key(), "Content-Type": "text/plain"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def say(text):
    post("/reply", text, timeout=15)


def working(step):
    post("/working?step=" + urllib.parse.quote(step), "", timeout=15)


def run_tool(name, args):
    return post(f"/tool?name={name}", json.dumps(args), timeout=40)


def ask_small(prompt):
    out = subprocess.run(["claude", "-p", "--model", SMALL_MODEL, "--safe-mode", "--tools", "", "--no-session-persistence",
                          "--system-prompt", JSON_ONLY, prompt], capture_output=True, text=True, timeout=ASK_TIMEOUT, cwd=NEUTRAL)
    return out.stdout


def read_marker():
    path = Path(os.environ["PP_READ_FILE"])
    return int(path.read_text()) if path.exists() else None


def write_marker(n):
    Path(os.environ["PP_READ_FILE"]).write_text(str(n))


def handle(line, status):
    """Carry out one chat line. Returns True when it was done here, False when it goes to the big assistant."""
    t0 = time.time()
    try:
        working("Reading your message")
    except (urllib.error.URLError, OSError):
        pass
    short = shortcut(line["text"])
    if short:
        calls, reply = short
        route = "plain command"
    else:
        tools = {t["name"] for t in status.get("tools", [])}
        scene = status.get("scene") or {}
        try:
            raw = ask_small(prompt_for(line["text"], status.get("chat", []), status))
        except (subprocess.TimeoutExpired, OSError):
            raw = ""
        plan = parse_plan(raw, tools, scene.get("objects", []), scene.get("range", [1, 240]))
        route = "small model"
        if plan[0] == "handoff":
            say(f"This needs the big assistant ({plan[1]}). It is picking it up now, usually one to two minutes.")
            print(f"[{time.strftime('%H:%M:%S')}] handed over after {time.time() - t0:.1f} s: {plan[1]}")
            return False
        calls, reply = plan[1], plan[2]
    for name, args in calls:
        result = run_tool(name, args)
        if not result.get("ok"):
            say(f"I could not do that: {result.get('error')}")
            print(f"[{time.strftime('%H:%M:%S')}] {route}: {name} failed: {result.get('error')}")
            return True
    say(reply)
    print(f"[{time.strftime('%H:%M:%S')}] {route}: {[c[0] for c in calls]} done in {time.time() - t0:.1f} s: {reply}")
    return True


def main():
    end = time.time() + float(sys.argv[1] if len(sys.argv) > 1 else 3000)
    status = get("/status")
    seen = read_marker()
    if seen is None:                               # first run: only lines written from now on
        seen = max([m["id"] for m in status["chat"] if m["who"] == "you"] or [0])
        write_marker(seen)
    print(f"[{time.strftime('%H:%M:%S')}] quick lane listening (after chat line {seen})", flush=True)
    while time.time() < end:
        try:
            status = get("/status")
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(2)
            continue
        if time.time() > status["until"]:
            print("the live Blender has stopped")
            return 4
        new = [m for m in status["chat"] if m["who"] == "you" and m["id"] > (read_marker() or 0)]
        for line in new[:1]:                       # one at a time, in order
            write_marker(line["id"])
            if not handle(line, status):
                print("THE ANIMATOR WROTE (needs the big assistant):")
                print(f"[{time.strftime('%H:%M:%S', time.localtime(line['at']))}] on the {line['shot']} shot (saved copy {line['copy']}): {line['text']}")
                return 0
        time.sleep(0.4)
    print("nobody wrote in the chat")
    return 5


if __name__ == "__main__":
    sys.exit(main())
