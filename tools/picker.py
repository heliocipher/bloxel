"""Material picker (eyedropper) tool."""
from __future__ import annotations

import bpy

from ..core import state
from ..core.grid import raycast
from .common import event_ray


class BLOXEL_OT_picker(bpy.types.Operator):
    bl_idname = "bloxel.picker"
    bl_label = "Voxel Material Picker"
    bl_description = "Pick the material of the voxel under the cursor"
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
        if res.hit is not None:
            mat = rt.grid.get(*res.hit.cell)
            if mat:
                obj.bloxel_palette_index = mat - 1
                self.report({'INFO'}, f"Picked material slot {mat}")
        return {'FINISHED'}
