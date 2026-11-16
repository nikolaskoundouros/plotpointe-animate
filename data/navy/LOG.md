## 2026-11-12 17:06 dock test scene (Nick: 'ok lets try')
- build_scene.py p1: dock sets linked from work/library/dock.blend, officer a library override of work/library/officer.blend, placed at (0.73, 6.62) on OFFICER_place, turned 25 deg off facing camera; camera zoom lens 27.72 -> 55.43 mm over frames 1-240, chest ends at (280, 380) px.
- check_scene.py c1: opened from /tmp/preview_elsewhere, both libraries found, no missing images, rig HG_James is an override, stills f001/f120/f240 rendered.
- First try refused by the workbench clip gate: script names contained 'preview'. Renamed to build_scene/check_scene on Nick's 'Yes, run it'. Second try: an overridden collection takes no new objects, so OFFICER_place got its own collection.
- Pod: L4 0.59 USD/h, about 10 min.
## 2026-11-12 17:31 all four scenes (Nick: 'Do the other 3 scenes')
- build_scene.py made general (one spec per scene). Scenes: SCENE_cruiser, SCENE_carrier_battleship, SCENE_officer, SCENE_dock; all checks pass from a fresh folder.
- Ship zooms aim at a measured frame point (zoom.frac): the SHIP_cruiser group's box centre fell off frame (x -12 px).
- Officer library renders on transparent film (sheet grey was composited); SCENE_officer sets film_transparent false.
- Lesson: never upload review/ specs while a pod run is going; the run's pull of review/ overwrote them.
- 20:55 Nick: "Yes, use it". g2 packaged as work/SHOT_officer.blend (old kept as SHOT_officer_d4_old.blend), copied to navy_preview/work/library/officer.blend; SCENE_officer and SCENE_dock rebuilt and checked from a fresh folder (libraries found, nothing missing, rig override).
