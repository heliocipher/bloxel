"""Sidebar panel: model info, working volume, palette editor."""
from __future__ import annotations

import bpy

from ..core import state


class BLOXEL_UL_palette(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "diffuse_color", text="")
        row.prop(item, "name", text="", emboss=False)


class BLOXEL_PT_main(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Bloxel"
    bl_label = "Bloxel"

    def draw(self, context):
        layout = self.layout
        layout.operator("bloxel.new_model", icon='MESH_CUBE')

        obj = context.active_object
        if not state.is_bloxel(obj):
            layout.label(text="Select a Bloxel object", icon='INFO')
            return

        box = layout.box()
        box.label(text="Working Volume")
        col = box.column(align=True)
        col.prop(obj, "bloxel_min", text="Min")
        col.prop(obj, "bloxel_max", text="Max")
        if any(a > b for a, b in zip(obj.bloxel_min, obj.bloxel_max)):
            col.label(text="Min exceeds Max on some axis", icon='ERROR')
        rt = state.runtime(obj)
        box.label(text=f"Voxels: {rt.grid.voxel_count()}")

        box = layout.box()
        box.label(text="Palette")
        box.template_list("BLOXEL_UL_palette", "", obj.data, "materials",
                          obj, "bloxel_palette_index", rows=5)
        box.operator("bloxel.palette_add", icon='ADD')

        box = layout.box()
        box.label(text="Export")
        box.operator("bloxel.export_godot", icon='EXPORT')
