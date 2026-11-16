"""The preview's own small server (this Mac only, 127.0.0.1:8575). It does two things:

  1. serves the page and its data, always fresh (the browser never shows an old copy)
  2. keeps every script's work for real, not only in the browser:
       GET  /api/state                 every script's saved work
       POST /api/save?folder=<folder>  one script's work (steps, text, change log, sessions), written to
                                         data/work/<folder>.json                       PlotPointe's own copy
                                         <Drive>/<folder>/01 Script/Script.txt         the latest text
                                         <Drive>/<folder>/00 Record/Record.txt         steps, dates, work sessions
                                         <Drive>/<folder>/00 Record/changes.jsonl      every change, one per line
                                         <Drive>/<folder>/02 Storyboard/Storyboard.txt  the storyboard with the writer's notes (when there is one)

       GET  /api/file?folder=&step=&name=  one picture, sound, video or captions file from a script's Drive step folder
                                       (what the demo plays: the storyboard pictures, the preview, the sound, the captions)
       POST /api/new                   a new idea written in the platform ({title, idea, lines}; the script lines can come
                                       later): its Drive folder with the step folders, its record, and a place in data/scripts.js
       POST /api/chat?folder=<folder>  the writer's message about one script; a model reads the script and answers with
                                       what it changed and the full new text. Its only writing lessons are the ones from
                                       Nick's ChatGPT chat (data/lessons.json; Nick, 13 Nov 2026: "you should only take the
                                       lessons from this chat."). Lines the writer edited are marked so the model leaves them
                                       alone; the page also never applies a change to them without the writer's click.
                                       Plus the full script rules Nick pasted the same day (data/import/rules_pasted.txt).
                                       PlotPointe's own 15 lessons are not used ("remove all plotpointe lessons. all 15.").
                                         <Drive>/<folder>/00 Record/chat.jsonl          every chat line, with the change it made

Only folders in data/scripts.js are accepted, and only requests from this page.
"""
import json
import shutil
import subprocess
import sys
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data" / "work"
DRIVE = Path.home() / "Library/CloudStorage/GoogleDrive-nikolaskoundouros@gmail.com/My Drive/Art Of War Productions"
PORT = 8575
PAGES = {f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"}
CHAT_MODEL = "sonnet"                              # asked through the Claude command-line tool, on Nick's own login
CHAT_TIMEOUT = 120
NEUTRAL = Path("/private/tmp")                     # the model runs from a folder with no project instructions in it
JSON_ONLY = "You edit short narrated scripts. Reply with one JSON object and nothing else: no code fences, no notes."
# The seven checkpoints (Nick, 13 Nov 2026: "idea, script, storyboard, preview (animate), sfx, captions, publish").
STEPS = [("Idea", ["Waiting for approval", "Approved"]), ("Script", ["Waiting for edit and approval", "Approved"]),
         ("Storyboard", ["Not started", "Written", "Approved"]), ("Preview", ["Not started", "In Blender", "Preview ready"]),
         ("SFX", ["Not started", "Added", "Approved"]), ("Captions", ["Not started", "Added", "Approved"]),
         ("Publish", ["Not published", "Published"])]
OLD_STEPS = [1, 2, 3, 6]                           # where the four earlier steps (script, storyboard, animate, publish) sit now
MEDIA = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".mp4": "video/mp4",
         ".mov": "video/quicktime", ".webm": "video/webm", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
         ".srt": "text/plain; charset=utf-8", ".vtt": "text/vtt; charset=utf-8", ".txt": "text/plain; charset=utf-8"}


def upgrade(state):
    """A record from before Idea, SFX and Captions were steps (4 steps) in the 7-step shape. Its idea counts as approved:
    every such script already had its text."""
    if isinstance(state, dict) and isinstance(state.get("at"), list) and len(state["at"]) == 4:
        def move(a, fill):
            out = [fill] * len(STEPS)
            for i, k in enumerate(OLD_STEPS):
                out[k] = (a or [fill] * 4)[i]
            return out
        state = dict(state, at=move(state["at"], 0), on=move(state.get("on"), None))
        state["at"][0] = 1
        if state.get("re"):
            state["re"] = move(state["re"], None)
    return state


