"""Runs INSIDE the live Blender on the cloud machine:
    blender FIRST.blend --python pp_live.py -- SHOTS.json SAVE_DIR PORT MINUTES FIRST_SHOT

Two jobs.

1. Saving the animator's work. The built scene is never written to. When a shot is opened it is saved once as
   SAVE_DIR/<shot>/<shot>_work.blend and the animator works in that file. Every SAVE_EVERY seconds, if something
   changed, the work file is saved and a numbered copy is kept beside it: <shot>_v001.blend, _v002 ... with one line
   per copy in SAVE_DIR/log.tsv (time, shot, file, size, frame). The box copies SAVE_DIR back once a minute.

2. Opening a shot for the page. GET /open?shot=dock opens the animator's latest saved copy of that shot, or the
   built scene when there is none yet. GET /status says what is open, what was saved last and, while a shot is being
   opened, the steps by name and which one is running (the page draws its loading steps from that).

3. Letting the model build in front of the animator. POST /run?step=<what it is doing> with Python as the body runs
   that one build step here, on screen, as one undo step. Only a sender who knows the session key (the X-PP-Key
   header) is answered; a web page in the browser cannot send that header, so no site can reach this door.

   When the step names the objects it works on (&focus=name,name), the animator is shown where: the view glides to
   those objects, a ring with the step's name marks them, the step runs, and the view glides back to the shot.

4. The chat between the animator and the model. The Animate page writes with POST /say (only that page: the browser
   names the page a request comes from, and any other is refused). The model answers with POST /reply (session key).
   Every line is kept in SAVE_DIR/chat.jsonl with the shot and the number of the latest saved copy, so each
   instruction sits next to the scene before and after it.

5. Ready-made tools, answered in a blink. POST /tool?name=<tool> with the arguments as JSON runs one tool (face,
   camera_view, bones, play, frame, shading, undo, move, rotate, scale, focus) and answers with {"ok", "out" or
   "error"}. The Animate page's buttons call it (same page rule as /say); the small router on the Mac calls it with the
   session key. /status lists the tools and a short summary of the scene (objects, frame, view) for whoever chooses.

Blender is only ever touched from its own main thread (tick); the web thread just hands requests over.
"""
import contextlib
import io
import json
import math
import os
import queue
import shutil
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import blf
import bpy
import gpu
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader
from mathutils import Euler, Vector

ARGS = sys.argv[sys.argv.index("--") + 1:]
SHOTS = json.loads(Path(ARGS[0]).read_text())      # {"dock": "/…/SCENE_dock.blend", ...}
SAVE = Path(ARGS[1])
PORT = int(ARGS[2])
END = time.time() + float(ARGS[3]) * 60            # the machine kills Blender about now
FIRST_SHOT = ARGS[4]
KEY = ARGS[5] if len(ARGS) > 5 else ""          # the session key for the model's door; no key, no door
COLOURS = Path(__file__).resolve().parent / "view_colours.py"
PAGES = {"http://localhost:8575", "http://127.0.0.1:8575"}   # the Animate page: the only page that may write in the chat
SAVE_EVERY = 30                                    # seconds between looks at "did something change"
LAST_CALL = 40                                     # in the last seconds before END, save at every look

state = {"shot": None, "from": None, "last": None, "count": 0, "error": None, "until": END,   # what /status reports
         "opening": None, "steps": [], "step": 0,  # while a shot is being opened: its steps by name, and which one is running
         "model": None,                            # the model's build step: {"step": its name, "busy": still working, "at": when}
         "chat": []}                               # every line of the chat: {"id", "who": "you" or "model", "text", "at", "shot", "copy"}
jobs = queue.Queue()                               # shots the page asked for, from the web thread
builds = queue.Queue()                             # build steps from the model: (code, answer dict, done event, object names)
job = {}                                           # the build step in progress (see tick)
pointer = {"names": [], "label": "", "until": 0.0, "painted": False}   # what the ring in the 3D view marks, what it says, until when
GLIDE = 1.3                                        # seconds the view takes to glide to the objects before a step runs
STAY = 1.6                                         # seconds the view stays on them after the step, before gliding back
tool_calls = queue.Queue()                         # ready-made tools asked for: (name, args, answer dict, done event)
plan = []                                          # the steps still to do for the shot being opened: (name, function)
clock = {"saved_look": 0.0, "shown": False}


