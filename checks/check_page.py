"""The check for the Animate page. Exit 0 = pass.

1. The Bat Bombs on the page says exactly what PlotPointe's storyboard file says (words, cast, picture text).
2. The navy demo on the page says exactly what the 12 Nov scene reports say (title, frames, lens, notes), and
   every one of its 4 storyboards and 12 built-scene pictures exists.
3. The page keeps PlotPointe's own colours and type (the :root and body lines match telegram/app.html).
4. In a real browser: the home screen lists 26 scripts, each on Step 1, and a script's page moves it on step by step; the
   Drive folders for all 26 exist with their step folders and a record; the earlier storyboard demos sit underneath; a shot starts empty (an empty chat, one
   Generate button, the shots and the scene details minimised) and each toggle flips its widget; pressing Generate
   puts the built scene's picture in Blender's place, or the live Blender when one is on; the live window survives
   toggles and shot changes; the chat shows the animator's and the model's lines and the model's running step, and
   sends what is typed; a storyboard with no built scene cannot be generated.
"""
import html
import json
from urllib.parse import quote
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
NAVY = [("dock", "storyboard_dock.png"), ("officer", "storyboard_officer.png"),
        ("cruiser", "storyboard_cruiser.png"), ("carrier", "storyboard_carrier_battleship.png")]
fails = []


def need(ok, what):
    print(("PASS  " if ok else "FAIL  ") + what)
    if not ok:
        fails.append(what)


def is_jpeg(rel):
    f = ROOT / rel
    return f.is_file() and f.read_bytes()[:3] == b"\xff\xd8\xff"


js = (ROOT / "data" / "story.js").read_text()
stories = {s["id"]: s for s in json.loads(js[js.index("["):js.rindex("]") + 1])}
order = [s["id"] for s in json.loads(js[js.index("["):js.rindex("]") + 1])]

# 1. The Bat Bombs: copied, not rewritten
src = json.loads((ROOT / "data" / "bat_bombs.json").read_text())
bb = stories["bat_bombs"]
need(bb["title"] == src["title"] and bb["seconds"] == src["seconds"], "Bat Bombs: title and length match the storyboard file")
need(len(bb["shots"]) == len(src["shots"]) > 0, f"Bat Bombs: same number of shots as the storyboard file ({len(src['shots'])})")
need(all(a["words"] == b["words"] and a["prompt"] == b["prompt"] and a["entities"] == b["entities"]
         for a, b in zip(bb["shots"], src["shots"])), "Bat Bombs: every shot's words, picture text and cast are identical to the source")
need([(e["id"], e["name"], e["look"]) for e in bb["entities"]] == [(e["id"], e["name"], e["look"]) for e in src["entities"]],
     "Bat Bombs: every cast member's name and look are identical to the source")
pics = [s["image"]["src"] for s in bb["shots"] if s["image"]] + [e["image"]["src"] for e in bb["entities"] if e["image"]]
need(all(s["image"] for s in bb["shots"]) and all(is_jpeg(p) for p in pics), f"Bat Bombs: every shot has a picture and all {len(pics)} pictures are real JPEG files")
need(all(s["built"] is None for s in bb["shots"]), "Bat Bombs: no shot claims a built scene")

# 2. The navy demo: says what the scene reports say
nv = stories["navy"]
need(order[0] == "navy" and nv.get("demo") is True, "the navy demo is the first storyboard")
need([s["short"] for s in nv["shots"]] == [n for n, _ in NAVY], "navy: the four scenes are dock, officer, cruiser, carrier")
for shot, (short, board) in zip(nv["shots"], NAVY):
    spec = json.loads((ROOT / "data" / "navy" / f"spec_{short}.json").read_text())
    made = json.loads((ROOT / "data" / "navy" / f"build_b_{short}.json").read_text())
    b = shot["built"]
    need(shot["words"] == spec["title"] and b["notes"] == spec.get("notes", []), f"navy {short}: title and notes are the spec's own words")
    need(b["file"] == made["name"] + ".blend" and b["frames"] == made["zoom"]["frames"] and b["lens"] == made["zoom"]["lens"],
         f"navy {short}: scene file, frame range and lens match the build report")
    need(f"from {made['zoom']['lens'][0]} to {made['zoom']['lens'][1]} mm" in " ".join(b["parts"]), f"navy {short}: the camera line on the page carries the build report's lens numbers")
    need(is_jpeg(shot["image"]["src"]) and [p["frame"] for p in b["pictures"]] == [1, 120, 240] and all(is_jpeg(p["src"]) for p in b["pictures"]),
         f"navy {short}: the storyboard and the three built-scene pictures exist")
    need(bool(made.get("officer")) == any("officer" in p.lower() for p in b["parts"]), f"navy {short}: the officer is listed only if the build report has him")

# 3. PlotPointe's own look
page, ref = (ROOT / "animate.html").read_text(), (ROOT / "reference" / "app.html").read_text()
for start in (":root{", "html,body{"):
    line = next(l for l in ref.splitlines() if l.startswith(start))
    need(line in page, f"the page carries PlotPointe's '{start}' line unchanged")


# 4. it really renders
LIVE_TAG = next(l for l in page.splitlines() if "data/live.js" in l)   # the one line that loads today's live setting
need(LIVE_TAG.count("<script") == 2 and "Date.now()" in LIVE_TAG, "the live setting is asked for fresh on every load, never from the browser's old copy")


def dom(after, live="null"):
    """The page as a browser leaves it after running `after` (the same clicks a person makes).
    `live` stands in for data/live.js, so the checks say the same whatever is live today."""
    probe = ROOT / "checks" / "_probe.html"
    probe.write_text(page.replace(LIVE_TAG, "<script>window.LIVE = " + live + ";</script>")
                     .replace("\nlist();\n", "\ntry{localStorage.clear()}catch(e){};list();" + after + "\n")
                     .replace('src="data/', 'src="../data/').replace('"data/img/', '"../data/img/'))
    try:
        out = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--virtual-time-budget=4000", "--dump-dom", probe.as_uri()],
                             capture_output=True, text=True, timeout=90).stdout
        return html.unescape(out.split("</style>")[1])
    finally:
        probe.unlink()


def stage(out):
    """Only Blender's place on the shot screen."""
    return out.split('class="stage"')[1].split('class="shotsbar"')[0]


ROW = "showStage(3);document.querySelectorAll('.row.demo')[%d].click();"     # the earlier storyboard demos live under Preview: 0 = Navy shots, 1 = The Bat Bombs
GEN = "document.querySelector('.start .go').click();"
TOG = "document.querySelectorAll('.tog')[%d].click();"          # 0 chat, 1 shots, 2 details
CELL = "document.querySelectorAll('.cell')[%d].click();"
cells = lambda out: len(re.findall(r'class="cell( on)?"', out))
if not Path(CHROME).exists():
    need(False, "Chrome is installed for the render check")
