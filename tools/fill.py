"""Flood fill (region fill) tool."""
from __future__ import annotations

import bpy

from ..core import mesher, palette, state
from ..core.grid import flood_fill, raycast
from .common import event_ray


class BLOXEL_OT_fill(bpy.types.Operator):
    bl_idname = "bloxel.fill"
    bl_label = "Voxel Fill"
    bl_description = "Fill a region of same-material voxels with the active material"
    bl_options = {'UNDO'}

    def invoke(self, context, event):
        obj = context.active_object
        if not state.is_bloxel(obj):
            self.report({'WARNING'}, "Select a Bloxel object first")
            return {'CANCELLED'}
        mat = palette.active_index(obj)
        # mat 0 means EMPTY: filling would delete the region instead
        if mat == 0:
            self.report({'WARNING'}, "Add a palette material first")
            return {'CANCELLED'}
        ray = event_ray(context, event, obj)
        if ray is None:
            return {'CANCELLED'}
        rt = state.runtime(obj)
        bmin, bmax = state.get_bounds(obj)
        res = raycast(rt.grid, ray[0], ray[1], bmin, bmax)
        if res.hit is None:
            return {'FINISHED'}
        settings = context.scene.bloxel_tools
        changed = flood_fill(rt.grid, res.hit.cell, mat, bmin, bmax,
                             contiguous=(settings.fill_mode == 'CONTIGUOUS'))
        if changed:
            mesher.rebuild_mesh(obj, rt)
            state.commit(obj, rt)
            self.report({'INFO'}, f"Filled {changed} voxels")
        return {'FINISHED'}
