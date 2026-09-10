"""Bloxel - voxel modeling inside Blender."""
from __future__ import annotations

import bpy

bl_info = {
    "name": "Bloxel",
    "author": "Bloxel contributors",
    "version": (0, 1, 0),
    "blender": (5, 0, 0),
    "location": "3D Viewport > Toolbar / Sidebar > Bloxel",
    "description": "Voxel modeling inside Blender (sparse chunked grid, native undo)",
    "category": "3D View",
}

from .core import draw, palette, state  # noqa: E402
from .ops import basic, export  # noqa: E402
from .tools import brush, common, extrude, fill, picker, select, workspace  # noqa: E402
from .ui import panels  # noqa: E402

_CLASSES = (
    workspace.BloxelToolSettings,
    basic.BLOXEL_OT_new_model,
    basic.BLOXEL_OT_palette_add,
    export.BLOXEL_OT_export_godot,
    brush.BLOXEL_OT_brush,
    brush.BLOXEL_OT_eraser,
    brush.BLOXEL_OT_brush_cursor,
    fill.BLOXEL_OT_fill,
    select.BLOXEL_OT_fuzzy_select,
    select.BLOXEL_OT_rect_select,
    extrude.BLOXEL_OT_extrude,
    picker.BLOXEL_OT_picker,
    panels.BLOXEL_UL_palette,
    panels.BLOXEL_PT_main,
)

_TOOLS = (
    workspace.BLOXEL_WT_brush,
    workspace.BLOXEL_WT_eraser,
    workspace.BLOXEL_WT_fill,
    workspace.BLOXEL_WT_select,
    workspace.BLOXEL_WT_rect_select,
    workspace.BLOXEL_WT_extrude,
    workspace.BLOXEL_WT_picker,
)

_HISTORY_HANDLERS = (
    bpy.app.handlers.load_post,
    bpy.app.handlers.undo_post,
    bpy.app.handlers.redo_post,
)


def register() -> None:
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    state.register_properties()
    bpy.types.Scene.bloxel_tools = bpy.props.PointerProperty(
        type=workspace.BloxelToolSettings)
    for handler_list in _HISTORY_HANDLERS:
        if state.history_changed not in handler_list:
            handler_list.append(state.history_changed)
    palette.register_msgbus()
    draw.register()
    basic.register_menu()
    for i, tool in enumerate(_TOOLS):
        bpy.utils.register_tool(tool, separator=(i == 0), group=(i == 0))


def unregister() -> None:
    for tool in reversed(_TOOLS):
        bpy.utils.unregister_tool(tool)
    basic.unregister_menu()
    common.cursor_highlight_stop()
    draw.unregister()
    palette.unregister_msgbus()
    for handler_list in _HISTORY_HANDLERS:
        if state.history_changed in handler_list:
            handler_list.remove(state.history_changed)
    del bpy.types.Scene.bloxel_tools
    state.unregister_properties()
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
