"""Bloxel in-session diagnostic.

HOW TO USE (needs the real Blender UI):
1. Open Terminal and launch Blender from it so Python errors are visible:
       /Applications/Blender.app/Contents/MacOS/Blender
2. Make sure the Bloxel extension is enabled.
3. Switch to the Scripting workspace, open this file, press "Run Script".
4. Select the Voxel Brush tool and click in the viewport; watch the Terminal
   for red tracebacks.
5. Copy everything printed with the [BLOXEL-DIAG] prefix and send it back.
"""
import sys
import traceback

import bpy


def P(*args):
    print("[BLOXEL-DIAG]", *args)


P("=== start ===")

# --- 1. registration --------------------------------------------------------
P("op bloxel.brush:", hasattr(bpy.ops.bloxel, "brush") if hasattr(bpy.ops, "bloxel") else "MISSING NAMESPACE")
P("scene.bloxel_tools:", hasattr(bpy.context.scene, "bloxel_tools"))
P("object.bloxel_min prop:", hasattr(bpy.types.Object, "bloxel_min"))

mod = sys.modules.get("bloxel") or next(
    (m for n, m in sys.modules.items() if n.endswith(".bloxel")), None)
P("module found:", mod.__name__ if mod else None)
if mod is None:
    P("FATAL: bloxel module not loaded")
    raise SystemExit

state = mod.core.state
grid_mod = mod.core.grid
mesher_mod = mod.core.mesher

# --- 2. model ---------------------------------------------------------------
obj = bpy.context.active_object
if not state.is_bloxel(obj):
    try:
        bpy.ops.bloxel.new_model('EXEC_DEFAULT')
        obj = bpy.context.active_object
        P("created model:", obj.name)
    except Exception:
        P("new_model FAILED:")
        traceback.print_exc()
        raise SystemExit
else:
    P("active model:", obj.name)
P("is_bloxel:", state.is_bloxel(obj))
P("bounds:", state.get_bounds(obj), "palette slots:", len(obj.data.materials))

# --- 3. tool activation + keymap --------------------------------------------
try:
    bpy.ops.wm.tool_set_by_id(name="bloxel.brush_tool")
    tool = bpy.context.workspace.tools.from_space_view3d_mode('OBJECT')
    P("active tool:", tool.idname if tool else None)
except Exception as e:
    P("tool_set_by_id failed:", e)

found = []
kc = bpy.context.window_manager.keyconfigs.user
for km in kc.keymaps:
    for kmi in km.keymap_items:
        if kmi.idname.startswith("bloxel."):
            found.append(f"{km.name} :: {kmi.idname} {kmi.type}/{kmi.value}")
P("tool keymap items:", *found if found else "NONE FOUND <-- keymap broken")
# also check the addon keyconfig
kc_addon = bpy.context.window_manager.keyconfigs.addon
if kc_addon:
    found2 = []
    for km in kc_addon.keymaps:
        for kmi in km.keymap_items:
            if kmi.idname.startswith("bloxel."):
                found2.append(f"{km.name} :: {kmi.idname} {kmi.type}/{kmi.value}")
    P("addon keymap items:", *found2 if found2 else "none")

# --- 4. synthetic click through the real pipeline ---------------------------
try:
    area = next(a for a in bpy.context.window.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    rv3d = area.spaces.active.region_3d
except StopIteration:
    P("no VIEW_3D in current screen - switch to Layout workspace and re-run")
    raise SystemExit

from bpy_extras import view3d_utils

coord = (region.width // 2, region.height // 2)
origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
inv = obj.matrix_world.inverted()
local_o = inv @ origin
local_d = (inv.to_3x3() @ direction).normalized()

rt = state.runtime(obj)
bmin, bmax = state.get_bounds(obj)
res = grid_mod.raycast(rt.grid, local_o, local_d, bmin, bmax)
P("raycast from view center -> hit:", res.hit, "entry:", res.entry_cell)

base = normal = None
if res.hit is not None:
    base = tuple(res.hit.cell[i] + res.hit.normal[i] for i in range(3))
    normal = res.hit.normal
elif res.entry_cell is not None:
    base, normal = res.entry_cell, res.entry_normal

if base is None:
    P("ray misses the volume - point the camera at the orange grid box")
else:
    changed = grid_mod.apply_brush(rt.grid, base, normal, 'SQUARE', 1,
                                   'ADD', 1, bmin, bmax)
    mesher_mod.rebuild_mesh(obj, rt)
    state.commit(obj, rt)
    P("synthetic ADD: changed =", changed,
      "| mesh polygons:", len(obj.data.polygons),
      "| voxels:", rt.grid.voxel_count())

# --- 5. call the real operator (first stamp happens during invoke) ----------
try:
    before = rt.grid.voxel_count()
    with bpy.context.temp_override(area=area, region=region):
        result = bpy.ops.bloxel.brush('INVOKE_DEFAULT')
    after = state.runtime(obj).grid.voxel_count()
    P("bpy.ops.bloxel.brush invoke returned:", result,
      "| voxels before/after:", before, after)
    P("NOTE: the operator is now in a modal state - press ESC or click once "
      "in the viewport to end it.")
except Exception:
    P("operator invoke RAISED:")
    traceback.print_exc()

P("=== done ===")
P("Now: select the Voxel Brush tool and LEFT-CLICK in the viewport.")
P("Any red traceback in the Terminal at that moment is the bug - send it.")