else:
    out = dom("showStage(3);")
    demos = out.split('class="rows demos"')[1]
    need(demos.find(">Navy shots<") != -1 and demos.find(">Navy shots<") < demos.find(f">{src['title']}<"), "under Preview, 'Earlier demos' lists both storyboards, the navy demo first")

    # the process in the sidebar: the seven checkpoints (Nick, 13 Nov: "idea, script, storyboard, preview (animate), sfx, captions, publish"); every item works
    reg = json.loads((ROOT / "data" / "scripts.js").read_text().split("=", 1)[1].rstrip().rstrip(";"))
    titles_ = [r["title"] for r in reg]
    out = dom("")
    nav = out.split('class="nav"')[1].split("</nav>")[0]
    need(re.findall(r"<button[^>]*>([^<]+)</button>", nav)[-7:] == ["Ideas", "Scripts", "Storyboard", "Preview", "SFX", "Captions", "Publish"] and "disabled" not in nav and 'aria-current="page">Ideas<' in nav,
         "the sidebar is the process: Ideas, Scripts, Storyboard, Preview, SFX, Captions, Publish, every item clickable, and the page opens on Ideas")
    need("Create another" not in out and "My scripts" not in out and ">Visuals<" not in out, "the old dead sidebar items (Create another, My scripts, Visuals) are gone")
    for n, name in ((2, "Storyboard"), (3, "Preview"), (4, "SFX"), (5, "Captions"), (6, "Publish")):
        o = dom(f"showStage({n});")
        need(f'<h1>{name}</h1>' in o and f'aria-current="page">{name}<' in o and "class=\"row script\"" not in o, f"the {name} page opens, is marked in the sidebar, and is empty while no script has reached it")
    need("No script is approved yet" in dom("showStage(2);") and "No storyboard is approved yet" in dom("showStage(3);") and "No preview is ready yet" in dom("showStage(4);")
         and "No sound is approved yet" in dom("showStage(5);") and "No captions are approved yet" in dom("showStage(6);"),
         "an empty stage says plainly what has to happen first")

    # the scripts: one row each, every one starting fresh at step 1, and a page per script with its four steps
    need(len(reg) == 26 and len(set(titles_)) == 26, "the script list has 26 different scripts")
    need(all([x["step"] for x in r["steps"]] == ["Script", "Storyboard", "Animate", "Publish"] and r["steps"][0]["state"] == "Waiting for edit and approval"
             and [x["state"] for x in r["steps"][1:]] == ["Not started", "Not started", "Not published"] and r["started"] for r in reg), "every script starts fresh at step 1: script waiting for approval, storyboard, animate and publish not started")
    need(not any("—" in r["folder"] or "–" in r["folder"] or "/" in r["folder"] for r in reg), "no folder name has a long dash or a slash")
    need(len(re.findall(r'class="row script"', out)) == 26 and out.count("Idea · Approved") == 26 and ">New idea<" in out,
         "the Ideas page lists all 26 scripts, each idea approved (they came from the writers' docs with their idea), with a New idea button")
    o = dom("showStage(1);")
    need(len(re.findall(r'class="row script"', o)) == 26 and o.count("Script · Waiting for edit and approval") == 26,
         "the Scripts page shows 26 scripts, each waiting for edit and approval")
    first = titles_[0]
    SCRIPT = "document.querySelectorAll('.row.script')[0].click();"
    out = dom(SCRIPT)
    need(out.count('class="stepbox') == 7 and [m for m in re.findall(r'<b class="name">([^<]+)</b>', out)] == ["Idea", "Script", "Storyboard", "Preview", "SFX", "Captions", "Publish"]
         and "Starts when step 2 is done" in out and "Starts when step 6 is done" in out and ">Approve script<" in out and f"Art Of War Productions / {first}" in out
         and "came from the writers' Google Doc, with its idea already written" in out,
         "a script's page shows its seven steps (the later ones wait), its idea approved, the Approve script button and its Drive folder")
    out = dom(SCRIPT + "document.querySelector('.stepbox .go').click();")
    need("Approved · 20" in out and ">Mark storyboard written<" in out and "Starts when step 3 is done" in out, "approving the script moves it on: step 2 shows Approved with a date and step 3 offers its next button")
    out = dom(SCRIPT + "document.querySelector('.stepbox .go').click();showStage(1);")
    need(out.count('class="row script"') == 26 and out.count("Script · Approved") == 1 and out.count("Script · Waiting for edit and approval") == 25, "on the Scripts page, that one script is now Approved and the other 25 still wait")
    out = dom(SCRIPT + "document.querySelector('.stepbox .go').click();document.querySelector('.text').click();")
    need('aria-current="page">Storyboard<' in out and out.count('class="row script"') == 1, "the back link on an approved script leads to the stage it is now in (Storyboard)")
    out = dom(SCRIPT + "document.querySelector('.stepbox .go').click();showStage(2);")
    need(out.count('class="row script"') == 1 and f">{first}<" in out and "Storyboard · Not started" in out, "an approved script appears on the Storyboard page, and only that one")
    WALK = SCRIPT + "const go=t=>[...document.querySelectorAll('.stepbox .go')].find(b=>b.textContent===t).click();go('Approve script');go('Mark storyboard written');go('Approve storyboard');"
    out = dom(WALK + "document.querySelectorAll('.reopen')[1].click();")
    need(">Approve script<" in out and "Waiting for edit and approval" in out and "Script was reopened. Check this still fits" in out and "Approved · 20" in out,
         "an approved script can be reopened to edit: step 1 offers Approve script again, and the approved storyboard stays, with a note to check it")
    out = dom(WALK + "document.querySelectorAll('.reopen')[1].click();showStage(2);")
    need(out.count('class="row script"') == 1 and "Storyboard · Approved" in out, "a reopened script stays on the Storyboard page with its storyboard still approved")
    out = dom(WALK + "[...document.querySelectorAll('.reopen')][2].click();")
    need(">Approve storyboard<" in out and out.count(">Reopen to edit<") == 2, "an approved storyboard can be reopened too, back to Written, waiting for approval again")
    out = dom(WALK + "showStage(3);")
    need(out.count('class="row script"') == 1 and "Preview · Not started" in out and 'class="rows demos"' in out, "an approved storyboard moves the script to Preview, above the earlier demos")
    PREV = "go('Start the preview');go('Mark preview ready');"
    out = dom(WALK + PREV + "showStage(4);")
    need(out.count('class="row script"') == 1 and "SFX · Not started" in out, "a ready preview moves the script to SFX")
    out = dom(WALK + PREV + "go('Mark sound added');go('Approve sound');showStage(5);")
    need(out.count('class="row script"') == 1 and "Captions · Not started" in out, "approved sound moves the script to Captions")
    DONE6 = PREV + "go('Mark sound added');go('Approve sound');go('Mark captions added');go('Approve captions');"
    out = dom(WALK + DONE6 + "showStage(6);")
    need(out.count('class="row script"') == 1 and "Publish · Not published" in out, "approved captions move the script to Publish")
    out = dom(WALK + DONE6 + "go('Mark published');showStage(6);")
    need("Publish · Published" in out, "a published script shows Published")
    out = dom(SCRIPT)
    need("03 Blend in Drive: (needs the page's server)" in out and "05 Sound in Drive:" in out and "06 Captions in Drive:" in out and "07 Publish in Drive:" in out,
         "each later step says what is in its Drive folder (03 Blend, 05 Sound, 06 Captions, 07 Publish)")
    out = dom("remote=true;FILES={[SCRIPTS[0].folder]:{'05 Sound':['boom.wav','music.mp3']}};" + SCRIPT)
    need("05 Sound in Drive: 2 files · boom.wav, music.mp3" in out and "06 Captions in Drive: empty" in out, "files the server finds in a step folder are listed on that step, by name")
    OLD4 = ("store.set(sKey(SCRIPTS[0]),JSON.stringify({at:[1,2,1,0],on:['2026-11-01','2026-11-02','2026-11-03',null],log:[],sessions:[]}));")
    out = dom(OLD4 + "document.body.dataset.up=JSON.stringify(sRead(SCRIPTS[0]).at)+'|'+JSON.stringify(sRead(SCRIPTS[0]).on);")
    need('data-up="[1,1,2,1,0,0,0]|[null,&quot;2026-11-01&quot;,&quot;2026-11-02&quot;,&quot;2026-11-03&quot;,null,null,null]"' in out or '[1,1,2,1,0,0,0]|[null,"2026-11-01","2026-11-02","2026-11-03",null,null,null]' in out,
         "a record saved before the seven steps keeps its work: script, storyboard and animate land on Script, Storyboard and Preview, the idea counts as approved")

    # the shot screen starts empty: an empty chat, one button, the other widgets minimised
    out = dom(ROW % 0)
    need(">Generate scene<" in stage(out) and "<img" not in stage(out) and "<iframe" not in stage(out), "a shot starts empty: Blender's place holds one button, Generate scene, and nothing else")
    need(re.search(r'class="chat-log"[^>]*></div>', out) is not None and len(re.findall(r"<textarea", out)) == 1, "the chat starts empty, with one line to write in")
    need(re.search(r'<textarea[^>]*disabled', out) is not None and "The chat opens when Blender is live" in out, "with no live Blender the chat line is off and says why")
    need('<aside class="side">' in out and 'class="strip" hidden' in out and 'class="details" hidden' in out, "the chat is open; the shots and the scene details start minimised")
    need(cells(out) == 4 and ">Shot 1 of 4<" in out, "the thin shots line says which shot is open (1 of 4)")
    out = dom(ROW % 0 + TOG % 0 + TOG % 1 + TOG % 2)
    need('<aside class="side" hidden' in out and 'class="strip">' in out and '<aside class="details">' in out and ">SCENE_dock.blend<" in out,
         "each toggle flips its widget: the chat minimises, the shots and the scene details open")

    out = dom(ROW % 0 + GEN)
    need("navy_dock_f001.jpg" in stage(out) and "live Blender is not connected yet" in out, "after Generate, with no live Blender, the built scene's first picture shows and the page says Blender is not connected")
    out = dom(ROW % 0 + GEN + "document.querySelector('.b-time').dispatchEvent(new MouseEvent('click',{bubbles:true,clientX:99999}));")
    need("navy_dock_f240.jpg" in stage(out), "clicking the end of the timeline shows the last picture (frame 240)")
    out = dom(ROW % 1 + TOG % 2)
    need(cells(out) == len(src["shots"]) and src["shots"][0]["words"] in out, "the Bat Bombs screen has one cell per shot and its details show the first shot's words")
    need(re.search(r'<button class="go"[^>]*disabled', out) is not None and "No scene has been built for this storyboard yet." in out,
         "a storyboard with no built scene cannot be generated, and the page says why")

    # live mode: only when a real Blender is being streamed, and only on the shots it can open
    need("<iframe" not in dom(ROW % 0 + GEN), "with no live Blender set, no shot shows a live window")
    ONE = '{story:"navy",shot:"dock",url:"about:blank",until:"23:59"}'
    need("<iframe" not in dom(ROW % 0, ONE), "live Blender set: before Generate the shot is still empty")
    out = dom(ROW % 0 + GEN, ONE)
    need(out.count("<iframe") == 1 and "Live Blender · stops at 23:59" in out, "live Blender set: after Generate the dock shot shows one live window and says when it stops")
    out = dom(ROW % 0 + GEN + "window._f=document.querySelector('iframe');" + TOG % 0 + TOG % 1 + TOG % 2 + "document.body.dataset.same=String(window._f===document.querySelector('iframe'));", ONE)
    need('data-same="true"' in out and '<aside class="details">' in out, "minimising or opening a widget keeps the same live window (Blender is not reloaded)")
    out = dom(ROW % 0 + TOG % 1 + CELL % 1 + GEN, ONE)
    need("<iframe" not in out and "navy_officer_f001.jpg" in out, "live Blender set: a shot it cannot open shows its pictures, not the live window")

    # one live Blender for several shots, with its door for questions
    TWO_SHOTS = '{story:"navy",shots:["dock","officer"],url:"about:blank",api:"http://127.0.0.1:9",until:"23:59"}'
    TWO = (ROW % 0 + TOG % 1 + TOG % 2 + GEN + CELL % 1 + GEN + "window._f=document.querySelector('iframe');" + CELL % 0 + CELL % 1
           + "document.body.dataset.same=String(!!window._f&&window._f===document.querySelector('iframe'));")
    out = dom(TWO, TWO_SHOTS)
    need('data-same="true"' in out and out.count("<iframe") == 1 and ">SCENE_officer.blend<" in out,
         "several live shots: going between two generated shots keeps the same live window and shows the right details")
    need("cannot reach Blender" in out and "Cannot reach Blender." in out, "when the live Blender does not answer, the top line and the chat both say so")
    ANSWER = "window.fetch=(u,o)=>{(window._calls=window._calls||[]).push([u,o&&o.method,o&&o.body]);return Promise.resolve({ok:true,json:()=>Promise.resolve(%s)})};"
    out = dom(ANSWER % "{shot:'dock',opening:'officer',step:1,steps:['Saving your work on the dock scene','Loading the built officer scene','Making your own working copy']}" + TWO, TWO_SHOTS)
    need(re.search(r'class="job done"><span>Saving your work on the dock scene<', out) is not None
         and re.search(r'class="job now"><span>Loading the built officer scene<', out) is not None
         and re.search(r'class="job"><span>Making your own working copy<', out) is not None,
         "while Blender opens a shot, the page lists Blender's own steps: the finished one, the running one, the one to come")

    # the chat with the model
    TALK = ("{shot:'dock',count:0,chat:[{id:1,who:'you',text:'make the crane taller'},{id:2,who:'model',text:'Done, it is 4 m taller.'}],"
            "model:{step:'Raising the crane',busy:true}}")
    out = dom(ANSWER % TALK + ROW % 0 + GEN, TWO_SHOTS)
    need('class="msg you">make the crane taller<' in out and 'class="msg model">Done, it is 4 m taller.<' in out, "the chat shows what the animator wrote and what the model answered")
    need(re.search(r'class="job now"><span>Raising the crane<', out) is not None and ">Stop<" in out, "while the model works, the chat names its step with a moving bar and offers Stop")
    need(re.search(r'<textarea[^>]*disabled', out) is None and "Tell the model what to change" in out, "with a live Blender the chat line is on")
    out = dom(ANSWER % "{shot:'dock',count:0,chat:[]}" + ROW % 0 + GEN
              + "const b=document.querySelector('textarea');b.value='turn the officer';b.dispatchEvent(new Event('input'));document.querySelector('.arrow').click();"
              + "document.body.dataset.sent=JSON.stringify(window._calls.filter(c=>c[1]==='POST'));", TWO_SHOTS)
    need('[["http://127.0.0.1:9/say?shot=dock","POST","turn the officer"]]' in out, "sending a chat line posts exactly that text to the live Blender, for the open shot")
    out = dom(ANSWER % "{shot:'dock',count:0,chat:[{id:1,who:'you',text:'make the crane taller'}],model:null}" + ROW % 0 + GEN, TWO_SHOTS)
    need(re.search(r'class="job now"><span>Sent\. The model is picking it up<', out) is not None, "a line the model has not started on yet shows at once as sent and being picked up")
    # the instant buttons
    out = dom(ANSWER % "{shot:'dock',count:0,chat:[]}" + ROW % 0 + GEN, TWO_SHOTS)
    need(re.findall(r'class="tog" title="Right now, no AI">([^<]+)<', out) == ["Face", "Full shot", "Bones", "Play", "Undo"], "with a live Blender the top bar has the five instant buttons: Face, Full shot, Bones, Play, Undo")
    need('class="tools"' not in dom(ROW % 0 + GEN), "with no live Blender there are no instant buttons")
    need('class="tools"' not in dom(ROW % 0 + GEN, '{story:"navy",shot:"dock",url:"about:blank",until:"23:59"}'), "a live window without Blender's door has no instant buttons")
    out = dom(ANSWER % "{shot:'dock',count:0,chat:[]}" + ROW % 0 + GEN + "[...document.querySelectorAll('.tools .tog')].filter(b=>b.textContent==='Face'||b.textContent==='Bones').forEach(b=>b.click());"
              + "document.body.dataset.sent=JSON.stringify(window._calls.filter(c=>c[1]==='POST'));", TWO_SHOTS)
    need('[["http://127.0.0.1:9/tool?name=face","POST","{}"],["http://127.0.0.1:9/tool?name=bones","POST","{\\"show\\":\\"toggle\\"}"]]' in out, "pressing Face and Bones posts exactly those two tools to the live Blender")
    # a line that cannot be sent still shows, says so, and can be sent again
    TYPE = "const b=document.querySelector('textarea');b.value='turn the officer';b.dispatchEvent(new Event('input'));document.querySelector('.arrow').click();"
    out = dom("window.fetch=(u,o)=>(o&&o.method==='POST')?Promise.reject(new Error('down')):Promise.resolve({ok:true,json:()=>Promise.resolve({shot:'dock',count:0,chat:[]})});" + ROW % 0 + GEN + TYPE, TWO_SHOTS)
    need('class="msg you pending failed"' in out and ">turn the officer<" in out and "Not sent." in out and ">Try again<" in out,
         "when the line to Blender is down, the typed line still shows in the chat, says it was not sent, and offers Try again")
    out = dom("window.fetch=(u,o)=>new Promise(()=>{});" + ROW % 0 + GEN + TYPE, TWO_SHOTS)
    need('class="msg you pending"' in out and ">Sending…<" in out, "a line that is being sent shows at once in the chat, marked Sending")
    out = dom("window.fetch=(u,o)=>Promise.resolve({ok:true,json:()=>Promise.resolve({shot:'dock',count:0,chat:[{id:1,who:'you',text:'turn the officer'}]})});" + ROW % 0 + GEN + TYPE, TWO_SHOTS)
    need('class="msg you">turn the officer<' in out and 'class="msg you pending' not in out, "once Blender has the line, the chat shows Blender's own copy and the sending mark is gone")
    out = dom(ROW % 1, '{story:"navy",shots:["dock"],url:"about:blank",api:"http://127.0.0.1:9",until:"23:59"}')
    need(re.search(r'<textarea[^>]*disabled', out) is not None, "a storyboard the live Blender is not serving has its chat line off")


