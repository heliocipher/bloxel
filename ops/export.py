"""Export operators (Godot via glTF)."""
from __future__ import annotations

import bpy


class BLOXEL_OT_export_godot(bpy.types.Operator):
    bl_idname = "bloxel.export_godot"
    bl_label = "Export to Godot (glTF)"
    bl_description = ("Export the selected Bloxel models as .glb with their "
                      "materials (Base Color / Metallic / Roughness) for Godot")
    bl_options = {'REGISTER'}

    def invoke(self, context, event):
        if not context.selected_objects:
            self.report({'WARNING'}, "Select the Bloxel model(s) to export")
            return {'CANCELLED'}
        return bpy.ops.export_scene.gltf('INVOKE_DEFAULT',
                                         use_selection=True,
                                         export_format='GLB',
                                         export_materials='EXPORT')