STEP_FOLDERS = ["00 Record", "01 Script", "02 Storyboard", "03 Blend", "04 Clips and final video", "05 Sound", "06 Captions", "07 Publish"]


def registry(root=ROOT):
    text = (root / "data" / "scripts.js").read_text()
    return {r["folder"]: r for r in json.loads(text.split("=", 1)[1].rstrip().rstrip(";"))}


def storyboards(root=ROOT):
    f = root / "data" / "storyboards.js"
    return json.loads(f.read_text().split("=", 1)[1].rstrip().rstrip(";")) if f.is_file() else {}


def storyboard_text(script, sb, notes):
    """The storyboard as plain text for Drive: every shot with its words, who is in it, its picture and the writer's note."""
    cast = {c["id"]: c["name"] for c in sb["cast"]}
    out = [f"Storyboard: {script['title']}", f"{len(sb['shots'])} shots, about {sb['seconds']} seconds, made {sb['made']}.", ""]
    for x in sb["shots"]:
        out += [f"SHOT {x['n']}  {x['words']}", f"  In it:   {', '.join(cast.get(c, c) for c in x['cast']) or 'nobody'}", f"  Picture: {x['image']}"]
        if notes.get(str(x["n"])) or notes.get(x["n"]):
            out.append(f"  NOTE:    {notes.get(str(x['n'])) or notes.get(x['n'])}")
        out.append("")
    out += ["CAST"] + [f"  {c['name']} ({c['kind']}): {c['look']}" for c in sb["cast"]]
    return "\n".join(out) + "\n"


def clock(ms):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ms / 1000))


def record_text(script, state):
    """The script's record as plain text: where each step stands, the work sessions, the number of changes."""
    lines = [f"Script:   {script['title']}", f"Folder:   Art Of War Productions / {script['folder']}",
             "Text:     01 Script / Script.txt (the latest text, kept up to date by PlotPointe)", f"Source:   {script['source']}",
             f"Tracking started {script['started']}.", ""]
    state = upgrade(state)
    at, on = state.get("at", [0] * len(STEPS)), state.get("on", [None] * len(STEPS))
    if state.get("idea") or script.get("idea"):
        lines += [f"Idea:     {state.get('idea') or script.get('idea')}", ""]
    for n, (name, states) in enumerate(STEPS):
        lines.append(f"STEP {n + 1}  {name:<11} {states[min(at[n], len(states) - 1)]}" + (f"  ({on[n]})" if on[n] else ""))
    sessions, log = state.get("sessions", []), state.get("log", [])
    notes = (state.get("sb") or {}).get("notes") or {}
    if notes:
        lines += ["", f"Storyboard notes: {len(notes)} (in 02 Storyboard / Storyboard.txt)"]
    lines += ["", f"Work sessions: {len(sessions)}   Changes: {len(log)}   Chat lines: {len(state.get('chat', []))}   (every change is in changes.jsonl, the chat in chat.jsonl)"]
    lines += [f"  Session {i}: {clock(s['start'])} to {clock(s['end'])[-5:]}, {s['changes']} change{'s' if s['changes'] != 1 else ''}"
              for i, s in enumerate(sessions, 1)]
    return "\n".join(lines) + "\n"


def folder_name(title):
    """The script's title as a folder name: no em or en dashes, no slashes (the same rule as tools/make_folders.py)."""
    return title.replace("\u2014", "-").replace("\u2013", "-").replace("/", "-").strip()


