"""Turn the source files into the data the Animate page reads.

Two storyboards, both copied as they are, nothing rewritten:

  navy        the four scenes built on 12 Nov 2026 (aow-modules/navy_preview on the 3D System box):
              data/navy/storyboard_*.png          the storyboard pictures
              data/navy/spec_*.json               what each scene was asked to be
              data/navy/build_b_*.json            what the builder made (set, officer, lights, camera zoom)
              data/navy/check_c_*.json            what the checker found when it opened the scene from a fresh folder
              data/navy/preview_c_*_f001/120/240.png   three pictures of the built scene
  bat_bombs   one PlotPointe storyboard exactly as PlotPointe saved it (research/visuals/<doc id>.json)

Out: data/img/*.jpg   smaller copies the page loads fast
     data/story.js    window.STORIES = [...]; a plain script so the page also opens straight from the file
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "data" / "img"
NAVY = ROOT / "data" / "navy"
WORDS_PER_SECOND = 3.9   # the same number PlotPointe uses in telegram/visuals.py
NAVY_ORDER = [("dock", "storyboard_dock.png"), ("officer", "storyboard_officer.png"),
              ("cruiser", "storyboard_cruiser.png"), ("carrier", "storyboard_carrier_battleship.png")]
FRAMES = [1, 120, 240]   # the three frames the checker rendered


def jpg(src, stem):
    """Make data/img/<stem>.jpg from a png once; return {src, w, h} for the page, or None when there is no picture."""
    out = IMG / f"{stem}.jpg"
    if not out.exists():
        if not src.exists():
            return None
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "82", str(src), "--out", str(out)],
                       check=True, capture_output=True)
    size = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(out)], check=True, capture_output=True, text=True).stdout
    w, h = (int(line.split()[-1]) for line in size.strip().splitlines()[-2:])
    return {"src": f"data/img/{stem}.jpg", "w": w, "h": h}


def plain(name):
    """SET_crane_0 -> crane 0. Only the prefix and the underscores go; the word itself is the builder's."""
    for prefix in ("SET_", "SHIP_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name.replace("_", " ").lower()


def navy_shot(short, board):
    spec = json.loads((NAVY / f"spec_{short}.json").read_text())
    made = json.loads((NAVY / f"build_b_{short}.json").read_text())
    seen = json.loads((NAVY / f"check_c_{short}.json").read_text())
    lens, frames = made["zoom"]["lens"], made["zoom"]["frames"]
    parts = []
    env = [plain(n) for n in made["env"] if n != "SET"]
    if env:
        parts.append("Set: " + ", ".join(env))
    if made.get("officer"):
        parts.append("The officer, on a rig the animator can pose" if made["officer"].get("override") else "The officer")
    parts.append(f"{len(made['lights'])} light" + ("" if len(made["lights"]) == 1 else "s"))
    parts.append(f"Camera zooms from {lens[0]} to {lens[1]} mm over frames {frames[0]} to {frames[1]}")
    checks = []
    if seen["libraries"] and all(seen["libraries"].values()):
        checks.append("Opens from a fresh folder, every library found")
    if not seen["missing_images"]:
        checks.append("No missing pictures")
    if seen.get("rig_is_override"):
        checks.append("The officer's rig can be posed")
    return {"short": short, "words": spec["title"], "entities": [], "prompt": None, "seconds": None,
            "image": jpg(NAVY / board, f"navy_board_{short}"),
            "built": {"file": made["name"] + ".blend", "frames": frames, "lens": lens, "parts": parts,
                      "libraries": [Path(p).name for p in made["libraries"]], "notes": spec.get("notes", []), "checks": checks,
                      "pictures": [dict(jpg(NAVY / f"preview_c_{short}_f{f:03d}.png", f"navy_{short}_f{f:03d}"), frame=f) for f in FRAMES]}}


def navy():
    return {"id": "navy", "title": "Navy shots", "demo": True, "seconds": None, "entities": [],
            "shots": [navy_shot(short, board) for short, board in NAVY_ORDER]}


def bat_bombs():
    v = json.loads((ROOT / "data" / "bat_bombs.json").read_text())
    return {"id": "bat_bombs", "doc": v["doc"], "title": v["title"], "seconds": v["seconds"],
            "entities": [{"id": e["id"], "kind": e["kind"], "name": e["name"], "look": e["look"],
                          "image": jpg(IMG / f"ent_{e['id']}.png", f"ent_{e['id']}")} for e in v["entities"]],
            "shots": [{"words": s["words"], "entities": s["entities"], "prompt": s["prompt"],
                       "seconds": round(len(s["words"].split()) / WORDS_PER_SECOND, 1),
                       "image": jpg(IMG / f"shot_{i + 1:02d}.png", f"shot_{i + 1:02d}"), "built": None}
                      for i, s in enumerate(v["shots"])]}


if __name__ == "__main__":
    stories = [navy(), bat_bombs()]
    (ROOT / "data" / "story.js").write_text("window.STORIES = " + json.dumps(stories, ensure_ascii=False, indent=1) + ";\n")
    for s in stories:
        built = sum(1 for x in s["shots"] if x["built"])
        print(f"{s['title']}: {len(s['shots'])} shots, {built} with a built scene, {sum(1 for x in s['shots'] if x['image'])} storyboard pictures")
