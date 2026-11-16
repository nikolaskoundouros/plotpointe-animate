"""Start over: one Drive folder per script, one folder per step inside it, and a fresh tracking record.

    make_folders.py            show what would be created (nothing is written)
    make_folders.py --create   create it, and write data/scripts.js for the page

The scripts are the Google Docs in "Art Of War Scripts" (read by title only), minus the documents that are not scripts.
Nothing is matched against PlotPointe's own records: every script starts at step 1 on the day this runs.
The writers' folder is never touched; the new folders are made beside it, in "Art Of War Productions".
"""
import json
import sys
import time
from pathlib import Path

DRIVE = Path.home() / "Library/CloudStorage/GoogleDrive-nikolaskoundouros@gmail.com/My Drive"
SOURCE = DRIVE / "Art Of War Scripts"
TARGET = DRIVE / "Art Of War Productions"
ROOT = Path(__file__).resolve().parent.parent
NOT_SCRIPTS = {                                    # documents in the writers' folder that are not scripts
    "Your rules prompt: draft for review", "Scriptwriters Feedback", "Embed Nick’s scriptwriting feedback",
    "Blind test: the two Neither stories"}
STEP_FOLDERS = ["00 Record", "01 Script", "02 Storyboard", "03 Blend", "04 Clips and final video", "05 Sound", "06 Captions", "07 Publish"]
STEPS = [("Script", "Waiting for edit and approval"), ("Storyboard", "Not started"), ("Animate", "Not started"), ("Publish", "Not published")]
TODAY = time.strftime("%Y-%m-%d")
TEXT = ROOT / "data" / "script_text.json"          # each doc's current script, from tools/import_scripts.py
SAME_NAME = {"The King Who Ate Poison": "14qAw7-mEx", "The King Who Ate Poison (1)": "1TJDc1FhzI"}   # two docs share one title; told apart by their dates (checked 13 Nov 2026)


def folder_name(title):
    """The script's title as a folder name: no em or en dashes, no slashes."""
    return title.replace("—", "-").replace("–", "-").replace("/", "-").strip()


def titles():
    return sorted(p.stem for p in SOURCE.glob("*.gdoc") if p.stem not in NOT_SCRIPTS)


def find_doc(title, texts):
    """The imported doc for a folder title: by its id for the two same-named docs, else by its exact title."""
    if title in SAME_NAME:
        return next(((i, t) for i, t in texts.items() if i.startswith(SAME_NAME[title])), (None, None))
    hits = [(i, t) for i, t in texts.items() if t["title"] == title]
    return hits[0] if len(hits) == 1 else (None, None)


def script_file(title, lines):
    return title + "\n\n" + "\n".join(lines) + "\n"


def record_text(title, name, source):
    lines = [f"Script:   {title}", f"Folder:   Art Of War Productions / {name}", f"Text:     01 Script / Script.txt (the latest text, kept up to date by PlotPointe)",
             f"Source:   {source}",
             f"Tracking started {TODAY}. Nothing is carried over from before.", ""]
    lines += [f"STEP {n}  {step:<11} {state}" for n, (step, state) in enumerate(STEPS, 1)]   # the process: scripts, storyboard, animate, publish
    return "\n".join(lines) + "\n"


def main():
    create = "--create" in sys.argv
    found = titles()
    print(f"{len(found)} scripts in {SOURCE.name} (left out: {len(NOT_SCRIPTS)} documents that are not scripts)")
    texts = json.loads(TEXT.read_text()) if TEXT.exists() else {}
    registry = []
    for title in found:
        name = folder_name(title)
        doc_id, text = find_doc(title, texts)
        source = (f"imported {TODAY} from the Google Doc {doc_id}, tab \"{text['tab']}\"" + (f", under \"{text['section']}\"" if text["section"] else "")) if text else "no text imported"
        record = {"title": title, "folder": name, "doc": doc_id, "source": source, "lines": text["lines"] if text else [], "started": TODAY,
                  "steps": [{"step": s, "state": st, "at": None} for s, st in STEPS]}
        registry.append(record)
        print(f"  {name}")
        if create:
            base = TARGET / name
            for sub in STEP_FOLDERS:
                (base / sub).mkdir(parents=True, exist_ok=True)
            (base / "00 Record" / "Record.txt").write_text(record_text(title, name, source))
            if record["lines"]:
                (base / "01 Script" / "Script.txt").write_text(script_file(title, record["lines"]))
            (base / "00 Record" / "record.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n")
    if create:
        old = ROOT / "data" / "scripts.js"
        if old.exists():                           # scripts written in the platform are never dropped by a re-import
            kept = [r for r in json.loads(old.read_text().split("=", 1)[1].rstrip().rstrip(";")) if r.get("made") == "platform"]
            registry = sorted(registry + [r for r in kept if r["folder"] not in {x["folder"] for x in registry}], key=lambda r: r["title"].lower())
        (ROOT / "data" / "scripts.js").write_text("window.SCRIPTS = " + json.dumps(registry, indent=1, ensure_ascii=False) + ";\n")
        print(f"created {len(registry)} folders with {len(STEP_FOLDERS)} step folders each in {TARGET}")
    else:
        print("dry run: nothing written. Run with --create.")


if __name__ == "__main__":
    main()