def new_script(body, root=ROOT, drive=DRIVE, work=WORK, now=None):
    """A new idea (and, if written already, its script) in the platform. Returns its record; raises ValueError for anything unusable."""
    title, lines, idea = body.get("title"), body.get("lines", []), body.get("idea", "")
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 120 or title.strip().startswith("."):
        raise ValueError("give the script a title (up to 120 letters)")
    if not isinstance(lines, list) or not all(isinstance(x, str) for x in lines) or not isinstance(idea, str) or len(idea) > 3000:
        raise ValueError("no usable text")
    title, lines, idea = " ".join(title.split()), [x.strip() for x in lines if x.strip()], " ".join(idea.split())
    if not lines and not idea:
        raise ValueError("write the idea")
    if len(lines) > 80 or sum(map(len, lines)) > 12000:
        raise ValueError("that is far too long for one script")
    js = root / "data" / "scripts.js"
    reg = json.loads(js.read_text().split("=", 1)[1].rstrip().rstrip(";"))
    folder = folder_name(title)
    if any(r["folder"].lower() == folder.lower() or r["title"].lower() == title.lower() for r in reg) or (drive / folder).exists():
        raise ValueError("a script with this title already exists")
    now = now or time.time()
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    script = {"title": title, "folder": folder, "doc": None, "source": f"written in the platform on {day}", "lines": lines, "idea": idea, "started": day,
              "made": "platform", "steps": [{"step": n, "state": st[0], "at": None} for n, st in STEPS]}
    if drive.is_dir():
        for sub in STEP_FOLDERS:
            (drive / folder / sub).mkdir(parents=True, exist_ok=True)
        (drive / folder / "00 Record" / "record.json").write_text(json.dumps(script, indent=1, ensure_ascii=False) + "\n")
    reg.append(script)
    reg.sort(key=lambda r: r["title"].lower())
    js.write_text("window.SCRIPTS = " + json.dumps(reg, indent=1, ensure_ascii=False) + ";\n")
    ms = int(now * 1000)                           # the first change: the script was written here
    first = [{"at": ms, "who": "you", "what": "Idea written in the platform", "line": None, "before": "", "after": idea}] if idea else []
    if lines:
        first.append({"at": ms, "who": "you", "what": "Script written in the platform", "line": 1, "before": "", "after": "\n".join(lines)})
    state = {"at": [0] * len(STEPS), "on": [None] * len(STEPS), "idea": idea, "text": lines,
             "sessions": [{"start": ms, "end": ms, "changes": len(first)}], "log": first}
    save(folder, {"state": state, "text": lines}, work=work, drive=drive, scripts={folder: script})
    return {"script": script, "state": state}


