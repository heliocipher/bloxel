"""Fuzzy select: pick same-material voxels by connection or globally.

A click replaces the selection with the picked region. Shift adds the
region to the selection, Ctrl removes it; clicking empty space clears the
selection. The selection lives in Runtime.selection, persists through the
serialized blob, and is drawn by the selection overlay in core.draw.
"""
from __future__ import annotations

import bpy

from ..core import draw, state
from ..core.grid import raycast, select_region
from .common import event_ray


class BLOXEL_OT_fuzzy_select(bpy.types.Operator):
    bl_idname = "bloxel.fuzzy_select"
    bl_label = "Voxel Fuzzy Select"
    bl_description = ("Select the clicked voxel's connected same-material "
                      "region or all voxels of that material (Shift adds, "
                      "Ctrl removes, empty space clears)")
    bl_options = {'UNDO'}

    def invoke(self, context, event):
        obj = context.active_object
        if not state.is_bloxel(obj):
            self.report({'WARNING'}, "Select a Bloxel object first")
            return {'CANCELLED'}
        ray = event_ray(context, event, obj)
        if ray is None:
            return {'CANCELLED'}
        rt = state.runtime(obj)
        bmin, bmax = state.get_bounds(obj)
        res = raycast(rt.grid, ray[0], ray[1], bmin, bmax)
        settings = context.scene.bloxel_tools
        old = set(rt.selection)
        if res.hit is None:
            rt.selection = set()
        else:
            cells = select_region(
                rt.grid, res.hit.cell, bmin, bmax,
                contiguous=(settings.select_mode == 'CONNECTED'))
            if event.shift:
                rt.selection |= cells
            elif event.ctrl:
                rt.selection -= cells
            else:
                rt.selection = set(cells)
        if rt.selection != old:
            state.commit(obj, rt)
            draw.tag_redraw_all()
            if rt.selection:
                self.report({'INFO'}, f"Selected {len(rt.selection)} voxels")
            else:
                self.report({'INFO'}, "Selection cleared")
        return {'FINISHED'}
