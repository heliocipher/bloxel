"""Basic operators: create a Bloxel model, manage the palette."""
from __future__ import annotations

import bpy

from ..core import palette, state


class BLOXEL_OT_new_model(bpy.types.Operator):
    bl_idname = "bloxel.new_model"
    bl_label = "New Bloxel Model"
    bl_description = "Create a voxel model with a working volume and palette"
    bl_options = {'REGISTER', 'UNDO'}

    size: bpy.props.IntVectorProperty(
        name="Size", size=3, default=(32, 32, 32), min=1,
        description="Working volume dimensions in voxels")

    def execute(self, context):
        mesh = bpy.data.meshes.new("BloxelMesh")
        obj = bpy.data.objects.new("Bloxel", mesh)
        collection = context.collection or context.scene.collection
        collection.objects.link(obj)

        obj.bloxel_min = (0, 0, 0)
        obj.bloxel_max = (self.size[0] - 1, self.size[1] - 1, self.size[2] - 1)
        palette.create_palette(obj)
        obj.bloxel_palette_index = 0
        state.init_object(obj)

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        try:  # switch to the brush tool when a UI is available
            bpy.ops.wm.tool_set_by_id(name="bloxel.brush_tool")
        except Exception:
            pass
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class BLOXEL_OT_palette_add(bpy.types.Operator):
    bl_idname = "bloxel.palette_add"
    bl_label = "Add Palette Material"
    bl_description = "Append a material to the model's palette"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not state.is_bloxel(obj):
            self.report({'WARNING'}, "Select a Bloxel object first")
            return {'CANCELLED'}
        idx = palette.add_material(obj)
        obj.bloxel_palette_index = idx - 1
        return {'FINISHED'}


def _menu_func(self, context):
    self.layout.operator(BLOXEL_OT_new_model.bl_idname, icon='MESH_CUBE')


def register_menu() -> None:
    bpy.types.VIEW3D_MT_add.append(_menu_func)


def unregister_menu() -> None:
    bpy.types.VIEW3D_MT_add.remove(_menu_func)