def window():
    return bpy.context.window_manager.windows[0]


def versions(shot):
    return sorted((SAVE / shot).glob(f"{shot}_v[0-9][0-9][0-9].blend"))


def busy():
    """True while the animator is in the middle of a move (grab, rotate, a drag). Saving then would cut it off."""
    return len(getattr(window(), "modal_operators", [])) > 0


def look_through_camera():
    """Show the shot the way it will be filmed: the 3D view looks through the scene's camera, its frame filling the view,
    and the cast in their own colours instead of plain grey (view_colours.py)."""
    for area in window().screen.areas:
        if area.type == "VIEW_3D":
            area.spaces.active.region_3d.view_perspective = "CAMERA"
            region = next(r for r in area.regions if r.type == "WINDOW")
            with bpy.context.temp_override(window=window(), area=area, region=region):
                bpy.ops.view3d.view_center_camera()
    try:
        with bpy.context.temp_override(window=window()):
            exec(compile(COLOURS.read_text(), str(COLOURS), "exec"), {"__name__": "__colours__"})
    except Exception as exc:                       # a grey cast is not a reason to fail opening the shot
        print("PP_LIVE could not colour the view:", exc, flush=True)
    if gpu.platform.backend_type_get() == "VULKAN":            # the graphics card is drawing: show the real materials
        for area in window().screen.areas:                     # (skin, eyes, cloth). Measured 13 Nov 2026 on an RTX 4090:
            if area.type == "VIEW_3D":                         # 88 pictures a second in the officer scene.
                area.spaces.active.shading.type = "MATERIAL"


def trim_screen():
    """A lighter Blender: only the 3D view and the timeline stay; the two side panels are closed. The welcome picture is
    switched off for the next start of Blender on this machine."""
    try:
        bpy.context.preferences.view.show_splash = False
        bpy.ops.wm.save_userpref()
    except Exception as exc:
        print("PP_LIVE could not switch the welcome picture off:", exc, flush=True)
    try:                                           # fill the machine's screen, which takes the size of the page's Blender area
        with bpy.context.temp_override(window=window()):
            bpy.ops.wm.window_fullscreen_toggle()
    except Exception as exc:
        print("PP_LIVE could not go fullscreen:", exc, flush=True)
    for kind in ("OUTLINER", "PROPERTIES"):
        area = next((a for a in window().screen.areas if a.type == kind), None)
        if area:
            try:
                with bpy.context.temp_override(window=window(), screen=window().screen, area=area):
                    bpy.ops.screen.area_close()
            except Exception as exc:
                print("PP_LIVE could not close", kind, exc, flush=True)


def adopt(shot, opened_from):
    """The file now open becomes this shot's work file, so the built scene is never overwritten."""
    work = SAVE / shot / f"{shot}_work.blend"
    work.parent.mkdir(parents=True, exist_ok=True)
    look_through_camera()
    with bpy.context.temp_override(window=window()):
        bpy.ops.file.make_paths_absolute()         # the libraries are found from any folder, on this machine and on the box
        bpy.ops.wm.save_as_mainfile(filepath=str(work), relative_remap=False)
    state.update(shot=shot, count=len(versions(shot)), error=None)
    state["from"] = Path(opened_from).name


def save_version(even_if_busy=False):
    """Keep a numbered copy if the animator changed something since the last one. Returns the copy's name or None."""
    shot = state["shot"]
    if not shot or not bpy.data.is_dirty or (busy() and not even_if_busy):
        return None
    with bpy.context.temp_override(window=window()):
        bpy.ops.wm.save_mainfile()
    have = versions(shot)
    number = int(have[-1].stem[-3:]) + 1 if have else 1
    out = SAVE / shot / f"{shot}_v{number:03d}.blend"
    part = out.with_suffix(".part")
    shutil.copy2(bpy.data.filepath, part)
    os.replace(part, out)                          # the copy appears whole or not at all
    now = time.time()
    with (SAVE / "log.tsv").open("a") as log:
        log.write("\t".join([time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), shot, out.name,
                             str(out.stat().st_size), str(window().scene.frame_current)]) + "\n")
    state.update(last={"file": out.name, "at": now, "shot": shot}, count=number)
    return out.name


def load(source):
    with bpy.context.temp_override(window=window()):
        bpy.ops.wm.open_mainfile(filepath=source, load_ui=False)


