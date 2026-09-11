"""Copy & paste the selected voxels (Cmd+C / Ctrl+C with Bloxel tools).

The clipboard is a module-level block in local grid coordinates: materials
keyed by their offset from the block's min corner, plus that corner as the
paste origin. Paste writes the block back at its original location, makes
the pasted cells the selection, and switches to the Move & Rotate tool so
the block can be dragged into place.
"""
from __future__ import annotations

import bpy

from ..core import draw, mesher, state
from ..core.grid import copy_block, paste_block, selection_bounds

_clipboard: tuple[dict, tuple[int, int, int]] | None = None


def clipboard() -> tuple[dict, tuple[int, int, int]] | None:
    """The stored (block, origin) pair, or None."""
    return _clipboard


def set_clipboard(block: dict, origin) -> None:
    global _clipboard
    _clipboard = (block, origin)


def _use_transform_tool() -> None:
    try:  # switch when a UI is available
        bpy.ops.wm.tool_set_by_id(name="bloxel.transform_tool")
    except Exception:
        pass


class BLOXEL_OT_copy(bpy.types.Operator):
    """Copy the selected voxels to the Bloxel clipboard."""

    bl_idname = "bloxel.copy"
    bl_label = "Copy Voxels"
    bl_description = "Copy the selected voxels (paste restores them in place)"

    def execute(self, context):
        obj = context.active_object
        if not state.is_bloxel(obj):
            self.report({'WARNING'}, "Select a Bloxel object first")
            return {'CANCELLED'}
        rt = state.runtime(obj)
        cells = {cell for cell in rt.selection if rt.grid.get(*cell) != 0}
        if not cells:
            self.report({'WARNING'}, "Select voxels first")
            return {'CANCELLED'}
        origin = selection_bounds(cells)[0]
        set_clipboard(copy_block(rt.grid, cells, origin), origin)
        self.report({'INFO'}, f"Copied {len(cells)} voxels")
        return {'FINISHED'}


class BLOXEL_OT_paste(bpy.types.Operator):
    """Paste the copied voxels in place and switch to Move & Rotate."""

    bl_idname = "bloxel.paste"
    bl_label = "Paste Voxels"
    bl_description = ("Paste the copied voxels at their original location "
                      "and switch to the Move & Rotate tool")
    bl_options = {'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not state.is_bloxel(obj):
            self.report({'WARNING'}, "Select a Bloxel object first")
            return {'CANCELLED'}
        if _clipboard is None:
            self.report({'WARNING'}, "Copy voxels first")
            return {'CANCELLED'}
        block, origin = _clipboard
        rt = state.runtime(obj)
        bmin, bmax = state.get_bounds(obj)
        _, cells = paste_block(rt.grid, block, origin, bmin, bmax)
        if not cells:
            self.report({'WARNING'},
                        "Pasted voxels fall outside the working volume")
            return {'CANCELLED'}
        rt.selection = cells
        mesher.rebuild_mesh(obj, rt)
        state.commit(obj, rt)
        draw.tag_redraw_all()
        _use_transform_tool()
        self.report({'INFO'}, f"Pasted {len(cells)} voxels")
        return {'FINISHED'}