# 5. the quick lane: what the router will and will not carry out
sys.path.insert(0, str(ROOT / "tools" / "live"))
import router  # noqa: E402

TOOLS = {"face", "focus", "camera_view", "bones", "play", "frame", "shading", "undo", "move", "rotate", "scale"}
OBJ = [["HG_Elwood", "ARMATURE", ""], ["HG_Body", "MESH", "HG_Elwood"], ["HG_Eyes", "MESH", "HG_Elwood"], ["CAP_peak", "MESH", ""]]
RNG = [1, 240]
plan = lambda raw: router.parse_plan(raw, TOOLS, OBJ, RNG)
need(router.shortcut("Undo that!") == ([("undo", {})], "Undone.") and router.shortcut("  Show the BONES.  ")[0] == [("bones", {"show": True})],
     "the router carries out plain commands (undo, show the bones) without a model, whatever the capital letters and punctuation")
need(router.shortcut("can we fix the details in his face?") is None, "a request that only mentions the face is not taken for the Face command")
need(plan('{"say": "Turned him.", "calls": [{"tool": "rotate", "args": {"object": "HG_Elwood", "z": 90}}]}')
     == ("calls", [("rotate", {"object": "HG_Elwood", "x": 0, "y": 0, "z": 90})], "Turned him."),
     "a good answer from the small model becomes a checked tool call with every axis filled in")