def steps_to_open(shot):
    """The steps that put this shot on screen: the animator's latest copy if there is one, else the built scene."""
    if shot == state["shot"]:
        return []                                  # already open: leave the animator's unsaved work alone
    have = versions(shot)
    source = str(have[-1]) if have else SHOTS[shot]
    todo = []
    if state["shot"]:
        todo.append((f"Saving your work on the {state['shot']} scene", lambda: save_version(even_if_busy=True)))
    todo.append((f"Loading your saved copy {int(have[-1].stem[-3:])} of the {shot} scene" if have else f"Loading the built {shot} scene",
                 lambda: load(source)))
    todo.append(("Making your own working copy", lambda: adopt(shot, source)))
    return todo


def chat_add(who, text, shot):
    """One line in the chat, also kept on disk beside the saved copies."""
    row = {"id": len(state["chat"]) + 1, "who": who, "text": text, "at": time.time(), "shot": shot, "copy": state["count"]}
    state["chat"].append(row)
    SAVE.mkdir(parents=True, exist_ok=True)
    with (SAVE / "chat.jsonl").open("a") as log:
        log.write(json.dumps(row) + "\n")


def view3d():
    """The 3D view and its main part."""
    for area in window().screen.areas:
        if area.type == "VIEW_3D":
            return area, next(r for r in area.regions if r.type == "WINDOW")
    return None, None


def in_view(operator):
    """Run a view operator (glide to selection, back to camera) in the 3D view."""
    area, region = view3d()
    with bpy.context.temp_override(window=window(), area=area, region=region):
        operator()


def middle(names):
    """The middle of the named objects, in the world."""
    corners = [o.matrix_world @ Vector(c) for o in map(bpy.data.objects.get, names) if o for c in o.bound_box]
    return sum(corners, Vector()) / len(corners) if corners else None


def point_at(names, label):
    """Show the animator where the model is about to work: select the objects, glide the view to them, ring them."""
    objects = [o for o in map(window().scene.objects.get, names) if o]
    if not objects:
        return False
    for o in window().view_layer.objects:
        o.select_set(o in objects)
    area, _ = view3d()
    job["was_camera"] = area.spaces.active.region_3d.view_perspective == "CAMERA"
    pointer.update(names=[o.name for o in objects], label=label, until=time.time() + 600)
    in_view(bpy.ops.view3d.view_selected)
    return True


def draw_pointer():
    """Drawn by Blender in the 3D view: a pulsing ring around what the model is working on, with the step's name."""
    try:
        if time.time() > pointer["until"]:
            return
        mid = middle(pointer["names"])
        at = mid and location_3d_to_region_2d(bpy.context.region, bpy.context.region_data, mid)
        if not at:
            return
        radius = 46 + 6 * math.sin(time.time() * 6)
        band = []
        for i in range(65):
            a = i * math.tau / 64
            band += [(at.x + radius * math.cos(a), at.y + radius * math.sin(a)), (at.x + (radius + 4) * math.cos(a), at.y + (radius + 4) * math.sin(a))]
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        gpu.state.blend_set("ALPHA")
        shader.uniform_float("color", (1.0, 0.72, 0.2, 0.95))
        batch_for_shader(shader, "TRI_STRIP", {"pos": band}).draw(shader)
        gpu.state.blend_set("NONE")
        blf.size(0, 17)
        blf.color(0, 1.0, 0.82, 0.4, 1.0)
        blf.position(0, at.x + radius + 14, at.y - 6, 0)
        blf.draw(0, pointer["label"])
    except Exception as exc:                       # a drawing fault must never stop Blender drawing
        pointer["until"] = 0.0
        print("PP_LIVE pointer error:", exc, flush=True)


