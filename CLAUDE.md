# plotpointe-animate
The Animate screen for PlotPointe: storyboard shots to animated clips, for the Art of War animators; local frontend only, never the live aow-bot

Done means `./verify.sh` exits 0. Agents never edit verify.sh, checks/ or program.md (the gate blocks it).
Needs Nick: deploys (only on his "ship"), and anything that touches the live aow-bot or its data on the 3D System box (this project only reads a copy).

Open it: preview server `plotpointe-animate` (port 8575, runs `tools/serve.py`), page `/animate.html`.
- `tools/serve.py` serves the page fresh and keeps each script's work: `data/work/<folder>.json` plus the script's Drive folder (`01 Script/Script.txt`, `00 Record/Record.txt`, `00 Record/changes.jsonl`).
- `tools/import_scripts.py` picks each doc's current script from `data/import/docs.json` (a read-only copy of the Google Docs); `tools/make_folders.py --create` makes the Drive folders and `data/scripts.js`. Running it again resets every record: do not run it once people have saved work.
- `tools/build_data.py` copies one PlotPointe storyboard file word for word (the earlier demos under Animate).