need(plan('{"say": "Moved him.", "calls": [{"tool": "move", "args": {"object": "HG_Elwood", "x": "-1", "y": 0, "z": "0"}}]}')
     == ("calls", [("move", {"object": "HG_Elwood", "x": -1.0, "y": 0, "z": 0.0})], "Moved him."), "a number the small model wrote as text (\"-1\") is still read as a number")
need(plan('{"say": "x", "calls": [{"tool": "move", "args": {"object": "HG_Elwood", "x": "left"}}]}')[0] == "handoff", "a number written as a word is refused")
need(plan('{"answer": "Frame 1 of 240."}') == ("calls", [], "Frame 1 of 240."), "a plain question the scene facts answer is answered without any tool")
need(plan('Sure!\n```json\n{"say": "ok", "calls": [{"tool": "face", "args": {}}]}\n```')[0] == "calls", "an answer wrapped in other words or a code block is still read")
need(plan('{"handoff": "it asks to change colours"}') == ("handoff", "it asks to change colours"), "the small model can hand a line to the big assistant")
for raw, why in (('{"say": "x", "calls": [{"tool": "delete_all", "args": {}}]}', "a tool that does not exist"),
                 ('{"say": "x", "calls": [{"tool": "move", "args": {"object": "Ghost", "x": 1}}]}', "an object that is not in the shot"),
                 ('{"say": "x", "calls": [{"tool": "move", "args": {"object": "HG_Body", "x": 9000}}]}', "a move of 9000 metres"),
                 ('{"say": "x", "calls": [{"tool": "frame", "args": {"n": 5000}}]}', "a frame outside the timeline"),
                 ('{"say": "x", "calls": []}', "no calls at all"),
                 ("I think you should zoom in.", "no JSON at all")):
    need(plan(raw)[0] == "handoff", f"the router refuses and hands over: {why}")
prompt = router.prompt_for("turn him left", [{"who": "you", "text": "hi"}], {"shot": "officer", "scene": {"objects": OBJ, "frame": 1, "range": RNG}, "tools": [{"name": "face", "does": "x", "args": {}}], "chat": []})
need("HG_Elwood (ARMATURE)" in prompt and "turn him left" in prompt and "handoff" in prompt, "the prompt to the small model carries the scene's objects, the instruction and the way out")


# 6. the Drive folders exist, one per script, each with its eight step folders and a record
DRIVE = Path.home() / "Library/CloudStorage/GoogleDrive-nikolaskoundouros@gmail.com/My Drive/Art Of War Productions"
SUB = ["00 Record", "01 Script", "02 Storyboard", "03 Blend", "04 Clips and final video", "05 Sound", "06 Captions", "07 Publish"]
if DRIVE.is_dir():
    missing = [r["folder"] for r in reg if not all((DRIVE / r["folder"] / sub).is_dir() for sub in SUB)
               or not (DRIVE / r["folder"] / "00 Record" / "Record.txt").is_file()]
    need(not missing, "Drive: every one of the 26 scripts has its folder, its eight step folders and a record" + (f" (missing: {missing[:3]})" if missing else ""))
    need(sorted(p.name for p in DRIVE.iterdir() if p.is_dir()) == sorted(r["folder"] for r in reg), "Drive: 'Art Of War Productions' holds exactly the 26 script folders and nothing else")
else:
    need(False, "Drive: 'Art Of War Productions' exists on this Mac")


# 7. the script itself: imported once from its doc, shown in an editable box, every change recorded
docs = {d["id"]: d for d in json.loads((ROOT / "data" / "import" / "docs.json").read_text())}
need(all(r["doc"] in docs and len(r["lines"]) >= 3 for r in reg), "every one of the 26 scripts has its text and the doc it came from")
bomb = next(r for r in reg if r["title"] == "He Carried the Burning Bomb")
src_tab = next(t for t in docs[bomb["doc"]]["tabs"] if t["title"] == "Version 1")["paragraphs"]
need(bomb["lines"][:6] == src_tab[11:17] and src_tab[10].startswith("Nick") and "Clean Copy" in bomb["source"],
     "He Carried the Burning Bomb: the text is word for word the lines under the doc's last heading (Nick's revision), not the first draft above it")
OWN = "clearing the smoke from the plane helping the pilot save the plane from crashing into the ground!"
share_text = (ROOT / "data" / "import" / "chatgpt_share.html").read_text().replace("\\u0026", "&")
need(bomb["lines"][-1] == OWN and share_text.count(OWN) >= 2 and src_tab[17] != OWN,
     "He Carried the Burning Bomb ends with Nick's own sentence, copied from his ChatGPT chat, not the clean copy's changed one")
saved = json.loads((ROOT / "data" / "work" / f"{bomb['folder']}.json").read_text()) if (ROOT / "data" / "work" / f"{bomb['folder']}.json").exists() else {}
need(OWN in saved.get("mine", []) and saved.get("text", [""])[-1] == OWN and any(c.get("after") == OWN for c in saved.get("log", [])),
     "his sentence counts as his own edit (the chat will not change it), and putting it back is in his change log")
need(all(r["lines"][0] != r["title"] and not any(l.strip().strip("*").strip() == r["title"] for l in r["lines"]) for r in reg), "no script's text starts with its own title line")
kings = {r["title"]: r["doc"][:10] for r in reg if r["title"].startswith("The King Who Ate Poison")}
need(kings == {"The King Who Ate Poison": "14qAw7-mEx", "The King Who Ate Poison (1)": "1TJDc1FhzI"}, "the two same-named King scripts each point at their own doc")
if DRIVE.is_dir():
    need(all((DRIVE / r["folder"] / "01 Script" / "Script.txt").is_file() for r in reg), "Drive: every script folder has its text in 01 Script/Script.txt")