def save(folder, body, work=WORK, drive=DRIVE, scripts=None):
    """Keep one script's work. Returns what was written; raises ValueError for anything that is not a known script."""
    scripts = scripts if scripts is not None else registry()
    if folder not in scripts:
        raise ValueError("unknown script")
    state, text = upgrade(body.get("state")), body.get("text")
    if not isinstance(state, dict) or not isinstance(state.get("at"), list) or len(state["at"]) != len(STEPS):
        raise ValueError("no usable state")
    if not isinstance(text, list) or not all(isinstance(t, str) for t in text):
        raise ValueError("no usable text")
    script = scripts[folder]
    work.mkdir(parents=True, exist_ok=True)
    (work / f"{folder}.json").write_text(json.dumps(state, ensure_ascii=False) + "\n")
    written = [f"data/work/{folder}.json"]
    base = drive / folder
    if base.is_dir():                              # Drive gets the readable copies
        (base / "01 Script").mkdir(exist_ok=True)
        (base / "00 Record").mkdir(exist_ok=True)
        (base / "01 Script" / "Script.txt").write_text(script["title"] + "\n\n" + "\n".join(text) + "\n")
        (base / "00 Record" / "Record.txt").write_text(record_text(script, state))
        (base / "00 Record" / "changes.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in state.get("log", [])))
        written += ["01 Script/Script.txt", "00 Record/Record.txt", "00 Record/changes.jsonl"]
        sb = storyboards().get(script.get("doc"))
        if sb:
            (base / "02 Storyboard").mkdir(exist_ok=True)
            (base / "02 Storyboard" / "Storyboard.txt").write_text(storyboard_text(script, sb, (state.get("sb") or {}).get("notes") or {}))
            written.append("02 Storyboard/Storyboard.txt")
        if state.get("chat"):
            (base / "00 Record" / "chat.jsonl").write_text("".join(json.dumps({k: m.get(k) for k in ("at", "who", "text", "change", "undone", "suggest", "applied")}, ensure_ascii=False) + "\n" for m in state["chat"]))
            written.append("00 Record/chat.jsonl")
    return written


def lessons(root=ROOT):
    f = root / "data" / "lessons.json"
    return json.loads(f.read_text())["lessons"] if f.is_file() else []


def script_rules(root=ROOT):
    """The full rules Nick pasted (ChatGPT's reconstruction), word for word."""
    f = root / "data" / "lessons.json"
    return (json.loads(f.read_text()).get("rules") or {}).get("text", "") if f.is_file() else ""


def chat_prompt(script, lines, history, message, taught=(), mine=(), rules=""):
    """What the model is asked: the writer's lessons, the script with the writer's marks and the lines the writer edited, the recent chat, the message."""
    numbered = "\n".join(f"{i}. {line}" + ("   [the writer's own edit]" if line in mine else "") for i, line in enumerate(lines, 1))
    told = "\n".join(f'- "{l["text"]}" ({l["who"]})' for l in taught)
    talk = "\n".join(f'{"writer" if m.get("who") == "you" else "you"}: {str(m.get("text", ""))[:300]}' for m in history[-6:])
    return f"""You are PlotPointe's script editor. The scripts are short narrated history videos: one spoken chain of about 100 words, one clause per line. The writer has the script "{script['title']}" open in an editable box and typed one message to you.

What this writer has taught you, in the words it was said (follow it):
{told or "(nothing yet)"}

The writer's script rules, as the writer gave them (follow them; the editing rules come first):
{rules or "(none given)"}

The script as it stands, one line per row. The writer's marks: ~~text~~ is struck out (the writer wants it gone), **text** is the writer's own words, [fluff: text] is filler, [flow: text] does not follow from the line before, [sense: text] does not make sense, [keep: text] is good.
{numbered}

Recent chat:
{talk or "(nothing yet)"}

How to answer:
- Change only what the message asks for. Every other line stays exactly as it is, letter for letter, marks included.
- Never change a line marked [the writer's own edit], or the writer's own words (**text**), unless the message asks for exactly that. If you think one of them should change, leave it as it is and say what you suggest in "say".
- If the message asks you to apply or clean up the marks: delete struck text, repair fluff, flow and sense passages, keep the kept text, and leave no mark behind on what you handled.
- If the message is a question, or needs no change, answer it and leave the script alone.
- No em dashes and no en dashes.
- "say" is one or two short plain sentences to the writer: what you changed and why, or the answer.

Reply with JSON only:
{{"say": "...", "lines": ["the full script after your change, every line, in order"]}}
or, when the script stays as it is:
{{"say": "...", "lines": null}}

The writer's message: {json.dumps(message)}"""


def parse_reply(raw, current):
    """The model's answer -> {"say", "lines"} (lines None when the script stays as it is). Raises ValueError when unusable."""
    start, end = raw.find("{"), raw.rfind("}")
    try:
        reply = json.loads(raw[start:end + 1])
    except ValueError:
        raise ValueError("the model gave no usable answer") from None
    say = reply.get("say") if isinstance(reply, dict) else None
    if not isinstance(say, str) or not say.strip():
        raise ValueError("the model gave no usable answer")
    lines = reply.get("lines")
    if lines is not None:
        if not isinstance(lines, list) or not all(isinstance(x, str) for x in lines):
            raise ValueError("the model's script was not a list of lines")
        lines = [x.strip() for x in lines if x.strip()]
        if not 1 <= len(lines) <= 80 or sum(map(len, lines)) > 12000:
            raise ValueError("the model's script was empty or far too long")
        if lines == [x.strip() for x in current if x.strip()]:
            lines = None
    return {"say": say.strip()[:700], "lines": lines}


def ask_model(prompt):
    claude = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
    out = subprocess.run([claude, "-p", "--model", CHAT_MODEL, "--safe-mode", "--tools", "", "--no-session-persistence",
                          "--system-prompt", JSON_ONLY, prompt], capture_output=True, text=True, timeout=CHAT_TIMEOUT, cwd=NEUTRAL)
    return out.stdout


def chat(folder, body, scripts=None, ask=ask_model):
    """One chat message about one script. Returns {"say", "lines"}; raises ValueError for anything unusable."""
    scripts = scripts if scripts is not None else registry()
    if folder not in scripts:
        raise ValueError("unknown script")
    message, lines, history, mine = body.get("text"), body.get("lines"), body.get("history") or [], body.get("mine") or []
    if not isinstance(message, str) or not message.strip() or len(message) > 2000:
        raise ValueError("no usable message")
    if not isinstance(lines, list) or not lines or not all(isinstance(x, str) for x in lines):
        raise ValueError("no script to work on")
    try:
        mine = [x for x in mine if isinstance(x, str)] if isinstance(mine, list) else []
        raw = ask(chat_prompt(scripts[folder], lines, history if isinstance(history, list) else [], message.strip(), lessons(), mine, script_rules()))
    except (subprocess.TimeoutExpired, OSError):
        raise ValueError("the model did not answer in time") from None
    return parse_reply(raw, lines)


def all_states(work=WORK, scripts=None):
    scripts = scripts if scripts is not None else registry()
    out = {}
    for folder in scripts:
        f = work / f"{folder}.json"
        if f.is_file():
            out[folder] = upgrade(json.loads(f.read_text()))
    return out


def step_files(drive=DRIVE, scripts=None):
    """What is in each script's step folders in Drive (02 Storyboard to 07 Publish): the files the platform can show, by name."""
    scripts = scripts if scripts is not None else registry()
    out = {}
    for folder in scripts:
        got = {}
        for sub in STEP_FOLDERS[2:]:
            d = drive / folder / sub
            names = sorted(x.name for x in d.iterdir() if x.is_file() and x.suffix.lower() in MEDIA) if d.is_dir() else []
            if names:
                got[sub] = names
        if got:
            out[folder] = got
    return out


def step_file(query, drive=DRIVE, scripts=None):
    """One file from a script's step folder, or None: only known scripts, the step folders and the file types above."""
    scripts = scripts if scripts is not None else registry()
    folder, sub, name = (query.get(k, [""])[0] for k in ("folder", "step", "name"))
    if folder not in scripts or sub not in STEP_FOLDERS[2:] or not name or "/" in name or name.startswith("."):
        return None
    f = drive / folder / sub / name
    return f if f.is_file() and f.suffix.lower() in MEDIA else None


class Page(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kw):
        super().__init__(*args, directory=str(ROOT), **kw)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def answer(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/state":
            return self.answer(200, {"scripts": all_states(), "files": step_files()})
        if url.path == "/api/file":
            f = step_file(parse_qs(url.query))
            if not f:
                return self.answer(404, {"error": "no such file"})
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", MEDIA[f.suffix.lower()])
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return None
        return super().do_GET()

    def do_POST(self):
        url = urlparse(self.path)
        origin = self.headers.get("Origin")
        if url.path not in ("/api/save", "/api/chat", "/api/new") or (origin and origin not in PAGES):
            return self.answer(403, {"error": "not allowed"})
        size = int(self.headers.get("Content-Length", 0))
        if size > 2_000_000:
            return self.answer(413, {"error": "too large"})
        folder = parse_qs(url.query).get("folder", [""])[0]
        try:
            body = json.loads(self.rfile.read(size))
            if url.path == "/api/chat":
                return self.answer(200, chat(folder, body))
            if url.path == "/api/new":
                return self.answer(200, new_script(body))
            written = save(folder, body)
        except (ValueError, OSError) as exc:
            return self.answer(400, {"error": str(exc)})
        return self.answer(200, {"ok": True, "written": written})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"PlotPointe preview on http://localhost:{PORT}/animate.html", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Page).serve_forever()