def run_step(code):
    """One build step from the model: run it in this Blender, keep what it printed, make it one undo step."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), bpy.context.temp_override(window=window()):
        exec(compile(code, "<model step>", "exec"), {"bpy": bpy, "__name__": "__model__"})
        bpy.ops.ed.undo_push(message="PlotPointe model step")   # the animator can undo it, and the next look saves a copy
    for area in window().screen.areas:
        area.tag_redraw()
    return out.getvalue()


# ---- ready-made tools: each is small, checked, one undo step, and answers at once ----
def _objects(names):
    found = [window().scene.objects.get(n) for n in names]
    found = [o for o in found if o]
    if not found:
        raise ValueError("none of these objects is in this shot: " + ", ".join(map(str, names)))
    return found


def _num(a, key, low, high, default=0.0):
    value = float(a.get(key, default))
    if not low <= value <= high:
        raise ValueError(f"{key} must be between {low} and {high}")
    return value


def _flag(a, key, now):
    """True, False or 'toggle' (the default): what the tool should make of something that is on or off."""
    want = a.get(key, "toggle")
    return (not now) if want == "toggle" else bool(want)


def _shown(objects, label):
    for o in window().view_layer.objects:
        o.select_set(o in objects)
    in_view(bpy.ops.view3d.view_selected)          # the view glides there (smooth view)
    return f"{label} {', '.join(o.name for o in objects)}"


def tool_focus(a):
    return _shown(_objects(a.get("objects") or []), "Zoomed to")


def tool_face(a):
    if "HG_Eyes" not in window().scene.objects:
        raise ValueError("there is no face in this shot")
    return _shown(_objects(["HG_Eyes", "CAP_peak"]), "Zoomed to the face:")


def tool_camera_view(a):
    area, _ = view3d()
    view = area.spaces.active.region_3d
    if view.view_perspective == "CAMERA":
        in_view(bpy.ops.view3d.view_center_camera)
    else:
        in_view(bpy.ops.view3d.view_camera)
    return "Back to the shot's camera"


def tool_bones(a):
    space = view3d()[0].spaces.active
    space.overlay.show_bones = _flag(a, "show", space.overlay.show_bones)
    return "Bones shown" if space.overlay.show_bones else "Bones hidden"


def tool_play(a):
    area, region = view3d()
    playing = window().screen.is_animation_playing
    want = _flag(a, "on", playing)
    with bpy.context.temp_override(window=window(), screen=window().screen, area=area, region=region):
        if want and not playing:
            bpy.ops.screen.animation_play()
        elif playing and not want:
            bpy.ops.screen.animation_cancel(restore_frame=False)
    return "Playing" if want else f"Stopped at frame {window().scene.frame_current}"


def tool_frame(a):
    sc = window().scene
    sc.frame_set(int(_num(a, "n", sc.frame_start, sc.frame_end, sc.frame_current)))
    return f"On frame {sc.frame_current}"


def tool_shading(a):
    mode = {"material": "MATERIAL", "solid": "SOLID", "wire": "WIREFRAME"}.get(str(a.get("mode", "")).lower())
    if not mode:
        raise ValueError("mode must be material, solid or wire")
    view3d()[0].spaces.active.shading.type = mode
    return f"View shown as {a['mode'].lower()}"


def tool_undo(a):
    try:
        with bpy.context.temp_override(window=window()):
            bpy.ops.ed.undo()
    except RuntimeError:                           # the poll fails when the undo history is empty (just after opening a shot)
        raise ValueError("there is nothing to undo yet") from None
    return "Undone"


def tool_move(a):
    obj = _objects([a.get("object")])[0]
    obj.location += Vector((_num(a, "x", -50, 50), _num(a, "y", -50, 50), _num(a, "z", -50, 50)))
    return f"Moved {obj.name}"


def tool_rotate(a):
    obj = _objects([a.get("object")])[0]
    turn = Euler(tuple(math.radians(_num(a, k, -720, 720)) for k in "xyz")).to_quaternion()
    if obj.rotation_mode == "QUATERNION":
        obj.rotation_quaternion = turn @ obj.rotation_quaternion
    elif obj.rotation_mode == "AXIS_ANGLE":
        raise ValueError(f"{obj.name} turns by axis and angle, which this tool does not handle")
    else:
        obj.rotation_euler = (turn @ obj.rotation_euler.to_quaternion()).to_euler(obj.rotation_mode, obj.rotation_euler)
    return f"Turned {obj.name}"


def tool_scale(a):
    obj = _objects([a.get("object")])[0]
    obj.scale = obj.scale * _num(a, "factor", 0.05, 20, 1.0)
    return f"Scaled {obj.name}"


# name: (function, what it does for the chooser, its arguments, changes the scene?)
TOOLS = {
    "face": (tool_face, "Zoom the view to the character's face", {}, False),
    "focus": (tool_focus, "Zoom the view to named objects", {"objects": "list of object names"}, False),
    "camera_view": (tool_camera_view, "Back to the shot's camera view (the full shot)", {}, False),
    "bones": (tool_bones, "Show or hide the posing bones", {"show": "true, false or \"toggle\""}, False),
    "play": (tool_play, "Play or stop the timeline", {"on": "true, false or \"toggle\""}, False),
    "frame": (tool_frame, "Go to a frame of the timeline", {"n": "frame number"}, False),
    "shading": (tool_shading, "How the view draws: real materials, plain solid, or wire", {"mode": "material, solid or wire"}, False),
    "undo": (tool_undo, "Undo the last change", {}, False),
    "move": (tool_move, "Move an object by metres (x right, y away, z up)", {"object": "name", "x": "m", "y": "m", "z": "m"}, True),
    "rotate": (tool_rotate, "Turn an object by degrees about x, y, z", {"object": "name", "x": "deg", "y": "deg", "z": "deg"}, True),
    "scale": (tool_scale, "Make an object bigger or smaller by a factor (1.2 = 20 % bigger)", {"object": "name", "factor": "number"}, True),
}
state["tools"] = [{"name": n, "does": t[1], "args": t[2]} for n, t in TOOLS.items()]


def run_tool(name, args):
    function, _, _, changes = TOOLS[name]
    out = function(args)
    if changes:
        with bpy.context.temp_override(window=window()):
            bpy.ops.ed.undo_push(message=f"PlotPointe: {name}")
    for area in window().screen.areas:
        area.tag_redraw()
    return out


def scene_summary():
    """What whoever chooses a tool needs to know: the objects, the frame, how the view is set."""
    sc = window().scene
    area, _ = view3d()
    space = area.spaces.active if area else None
    state["scene"] = {
        "objects": [[o.name, o.type, o.parent.name if o.parent else ""] for o in list(sc.objects)[:250]],
        "frame": sc.frame_current, "range": [sc.frame_start, sc.frame_end],
        "playing": window().screen.is_animation_playing,
        "bones": space.overlay.show_bones if space else None,
        "shading": space.shading.type if space else None,
        "view": space.region_3d.view_perspective if space else None}


def tick():
    """Blender calls this on its main thread: ten times a second, so a tool answers in a blink."""
    try:
        if state["shot"] is None and not plan:     # first call: the file given on the command line is the first shot
            trim_screen()
            adopt(FIRST_SHOT, bpy.data.filepath)
        if not plan and not jobs.empty():
            shot = jobs.get_nowait()
            plan.extend(steps_to_open(shot))
            if plan:
                state.update(opening=shot, steps=[name for name, _ in plan], step=0, error=None)
                clock["shown"] = False
        if plan:
            if not clock["shown"]:                 # give the page a moment to read the step's name before Blender is busy with it
                clock["shown"] = True
                return 0.3
            _, work = plan.pop(0)
            work()
            state["step"] += 1
            clock["shown"] = False
            if not plan:
                state["opening"] = None
            return 0.3
        if time.time() < pointer["until"]:         # keep the ring pulsing
            pointer["painted"] = True
            view3d()[0].tag_redraw()
        elif pointer["painted"]:                   # its time is up: draw the view once more, without the ring
            pointer["painted"] = False
            view3d()[0].tag_redraw()
        if job:                                    # a build step in progress: (glide there) -> run -> (stay, glide back)
            if time.time() < job["at"]:
                return 0.1
            if job["stage"] == "run":
                try:
                    job["answer"]["out"] = run_step(job["code"])
                except Exception:                  # the model is told what went wrong; Blender keeps running
                    job["answer"]["error"] = traceback.format_exc(limit=4)
                job.update(stage="back", at=time.time() + (STAY if job["pointed"] else 0))
                return 0.1
            if job["pointed"]:
                if job.get("was_camera") and view3d()[0].spaces.active.region_3d.view_perspective != "CAMERA":
                    in_view(bpy.ops.view3d.view_camera)
                pointer["until"] = time.time() + 1.0
            job["done"].set()                      # the model stays "working" until it answers in the chat
            job.clear()
            return 0.1
        if not tool_calls.empty():
            name, args, answer, done = tool_calls.get_nowait()
            try:
                answer.update(ok=True, out=run_tool(name, args))
                scene_summary()
            except Exception as exc:               # a tool that cannot do it says why; Blender keeps running
                answer.update(ok=False, error=str(exc) or type(exc).__name__)
            done.set()
            return 0.05
        if not builds.empty():
            code, answer, done, names = builds.get_nowait()
            job.update(code=code, answer=answer, done=done, stage="run", pointed=False, at=time.time())
            try:
                if names and point_at(names, state["model"]["step"]):
                    job.update(pointed=True, at=time.time() + GLIDE)
            except Exception as exc:               # no pointer is not a reason to skip the step
                print("PP_LIVE could not point:", exc, flush=True)
            return 0.1
        now = time.time()
        if now - clock["saved_look"] >= SAVE_EVERY or now > END - LAST_CALL:
            clock["saved_look"] = now
            save_version()
        if now - clock.get("summary", 0.0) >= 2.0 and state["shot"]:
            clock["summary"] = now
            scene_summary()
    except Exception as exc:                       # the page is told; Blender keeps running
        plan.clear()
        state.update(opening=None, error=f"{type(exc).__name__}: {exc}")
        print("PP_LIVE error:", state["error"], flush=True)
    return 0.1


class Ask(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        answer = {}
        if url.path == "/open":                    # answered at once; the page then follows the steps through /status
            shot = parse_qs(url.query).get("shot", [""])[0]
            if shot in SHOTS:
                jobs.put(shot)
                answer["asked"] = shot
            else:
                answer["error"] = f"no such shot: {shot}"
        elif url.path != "/status":
            self.send_error(404)
            return
        body = json.dumps({**state, **answer}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        url = urlparse(self.path)
        ask = parse_qs(url.query)
        text = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        page = self.headers.get("Origin")
        model = bool(KEY) and self.headers.get("X-PP-Key") == KEY
        answer = {}
        if url.path == "/say" and page in PAGES:               # the animator, from the Animate page
            if text.strip():
                chat_add("you", text.strip()[:2000], ask.get("shot", [""])[0] or state["shot"])
        elif url.path == "/reply" and model:                   # the model's answer; it is no longer working
            if text.strip():
                chat_add("model", text.strip(), state["shot"])
            if state["model"]:
                state["model"]["busy"] = False
        elif url.path == "/working" and model:                 # the model says what it is doing, before a slow step
            state["model"] = {"step": ask.get("step", ["working"])[0], "busy": True, "at": time.time()}
        elif url.path == "/tool" and (model or page in PAGES):   # a button on the page, or the router with the key
            name = ask.get("name", [""])[0]
            if name not in TOOLS:
                answer.update(ok=False, error=f"no such tool: {name}")
            else:
                try:
                    args = json.loads(text) if text.strip() else {}
                except ValueError:
                    args = None
                if not isinstance(args, dict):
                    answer.update(ok=False, error="the arguments are not JSON")
                else:
                    done = threading.Event()
                    tool_calls.put((name, args, answer, done))
                    if not done.wait(30):
                        answer.update(ok=False, error="Blender did not answer in 30 seconds")
            if not answer.get("ok") and not model:               # the animator pressed a button: say why it did nothing
                chat_add("model", f"{name}: {answer.get('error')}", state["shot"])
        elif url.path == "/run" and model:
            done = threading.Event()
            state["model"] = {"step": ask.get("step", ["working"])[0], "busy": True, "at": time.time()}
            builds.put((text, answer, done, [n for n in ask.get("focus", [""])[0].split(",") if n]))
            if not done.wait(600):
                answer["error"] = "Blender did not finish this step in 10 minutes"
        else:
            self.send_error(403)
            return
        body = json.dumps(answer).encode()
        self.send_response(200)
        if page in PAGES:                          # only the Animate page may read the answer in a browser
            self.send_header("Access-Control-Allow-Origin", page)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if (SAVE / "chat.jsonl").exists():                             # the chat goes on where it stopped
    state["chat"] = [json.loads(line) for line in (SAVE / "chat.jsonl").read_text().splitlines() if line.strip()]
bpy.context.preferences.view.smooth_view = 700                # the view glides (0.7 s) instead of jumping, so the eye can follow
bpy.types.SpaceView3D.draw_handler_add(draw_pointer, (), "WINDOW", "POST_PIXEL")
bpy.context.preferences.filepaths.save_version = 0             # no .blend1 files beside the copies
threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", PORT), Ask).serve_forever, daemon=True).start()
bpy.app.timers.register(tick, first_interval=2.0, persistent=True)   # persistent: it survives opening another file
print(f"PP_LIVE ready on port {PORT}, saving to {SAVE}", flush=True)
