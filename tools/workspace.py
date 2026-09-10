"""Toolbar registration (WorkSpaceTool) and shared tool settings."""
from __future__ import annotations

import bpy


class BloxelToolSettings(bpy.types.PropertyGroup):
    brush_mode: bpy.props.EnumProperty(
        name="Mode",
        items=[('ADD', "Add", "Add voxels with the active material"),
               ('PAINT', "Paint", "Repaint existing voxels")],
        default='ADD')
    size: bpy.props.IntProperty(
        name="Size", default=1, min=1, max=33,
        description="Brush size - footprint side length in voxels")
    shape: bpy.props.EnumProperty(
        name="Shape",
        items=[('SQUARE', "Square", "Square footprint"),
               ('CIRCLE', "Circle", "Circular footprint")],
        default='SQUARE')
    mirror_x: bpy.props.BoolProperty(name="X", description="Mirror across the volume centre on X")
    mirror_y: bpy.props.BoolProperty(name="Y", description="Mirror across the volume centre on Y")
    mirror_z: bpy.props.BoolProperty(name="Z", description="Mirror across the volume centre on Z")
    fill_mode: bpy.props.EnumProperty(
        name="Fill",
        items=[('CONTIGUOUS', "Contiguous", "Fill the connected region of same-material voxels"),
               ('GLOBAL', "Global", "Fill all voxels sharing the clicked material")],
        default='CONTIGUOUS')
    select_mode: bpy.props.EnumProperty(
        name="Select",
        items=[('CONNECTED', "Connected", "Select the connected region of same-material voxels"),
               ('MATERIAL', "Material", "Select all voxels sharing the clicked material")],
        default='CONNECTED')
    rect_select_mode: bpy.props.EnumProperty(
        name="Rectangle",
        items=[('VISIBLE', "Visible Only", "Select only voxels visible from the current view"),
               ('THROUGH', "Strikethrough", "Select all voxels in the rectangle, including hidden ones")],
        default='VISIBLE')


def _draw_brush_settings(context, layout, tool):
    settings = context.scene.bloxel_tools
    layout.prop(settings, "brush_mode", expand=True)
    layout.prop(settings, "shape", expand=True)
    layout.prop(settings, "size")
    row = layout.row(align=True)
    row.label(text="Mirror:")
    row.prop(settings, "mirror_x", toggle=True)
    row.prop(settings, "mirror_y", toggle=True)
    row.prop(settings, "mirror_z", toggle=True)


def _draw_eraser_settings(context, layout, tool):
    settings = context.scene.bloxel_tools
    layout.prop(settings, "shape", expand=True)
    layout.prop(settings, "size")
    row = layout.row(align=True)
    row.label(text="Mirror:")
    row.prop(settings, "mirror_x", toggle=True)
    row.prop(settings, "mirror_y", toggle=True)
    row.prop(settings, "mirror_z", toggle=True)


def _draw_fill_settings(context, layout, tool):
    layout.prop(context.scene.bloxel_tools, "fill_mode", expand=True)


def _draw_select_settings(context, layout, tool):
    layout.prop(context.scene.bloxel_tools, "select_mode", expand=True)


def _draw_rect_select_settings(context, layout, tool):
    layout.prop(context.scene.bloxel_tools, "rect_select_mode", expand=True)


class BLOXEL_WT_brush(bpy.types.WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'OBJECT'
    bl_idname = "bloxel.brush_tool"
    bl_label = "Voxel Brush"
    bl_description = "Add or paint voxels (Alt+LMB picks material)"
    bl_icon = "brush.generic"
    bl_keymap = (
        ("bloxel.brush", {"type": 'LEFTMOUSE', "value": 'PRESS'},
         {"properties": [("tool_mode", 'BRUSH')]}),
        ("bloxel.brush_cursor", {"type": 'MOUSEMOVE', "value": 'ANY'},
         {"properties": [("tool_mode", 'BRUSH')]}),
    )
    draw_settings = staticmethod(_draw_brush_settings)


class BLOXEL_WT_eraser(bpy.types.WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'OBJECT'
    bl_idname = "bloxel.eraser_tool"
    bl_label = "Voxel Eraser"
    bl_description = "Remove voxels"
    bl_icon = "brush.gpencil_draw.erase"
    bl_keymap = (
        ("bloxel.eraser", {"type": 'LEFTMOUSE', "value": 'PRESS'},
         {"properties": [("tool_mode", 'ERASER')]}),
        ("bloxel.brush_cursor", {"type": 'MOUSEMOVE', "value": 'ANY'},
         {"properties": [("tool_mode", 'ERASER')]}),
    )
    draw_settings = staticmethod(_draw_eraser_settings)


class BLOXEL_WT_fill(bpy.types.WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'OBJECT'
    bl_idname = "bloxel.fill_tool"
    bl_label = "Voxel Fill"
    bl_description = "Flood fill voxels with the active material"
    bl_icon = "brush.gpencil_draw.fill"
    bl_keymap = (
        ("bloxel.fill", {"type": 'LEFTMOUSE', "value": 'PRESS'}, None),
    )
    draw_settings = staticmethod(_draw_fill_settings)


class BLOXEL_WT_select(bpy.types.WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'OBJECT'
    bl_idname = "bloxel.select_tool"
    bl_label = "Voxel Fuzzy Select"
    bl_description = ("Select voxels of one material: connected region or "
                      "global (Shift adds, Ctrl removes)")
    bl_icon = "ops.sculpt.mask_by_color"
    bl_keymap = (
        ("bloxel.fuzzy_select", {"type": 'LEFTMOUSE', "value": 'PRESS'}, None),
    )
    draw_settings = staticmethod(_draw_select_settings)


class BLOXEL_WT_rect_select(bpy.types.WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'OBJECT'
    bl_idname = "bloxel.rect_select_tool"
    bl_label = "Voxel Rectangle Select"
    bl_description = ("Drag a rectangle to select the voxels it covers: "
                      "visible only or strikethrough")
    bl_icon = "ops.generic.select_box"
    bl_keymap = (
        ("bloxel.rect_select", {"type": 'LEFTMOUSE', "value": 'PRESS'}, None),
    )
    draw_settings = staticmethod(_draw_rect_select_settings)


class BLOXEL_WT_extrude(bpy.types.WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'OBJECT'
    bl_idname = "bloxel.extrude_tool"
    bl_label = "Voxel Extrude"
    bl_description = "Pull coplanar same-material faces outward (drag for layers)"
    bl_icon = "ops.mesh.extrude_faces_move"
    bl_keymap = (
        ("bloxel.extrude", {"type": 'LEFTMOUSE', "value": 'PRESS'}, None),
    )


class BLOXEL_WT_picker(bpy.types.WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'OBJECT'
    bl_idname = "bloxel.picker_tool"
    bl_label = "Voxel Picker"
    bl_description = "Pick the material of a voxel"
    bl_icon = "ops.paint.eyedropper_add"
    bl_keymap = (
        ("bloxel.picker", {"type": 'LEFTMOUSE', "value": 'PRESS'}, None),
    )