if Path(CHROME).exists():
    BOMB = "[...document.querySelectorAll('.row.script')].find(b=>b.textContent.startsWith('He Carried the Burning Bomb')).click();"
    out = dom(BOMB)
    need('class="scriptbox" contenteditable="true"' in out and out.count("<p>") >= 7 and "<p>" + bomb["lines"][0] + "</p>" in out.split('class="scriptbox"')[1],
         "a script's page shows the actual script, line by line, in a box you can type in")
    marks = re.findall(r'<button class="tog" title="[^"]*">(?:<i [^>]*></i>)?([^<]+)</button>', out.split('class="marks"')[1].split('class="scriptbox"')[0])
    need(marks == ["Cut", "My words", "Fluff", "Flow", "Sense", "Keep", "Clear"], "above the script: the marks Cut, My words, Fluff, Flow, Sense, Keep, and Clear")
    need("No changes yet. Everything you change here is recorded." in out, "an untouched script says nothing has changed yet")
    TYPE_ = BOMB + "const bx=document.querySelector('.scriptbox');bx.children[2].textContent='and smoke filled the cockpit,';bx.dispatchEvent(new Event('input'));"
    out = dom(TYPE_)
    need("1 change · 1 work session" in out and "Edit · line 3" in out and "<s>and smoke filled the cockpit until the pilot couldn’t see anything,</s>" in out and "<span>and smoke filled the cockpit,</span>" in out,
         "typing in the script records one change after a pause: the line, what it said before and what it says now, in work session 1")
    SELECT = "const bx=document.querySelector('.scriptbox');const r=document.createRange();r.selectNodeContents(bx.children[3]);const sel=getSelection();sel.removeAllRanges();sel.addRange(r);bx.focus();sel.removeAllRanges();sel.addRange(r);"
    out = dom(BOMB + SELECT + "[...document.querySelectorAll('.marks .tog')].find(b=>b.textContent==='Cut').click();")
    need("<strike>but then the plane began diving,</strike>" in out.split('class="scriptbox"')[1] and "Cut · line 4" in out and "~~but then the plane began diving,~~" in out,
         "Cut strikes the selected words in the box and is recorded as a cut on that line")
    out = dom(BOMB + SELECT + "[...document.querySelectorAll('.marks .tog')].find(b=>b.textContent==='Fluff').click();")
    need("Fluff · line 4" in out and "[fluff: but then the plane began diving,]" in out, "Fluff highlights the selected words and is recorded as fluff on that line")
    out = dom(TYPE_ + "setTimeout(()=>{document.querySelector('.stepbox .go').click()},2500);")
    need('class="scriptbox" contenteditable="false"' in out and 'class="marks"' not in out and ">Reopen to edit<" in out and "Approve script" in out.split('class="changes"')[1] and "and smoke filled the cockpit," in out.split('class="scriptbox"')[1],
         "approving keeps the edited text, locks the box, and the approval itself is in the change list")
    out = dom(TYPE_ + "setTimeout(()=>{document.querySelector('.stepbox .go').click();document.querySelectorAll('.reopen')[1].click()},2500);")
    need('class="scriptbox" contenteditable="true"' in out and "Reopen script" in out.split('class="changes"')[1], "Reopen to edit unlocks the box again and is recorded too")
    out = dom(TYPE_ + "setTimeout(()=>{showStage(0);document.body.dataset.kept=JSON.stringify(sRead(SCRIPTS.find(x=>x.title==='He Carried the Burning Bomb')).text.slice(2,3))},100);")
    need('["and smoke filled the cockpit,"]' in out, "leaving the page right after typing still records the change (nothing typed is lost)")

# 7b. the chat on the script page
if Path(CHROME).exists():
    NEW = bomb["lines"][:6] + ["and the smoke cleared just before the plane hit the ground"]
    SERVER = ("remote=true;window._calls=[];window.fetch=(u,o)=>{window._calls.push([String(u),o&&o.body]);"
              "return Promise.resolve({ok:true,json:()=>Promise.resolve(String(u).startsWith('api/chat')?%s:{ok:true})})};")
    ASK = "const t=document.querySelector('.stepbox textarea');t.value='put my last sentence back';t.dispatchEvent(new Event('input'));document.querySelector('.stepbox .arrow').click();"
    out = dom(BOMB)
    need(re.search(r'<textarea[^>]*disabled[^>]*placeholder="The chat needs the page\'s server"', out) is not None or
         re.search(r'<textarea[^>]*placeholder="The chat needs the page\'s server"[^>]*disabled', out) is not None, "without the page's server the chat line is off and says why")
    out = dom(SERVER % json.dumps({"say": "I put your last sentence back.", "lines": NEW}) + BOMB + ASK)
    box_ = out.split('class="scriptbox"')[1].split("</div>")[0]
    need('class="msg you">put my last sentence back<' in out and "<span>I put your last sentence back.</span>" in out, "the chat shows what the writer asked and what PlotPointe answered")
    need(NEW[-1] in box_ and bomb["lines"][-1] not in box_, "PlotPointe's edit lands in the script box itself")
    need("PlotPointe · Chat edit · line 7" in out and f"<s>{bomb['lines'][-1]}</s>" in out.split('class="talk"')[1] and ">Undo<" in out,
         "the edit is recorded as PlotPointe's change on that line, shown as before and after in the chat, with Undo")
    sent = out.split('data-sent="')[1].split('"')[0] if 'data-sent="' in out else ""
    out = dom(SERVER % json.dumps({"say": "I put your last sentence back.", "lines": NEW}) + BOMB + ASK
              + "setTimeout(()=>{document.body.dataset.sent=JSON.stringify(JSON.parse(window._calls.find(c=>c[0].startsWith('api/chat'))[1]).lines.length+'|'+JSON.parse(window._calls.find(c=>c[0].startsWith('api/chat'))[1]).text)},300);")
    need('data-sent="&quot;7|put my last sentence back&quot;"' in out or 'data-sent="\\"7|put my last sentence back\\""' in out or '"7|put my last sentence back"' in out,
         "the chat sends the writer's message together with the script as it stands (7 lines)")
    out = dom(SERVER % json.dumps({"say": "I put your last sentence back.", "lines": NEW}) + BOMB + ASK + "setTimeout(()=>{[...document.querySelectorAll('.talk .text')].find(b=>b.textContent==='Undo').click()},300);")
    box_ = out.split('class="scriptbox"')[1].split("</div>")[0]
    need(bomb["lines"][-1] in box_ and NEW[-1] not in box_ and ">Undone<" in out and "Undo · line 7" in out, "Undo puts the script back as it was and is recorded too")
    # "never change my edits": a chat change to a line the writer edited is only a suggestion, applied on the writer's click
    MINE = BOMB + "const bx=document.querySelector('.scriptbox');bx.children[6].textContent='and the smoke cleared just before the plane hit the ground!';bx.dispatchEvent(new Event('input'));"
    ASK2 = "setTimeout(()=>{" + ASK + "},2300);"
    ALTERED = bomb["lines"][:6] + ["clearing the smoke so the pilot could recover the plane."]
    out = dom(SERVER % json.dumps({"say": "I tightened the last line.", "lines": ALTERED}) + MINE + ASK2)
    box_ = out.split('class="scriptbox"')[1].split("</div>")[0]
    sent = re.search(r'"mine":\[([^\]]*)\]', html.unescape(out)) if False else None
    need("just before the plane hit the ground!" in box_ and "could recover the plane" not in box_ and "This changes your own edit, so it is only a suggestion" in out and ">Apply<" in out,
         "a chat change to a line the writer edited is NOT applied: it shows as a suggestion with Apply (\"never change my edits\")")
    out = dom(SERVER % json.dumps({"say": "I tightened the last line.", "lines": ALTERED}) + MINE + ASK2 + "setTimeout(()=>{[...document.querySelectorAll('.talk .text')].find(b=>b.textContent==='Apply').click()},2700);")
    box_ = out.split('class="scriptbox"')[1].split("</div>")[0]
    need("could recover the plane" in box_ and "Chat edit (applied by you)" in out, "Apply puts the suggestion in, and the log says the writer applied it")
    OTHER = ["He carried a burning bomb with his bare hands,"] + bomb["lines"][1:6] + ["and the smoke cleared just before the plane hit the ground!"]
    out = dom(SERVER % json.dumps({"say": "I shortened the first line.", "lines": OTHER}) + MINE + ASK2)
    box_ = out.split('class="scriptbox"')[1].split("</div>")[0]
    need("<p>He carried a burning bomb with his bare hands,</p>" in box_ and "just before the plane hit the ground!" in box_ and "only a suggestion" not in out.split('class="talk"')[1].split('class="input"')[0],
         "a chat change that leaves the writer's edits alone goes straight into the script")
    out = dom(SERVER % json.dumps({"say": "ok", "lines": None}) + MINE + ASK2 + "setTimeout(()=>{document.body.dataset.mine=JSON.parse(window._calls.find(c=>c[0].startsWith('api/chat'))[1]).mine.join('|')},2700);")
    need('data-mine="and the smoke cleared just before the plane hit the ground!"' in out, "the chat tells the model which lines are the writer's own edits")
    out = dom(SERVER % json.dumps({"say": "It was already clear.", "lines": None}) + BOMB + ASK)
    need("<span>It was already clear.</span>" in out and "No changes yet" in out and ">Undo<" not in out, "a question gets an answer and leaves the script alone")
    out = dom(SERVER % json.dumps({"error": "the model did not answer in time"}) + BOMB + ASK)
    need("I could not do that: the model did not answer in time." in out and "No changes yet" in out, "when the model fails the chat says so and nothing changes")
    out = dom("remote=true;" + BOMB + "document.querySelector('.stepbox .go').click();")
    need(re.search(r'placeholder="Reopen the script to change it"', out) is not None, "on an approved script the chat line is off until the script is reopened")

