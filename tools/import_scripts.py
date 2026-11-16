"""Bring each script's current text into PlotPointe, once, from the copy of the Google Docs in data/import/docs.json
(fetched read-only through PlotPointe's own Google access). Nothing in Google is changed.

Which text counts as "the script":
  - the tab named "Version N" with the highest place in the doc, else "Tab 1" (the other tabs are notes: Fun Facts,
    Sources, Learnings, Feedback & Lessons, Changes Comparison)
  - inside that tab the first line is the title; a short line with no end punctuation ("Approved Final", "My version",
    "Version 8 - Final") starts a newer version; the lines under the LAST such heading are the current script
  - the writer's marks are kept as PlotPointe already reads them: ~~cut~~ and **the writer's own words**

Out: data/script_text.json  {doc id: {title, tab, section, lines}}
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def script_tab(doc):
    tabs = doc["tabs"]
    versions = [t for t in tabs if re.fullmatch(r"(?i)version\s*\d+", t["title"].strip())]
    return versions[-1] if versions else next((t for t in tabs if t["title"].strip().lower() == "tab 1"), tabs[0])


def is_heading(line):
    text = line.strip().strip("*").strip()
    return bool(text) and len(text.split()) <= 6 and len(text) < 45 and text[-1] not in ",.!?'\"’”" and not text.startswith("~~")


def current_script(doc):
    tab = script_tab(doc)
    lines = tab["paragraphs"]
    heads = [i for i in range(1, len(lines)) if is_heading(lines[i])]
    start = heads[-1] + 1 if heads else (1 if lines and lines[0].strip() == doc["name"].strip() else 0)
    return {"title": doc["name"], "tab": tab["title"], "section": lines[heads[-1]].strip().strip("*").strip() if heads else None,
            "lines": [l.strip() for l in lines[start:] if l.strip()]}


# Lines Nick wrote that the doc's clean copy changed. He asked for his own back (13 Nov 2026: "Yes, put it back").
# Each text is copied from data/import/chatgpt_share.html (his marked-up script, message 20, and the reply quoting it, message 23).
FIXES = {"1cWbOCeKHtUOqok2wexo8B9_Mq8RKO2wwiYDXETo2uQk": {-1: "clearing the smoke from the plane helping the pilot save the plane from crashing into the ground!"}}


def apply_fixes(doc_id, script):
    for index, text in FIXES.get(doc_id, {}).items():
        script["lines"][index] = text
    return script


if __name__ == "__main__":
    docs = json.loads((ROOT / "data" / "import" / "docs.json").read_text())
    out = {d["id"]: apply_fixes(d["id"], current_script(d)) for d in docs}
    (ROOT / "data" / "script_text.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(len(out), "docs read;", sum(1 for v in out.values() if v["lines"]), "with text")
