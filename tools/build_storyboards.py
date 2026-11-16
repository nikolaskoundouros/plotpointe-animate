"""The storyboards on the platform, copied from PlotPointe's own finished ones (data/import/storyboards_raw.json, a
read-only copy of research/visuals/<doc id>.json on the box). Only storyboards whose words are word for word the
platform's current script are taken, so a storyboard never shows a script that has since changed.

Out: data/storyboards.js   window.STORYBOARDS = {doc id: {title, seconds, shots: [...], cast: [...]}}
Pictures stay where PlotPointe made them (their web address); nothing is downloaded.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def words(text):
    return re.sub(r"[^a-z0-9 ]+", "", re.sub(r"~~.*?~~", "", text).replace("**", "").lower()).split()


def build():
    raw = json.loads((ROOT / "data" / "import" / "storyboards_raw.json").read_text())
    scripts = {r["doc"]: r for r in json.loads((ROOT / "data" / "scripts.js").read_text().split("=", 1)[1].rstrip().rstrip(";"))}
    out = {}
    for doc, d in raw.items():
        script = scripts.get(doc)
        if not script or words(" ".join(s["words"] for s in d["shots"])) != words(" ".join(script["lines"])):
            continue                               # no platform script, or the script changed since this storyboard was made
        cast = {e["id"]: e for e in d["entities"]}
        out[doc] = {"title": d["title"], "seconds": d.get("seconds"), "made": "by PlotPointe's storyboard maker",
                    "cast": [{"id": e["id"], "name": e["name"], "kind": e["kind"], "look": e["look"], "image": (e.get("image") or {}).get("url")} for e in d["entities"]],
                    "shots": [{"n": i + 1, "words": s["words"], "cast": [c for c in s["entities"] if c in cast], "prompt": s["prompt"],
                               "image": (s.get("image") or {}).get("url")} for i, s in enumerate(d["shots"])]}
    (ROOT / "data" / "storyboards.js").write_text("window.STORYBOARDS = " + json.dumps(out, indent=1, ensure_ascii=False) + ";\n")
    return out


if __name__ == "__main__":
    for doc, sb in build().items():
        print(f"{sb['title']}: {len(sb['shots'])} shots, {len(sb['cast'])} cast, {sum(1 for s in sb['shots'] if s['image'])} pictures")
