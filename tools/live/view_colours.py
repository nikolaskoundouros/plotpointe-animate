"""Runs inside the live Blender each time a shot is opened (pp_live.py), and can be sent as a build step.

Blender's fast drawing mode paints every material in its "viewport colour". The built scenes leave that at plain grey,
so the cast looks black and white. This gives each material the colour its own shader already has:

  a plain shader colour            that colour
  cloth from the character kit     the tint the builder mixed in last (navy jacket, white shirt)
  skin                             the average colour of the skin picture
  eyes and teeth                   white and ivory

The materials come from the shared library files, which a scene cannot write to, so this is done again on every open.
"""
import bpy
import numpy as np

coloured = []
for m in bpy.data.materials:
    nodes = m.node_tree.nodes if m.node_tree else []
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if not bsdf:
        continue
    base = bsdf.inputs["Base Color"]
    colour = None
    if not base.is_linked:
        colour = base.default_value[:]
    else:
        last = base.links[0].from_node
        tint = next((i for i in last.inputs if i.name == "B" and i.type == "RGBA"), None) if last.type == "MIX" else None
        if tint and not tint.is_linked and "HG_Control" in nodes:
            colour = tint.default_value[:]
    skin = nodes.get("Color") if m.name.startswith(".Human") else None
    if skin and skin.type == "TEX_IMAGE" and skin.image and skin.image.size[0]:
        px = np.empty(skin.image.size[0] * skin.image.size[1] * 4, dtype=np.float32)
        skin.image.pixels.foreach_get(px)
        px = px.reshape(-1, 4)[::97, :3]
        px = px[px.sum(axis=1) > 0.3]                 # the empty, dark parts of the picture are left out
        if len(px):
            colour = [float(c) for c in px.mean(axis=0)] + [1.0]
    if m.name.startswith(".HG_Eyes_Inner"):
        colour = (0.85, 0.85, 0.85, 1.0)
    if m.name.startswith(".HG_Teeth"):
        colour = (0.8, 0.77, 0.7, 1.0)
    if colour:
        m.diffuse_color = colour
        coloured.append(m.name)
for area in bpy.context.window.screen.areas:
    if area.type == "VIEW_3D":
        area.spaces.active.shading.color_type = "MATERIAL"
print("materials shown in their own colour:", len(coloured))