# 7c. the storyboard step and the demo page
sbs = json.loads((ROOT / "data" / "storyboards.js").read_text().split("=", 1)[1].rstrip().rstrip(";"))
raw_sb = json.loads((ROOT / "data" / "import" / "storyboards_raw.json").read_text())
cap = next(r for r in reg if r["title"] == "The Captain Who Sank His Own Ship")
need(sorted(sb["title"] for sb in sbs.values()) == ["The Bat Bombs", "The Captain Who Sank His Own Ship"], "two scripts have a storyboard: the two PlotPointe made whose words match the script word for word")
need([x["words"] for x in sbs[cap["doc"]]["shots"]] == [s["words"] for s in raw_sb[cap["doc"]]["shots"]] and all(x["image"] == (s.get("image") or {}).get("url") for x, s in zip(sbs[cap["doc"]]["shots"], raw_sb[cap["doc"]]["shots"])),
     "the Captain's 19 shots carry PlotPointe's own words and pictures, unchanged")
if DRIVE.is_dir():
    need(all((DRIVE / r["folder"] / "02 Storyboard" / "Storyboard.txt").is_file() for r in reg if r["doc"] in sbs), "Drive: both storyboards are in their scripts' 02 Storyboard folders")
if Path(CHROME).exists():
    CAP = "[...document.querySelectorAll('.row.script')].find(b=>b.textContent.startsWith('The Captain Who Sank')).click();"
    out = dom(CAP)
    need(out.count('<img src="https://d8j0ntlcm91z4.cloudfront.net', 0, out.find('class="sbopen"')) >= 8 and ">Open the storyboard · 19 shots<" in out, "the script page shows the storyboard's first shots and opens the storyboard")
    out = dom("[...document.querySelectorAll('.row.script')].find(b=>b.textContent.startsWith('He Carried')).click();")
    need("No storyboard yet." in out and "waits for your go" in out, "a script with no storyboard says so, and that making one waits for a go")
    out = dom(CAP + "document.querySelector('.sbopen').click();")
    need(out.count('class="shot"') == 19 and 'aria-current="page">Storyboard<' in out and "Starts when the script is approved" in out, "the storyboard page shows all 19 shots, marks Storyboard in the sidebar, and waits for the script's approval")
    out = dom(CAP + "document.querySelector('.stepbox .go').click();document.querySelector('.sbopen').click();document.querySelectorAll('.shot')[4].click();"
              "const n=document.querySelector('.shotinfo textarea');n.value='make him look older';n.dispatchEvent(new Event('change'));")
    need('class="shotdetail"' in out and "Shot 5 · note" in out,
         "a shot opens big with its words, cast and prompt, and a note on it is kept")
    out = dom(CAP + "document.querySelector('.stepbox .go').click();document.querySelector('.sbopen').click();[...document.querySelectorAll('.stepbox .go')].find(b=>b.textContent==='Mark storyboard written').click();[...document.querySelectorAll('.stepbox .go')].find(b=>b.textContent==='Approve storyboard').click();")
    need("Approved · 20" in out.split('class="stepbox')[1] and ">Reopen<" in out, "the storyboard can be approved from its own page, and reopened")
    out = dom("location.hash='#storyboard=' + encodeURIComponent('The Captain Who Sank His Own Ship');route();")
    need(out.count('class="shot"') == 19, "a link straight to a script's storyboard opens it (the demo page uses these links)")
    demo = (ROOT / "demo.html").read_text()
    probe = ROOT / "_demo_probe.html"
    probe.write_text(demo)
    try:
        shot_ = lambda q, k: html.unescape(subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--virtual-time-budget=3000", "--dump-dom", probe.as_uri() + q + f"#{k}"], capture_output=True, text=True, timeout=90).stdout)
        pages = [shot_("?script=" + quote(cap["folder"]), k) for k in range(1, 9)]
        fresh_ = [shot_("?fresh", k) for k in range(1, 9)]
    finally:
        probe.unlink()
    CHECKS = ["Idea", "Script", "Storyboard", "Preview", "SFX", "Captions", "Publish"]
    bars = [d.split('id="bar"')[1].split("</nav>")[0] for d in pages]
    need("Welcome to PlotPointe" in pages[0] and re.findall(r"<b>([^<]+)</b>", pages[0].split('class="path intro"')[1].split('class="facts"')[0]) == CHECKS and ">Get started<" in pages[0],
         "page 1 is the introduction: Welcome to PlotPointe, the seven steps in order (Idea, Script, Storyboard, Preview, SFX, Captions, Publish), and Get started")
    need(all(re.findall(r"<span>([^<]+)</span>", b) == CHECKS for b in bars) and all(b.count('class="past"') == max(k - 1, 0) and b.count('class="now"') == (1 if k else 0) for k, b in enumerate(bars)),
         "every page has the progress bar on top with the seven steps; on step k the steps before it are done and step k is the current one")
    need(all(f"Step {k} of 7 · {name}" in pages[k] and f'id="where">Step {k} of 7<' in pages[k] for k, name in enumerate(CHECKS, 1)), "each of pages 2 to 8 is one step, numbered 1 to 7, and the top says which")
    flat = lambda t: " ".join(re.sub(r"<[^>]+>", "", t).split())
    need("This walkthrough starts empty" in fresh_[0] and "Captain" not in "".join(fresh_) and all(">Not started<" in d.split('id="app"')[1] for d in fresh_[1:])
         and "No idea written yet." in fresh_[1] and "No script written yet." in fresh_[2] and "No storyboard yet." in fresh_[3] and 'href="animate.html#new"' in fresh_[1],
         "a fresh demo starts empty: no other story in it, every step Not started, and each step links to New idea in PlotPointe")
    need(all(flat(l.replace("~~", "").replace("**", ""))[:40] in flat(pages[2]) for l in cap["lines"]) and pages[3].count('alt="Shot ') == 19, "the demo shows the Captain's real script and all 19 storyboard pictures")
    need(all(any(f'href="animate.html#{k}' in d for d in pages) for k in ("script=", "storyboard=", "desk=navy", "stage=0")), "the demo links into the platform: the script, the storyboard, the shot desk and every story")
    need("This story's preview is not made yet" in pages[4] and "No sound yet." in pages[5] and "No captions yet." in pages[6] and "The finished video is not made yet." in pages[7],
         "the demo says plainly what is not made yet: the preview, the sound, the captions and the finished video")
    need(all("—" not in d.split("<body")[1] and "–" not in d.split("<body")[1] for d in pages), "no long dashes anywhere on the demo")

# 7d. the New script button
if Path(CHROME).exists():
    out = dom("")
    need(re.search(r'<button class="go newbtn"[^>]*disabled', out) is not None, "without the page's server, New idea is off")
    NEWSTUB = ("remote=true;window._calls=[];window.fetch=(u,o)=>{window._calls.push([String(u),o&&o.body]);return Promise.resolve({ok:true,json:()=>Promise.resolve(String(u)==='api/new'?"
               "{script:{title:'Test Crossing',folder:'Test Crossing',doc:null,source:'written in the platform on 2026-11-13',lines:['He swam the river at night,','and nobody saw him.'],started:'2026-11-13',made:'platform'},"
               "state:{at:[0,0,0,0,0,0,0],on:[null,null,null,null,null,null,null],idea:'A man swims a river at night to warn his town.',text:['He swam the river at night,','and nobody saw him.'],sessions:[],log:[{at:1,who:'you',what:'Script written in the platform',line:1,before:'',after:'x'}]}}:{ok:true})})};showStage(0);")
    out = dom(NEWSTUB + "document.querySelector('.newbtn').click();")
    need('<h1>New idea</h1>' in out and 'class="newtitle"' in out and 'class="newtext newidea"' in out and 'class="newtext"' in out and ">Create<" in out, "New idea opens a form: a title, the idea, the script (can wait), Create")
    out = dom(NEWSTUB + "document.querySelector('.newbtn').click();document.querySelector('.go').click();")
    need("Give the script a title." in out, "Create with no title says what is missing")
    MAKE = ("document.querySelector('.newbtn').click();document.querySelector('.newtitle').value='Test Crossing';document.querySelector('.newidea').value='A man swims a river at night to warn his town.';"
            "document.querySelector('.newtext:not(.newidea)').value='He swam the river at night,\\n\\nand nobody saw him.';"
            "[...document.querySelectorAll('.go')].find(b=>b.textContent==='Create').click();document.body.dataset.sent=window._calls.find(c=>c[0]==='api/new')[1];")
    out = dom(NEWSTUB + MAKE + "setTimeout(()=>{document.body.dataset.idea=document.querySelector('.ideabox').value},200);")
    need('<h1>Test Crossing</h1>' in out and 'data-idea="A man swims a river at night to warn his town."' in out and ">Approve idea<" in out
         and 'class="scriptbox"' not in out and '"idea":"A man swims a river at night to warn his town."' in out and '"lines":["He swam the river at night,","and nobody saw him."]' in out,
         "Create sends the title, the idea and the lines, then opens the new page on its idea, waiting for approval; the script waits for the idea")
    out = dom(NEWSTUB + MAKE + "setTimeout(()=>[...document.querySelectorAll('.go')].find(b=>b.textContent==='Approve idea').click(),200);")
    need("<p>He swam the river at night,</p>" in out.split('class="scriptbox"')[1] and ">Approve script<" in out and "Script written in the platform" in out,
         "once the idea is approved, the script step opens with the text and its first change")

# 8. the save server: one script's work lands in PlotPointe's copy and in its Drive folder; nothing else is accepted
import shutil
import tempfile
sys.path.insert(0, str(ROOT / "tools"))
import serve  # noqa: E402

tmp = Path(tempfile.mkdtemp())
try:
    folder = bomb["folder"]
    (tmp / "drive" / folder).mkdir(parents=True)
    state = {"at": [1, 1, 0, 0, 0, 0, 0], "on": ["2026-11-12", "2026-11-13", None, None, None, None, None], "log": [{"at": 1794560000000, "who": "you", "what": "Cut", "line": 4, "before": "a", "after": "~~a~~"}],
             "sessions": [{"start": 1794560000000, "end": 1794560300000, "changes": 1}]}
    written = serve.save(folder, {"state": state, "text": ["line one,", "~~a~~"]}, work=tmp / "work", drive=tmp / "drive", scripts={folder: bomb})
    need(json.loads((tmp / "work" / f"{folder}.json").read_text()) == state, "the save server keeps the script's work exactly as sent")
    need((tmp / "drive" / folder / "01 Script" / "Script.txt").read_text() == "He Carried the Burning Bomb\n\nline one,\n~~a~~\n", "the save server writes the latest text into the script's Drive folder")
    rec = (tmp / "drive" / folder / "00 Record" / "Record.txt").read_text()
    need("STEP 1  Idea        Approved  (2026-11-12)" in rec and "STEP 2  Script      Approved  (2026-11-13)" in rec and "STEP 7  Publish     Not published" in rec and "Work sessions: 1   Changes: 1" in rec and "Session 1:" in rec, "the Drive record shows the step's state and date and the work sessions")
    need(json.loads((tmp / "drive" / folder / "00 Record" / "changes.jsonl").read_text().splitlines()[0])["what"] == "Cut", "the Drive record keeps every change, one per line")
    need(serve.all_states(work=tmp / "work", scripts={folder: bomb}) == {folder: state}, "the saved work is what the page gets back when it loads")
    talk = {**state, "chat": [{"at": 1, "who": "you", "text": "cut it"}, {"at": 2, "who": "PlotPointe", "text": "Done.", "change": {"line": 2, "before": "a", "after": ""}, "was": ["x"]}]}
    serve.save(folder, {"state": talk, "text": ["line one,"]}, work=tmp / "work", drive=tmp / "drive", scripts={folder: bomb})
    chat_file = [json.loads(l) for l in (tmp / "drive" / folder / "00 Record" / "chat.jsonl").read_text().splitlines()]
    need([m["who"] for m in chat_file] == ["you", "PlotPointe"] and chat_file[1]["change"]["line"] == 2 and "was" not in chat_file[1], "the Drive record keeps the chat, each line with the change it made")
    share = (ROOT / "data" / "import" / "chatgpt_share.html").read_text().replace("\\u0026", "&").replace("**", "")
    taught = json.loads((ROOT / "data" / "lessons.json").read_text())
    tab_lines = next(t for t in docs[bomb["doc"]]["tabs"] if t["title"].startswith("Feedback"))["paragraphs"]
    need(taught["source"] == "https://chatgpt.com/share/6af72603-4458-83eb-a6e6-9b6811643870" and len(taught["lessons"]) == 6
         and all(l["text"] in share or l["text"] in tab_lines for l in taught["lessons"]) and taught["lessons"][0]["text"] == "never change my edits.",
         "the chat's 6 lessons all come word for word from that ChatGPT chat (or the lessons tab it wrote), starting with \"never change my edits.\"")
    pasted = (ROOT / "data" / "import" / "rules_pasted.txt").read_text()
    need(taught["rules"]["text"] in pasted and taught["rules"]["text"].startswith("The central principle") and len(re.findall(r"^\* ", taught["rules"]["text"], re.M)) == 91
         and "Never change my edits without being asked." in taught["rules"]["text"], "the full rules Nick pasted are kept word for word: 10 sections, 91 rule lines, the editing rules included")
    p3 = serve.chat_prompt(bomb, bomb["lines"], [], "cut it", taught["lessons"], [], serve.script_rules())
    need("Write in language a 9-10-year-old can understand." in p3 and "Target length: 100-150 words." in p3 and "Is the story immediately understandable?" in p3, "the chat model is given all of the pasted rules")
    p2 = serve.chat_prompt(bomb, bomb["lines"], [], "cut it", taught["lessons"], [bomb["lines"][2]])
    need('"never change my edits." (Nick)' in p2 and taught["lessons"][3]["text"] in p2 and f"3. {bomb['lines'][2]}   [the writer's own edit]" in p2 and "[the writer's own edit]" not in p2.split("\n3. ")[0].split("The script as it stands")[1],
         "the model is given the 6 lessons in their own words, and the writer's edited lines are marked (and only those)")
    prompt = serve.chat_prompt(bomb, bomb["lines"], [{"who": "you", "text": "hi"}], "cut the last line")
    need(f"7. {bomb['lines'][-1]}" in prompt and '"cut the last line"' in prompt, "the model is given the numbered script as it stands and the writer's message")
    need(not any(w in prompt for w in ("House rules", "Answer the questions a viewer asks", "supposedly", "No years", "One story, one topic")) and not (ROOT / "data" / "house_rules.json").exists()
         and "house_rules" not in (ROOT / "tools" / "serve.py").read_text(), "none of PlotPointe's 15 lessons, hedges or year rule reach the chat, and the copy of that rules file is gone")
    good = serve.parse_reply('Here you go:\n{"say": "Cut it.", "lines": ["a,", " b "]}', ["a,", "b", "c"])
    need(good == {"say": "Cut it.", "lines": ["a,", "b"]}, "a good answer from the model is read, even wrapped in other words")
    need(serve.parse_reply('{"say": "Nothing to change.", "lines": ["a,", "b"]}', ["a,", "b"])["lines"] is None and serve.parse_reply('{"say": "Because.", "lines": null}', ["a"])["lines"] is None,
         "an answer that leaves the script as it is counts as no change")
    for raw, why in (("I think you should cut it.", "no JSON"), ('{"lines": ["a"]}', "no reply text"), ('{"say": "x", "lines": "a"}', "a script that is not lines"), ('{"say": "x", "lines": []}', "an empty script")):
        try:
            serve.parse_reply(raw, ["a"])
            need(False, f"the chat refuses a model answer with {why}")
        except ValueError:
            need(True, f"the chat refuses a model answer with {why}")
    need(serve.chat(folder, {"text": "cut b", "lines": ["a,", "b"]}, scripts={folder: bomb}, ask=lambda prompt: '{"say": "Cut.", "lines": ["a,"]}') == {"say": "Cut.", "lines": ["a,"]},
         "one chat message goes in, the model's reply and new script come out")
    for body, why in (({"text": "", "lines": ["a"]}, "an empty message"), ({"text": "x", "lines": []}, "no script")):
        try:
            serve.chat(folder, body, scripts={folder: bomb}, ask=lambda prompt: "{}")
            need(False, f"the chat refuses {why}")
        except ValueError:
            need(True, f"the chat refuses {why}")
    # a new script written in the platform
    root2 = tmp / "root"; (root2 / "data").mkdir(parents=True)
    (root2 / "data" / "scripts.js").write_text((ROOT / "data" / "scripts.js").read_text())
    (tmp / "drive2").mkdir()
    made = serve.new_script({"title": "  The  Test — Crossing ", "lines": ["He swam the river at night,", "", " and nobody saw him. "]}, root=root2, drive=tmp / "drive2", work=tmp / "work2")
    newreg = json.loads((root2 / "data" / "scripts.js").read_text().split("=", 1)[1].rstrip().rstrip(";"))
    nr = next(r for r in newreg if r["title"] == "The Test — Crossing")
    need(nr["folder"] == "The Test - Crossing" and nr["lines"] == ["He swam the river at night,", "and nobody saw him."] and nr["made"] == "platform" and nr["doc"] is None and len(newreg) == len(reg) + 1,
         "New script: the title is tidied, the folder name has no long dash, the text keeps its lines, and it joins the script list")
    need(all((tmp / "drive2" / "The Test - Crossing" / sub).is_dir() for sub in serve.STEP_FOLDERS) and (tmp / "drive2" / "The Test - Crossing" / "01 Script" / "Script.txt").read_text().endswith("and nobody saw him.\n")
         and "Script written in the platform" in (tmp / "drive2" / "The Test - Crossing" / "00 Record" / "changes.jsonl").read_text(),
         "New script: its Drive folder has all 8 step folders, the text, and 'Script written in the platform' as its first change")
    for body, why in (({"title": "", "lines": ["a"]}, "no title"), ({"title": "x", "lines": ["", " "]}, "no text"), ({"title": "the test - crossing", "lines": ["a"]}, "a title that already exists"), ({"title": "y", "lines": "a"}, "text that is not lines")):
        try:
            serve.new_script(body, root=root2, drive=tmp / "drive2", work=tmp / "work2")
            need(False, f"New script refuses {why}")
        except ValueError:
            need(True, f"New script refuses {why}")
    idea_only = serve.new_script({"title": "Only An Idea", "idea": " A pilot  lands on a frozen lake. "}, root=root2, drive=tmp / "drive2", work=tmp / "work2")
    need(idea_only["script"]["idea"] == "A pilot lands on a frozen lake." and idea_only["script"]["lines"] == [] and idea_only["state"]["at"] == [0] * 7
         and "Idea:     A pilot lands on a frozen lake." in (tmp / "drive2" / "Only An Idea" / "00 Record" / "Record.txt").read_text(),
         "New idea: an idea with no script yet is accepted, starts at step 1 of 7, and its idea is in the Drive record")
    old = {"at": [1, 2, 1, 0], "on": ["2026-11-01", "2026-11-02", "2026-11-03", None], "re": ["2026-11-04", None, None, None], "log": [], "sessions": []}
    up = serve.upgrade(dict(old))
    need(up["at"] == [1, 1, 2, 1, 0, 0, 0] and up["on"] == [None, "2026-11-01", "2026-11-02", "2026-11-03", None, None, None] and up["re"][1] == "2026-11-04",
         "a record saved before the seven steps is read into them: script, storyboard, animate and publish keep their place, the idea counts as approved")
    sdrive = tmp / "sdrive"; (sdrive / folder / "05 Sound").mkdir(parents=True); (sdrive / folder / "05 Sound" / "boom.wav").write_bytes(b"RIFF")
    (sdrive / folder / "05 Sound" / "notes.py").write_text("x"); (sdrive / folder / "01 Script").mkdir(); (sdrive / folder / "01 Script" / "a.txt").write_text("x")
    need(serve.step_files(drive=sdrive, scripts={folder: bomb}) == {folder: {"05 Sound": ["boom.wav"]}}, "the server lists the sound, picture, video and caption files in a script's step folders, nothing else")
    q = lambda **k: {a: [b] for a, b in k.items()}
    need(serve.step_file(q(folder=folder, step="05 Sound", name="boom.wav"), drive=sdrive, scripts={folder: bomb}) == sdrive / folder / "05 Sound" / "boom.wav"
         and all(serve.step_file(x, drive=sdrive, scripts={folder: bomb}) is None for x in (q(folder=folder, step="05 Sound", name="notes.py"), q(folder=folder, step="05 Sound", name="../../x.wav"),
                 q(folder="../x", step="05 Sound", name="boom.wav"), q(folder=folder, step="01 Script", name="a.txt"), q(folder=folder, step="05 Sound", name="gone.wav"))),
         "the server hands out one known file from a step folder, and refuses other types, other folders and paths that climb out")
    mf = (ROOT / "tools" / "make_folders.py").read_text()
    need('r.get("made") == "platform"' in mf, "a re-import keeps the scripts written in the platform")
    for bad, why in ((("../../etc", {"state": state, "text": []}), "a folder that is not a script"), ((folder, {"state": {"at": [1]}, "text": []}), "a broken state"), ((folder, {"state": state, "text": "x"}), "text that is not lines")):
        try:
            serve.save(bad[0], bad[1], work=tmp / "work", drive=tmp / "drive", scripts={folder: bomb})
            need(False, f"the save server refuses {why}")
        except ValueError:
            need(True, f"the save server refuses {why}")
finally:
    shutil.rmtree(tmp)

print()
print("FAILED: " + str(len(fails)) if fails else "ALL PASS")
sys.exit(1 if fails else 0)
