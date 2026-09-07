"""Brush (Add/Paint) and Eraser tools."""
from __future__ import annotations

import bpy

from ..core import palette, state
from ..core.grid import apply_brush, mirror_variants, stamp_cells, walk_line
from .common import (BloxelStrokeMixin, cursor_highlight_clear,
                     cursor_highlight_for)

_COLORS = {
    'ADD': (0.25, 0.90, 0.30, 0.30),
    'PAINT': (0.30, 0.50, 1.00, 0.30),
    'ERASE': (1.00, 0.25, 0.20, 0.30),
}

_TOOL_MODES = [('BRUSH', "Brush", "Add or paint voxels"),
               ('ERASER', "Eraser", "Remove voxels")]


class BrushStrokeMixin(BloxelStrokeMixin):
    """Brush/eraser behavior (plain mixin - see BloxelStrokeMixin note)."""

    def invoke(self, context, event):
        obj = context.active_object
        # mat 0 means EMPTY: ADD/PAINT would erase voxels instead of writing
        if (state.is_bloxel(obj) and self._mode(context) != 'ERASE'
                and palette.active_index(obj) == 0):
            self.report({'WARNING'}, "Add a palette material first")
            return {'CANCELLED'}
        return super().invoke(context, event)

    # ---------------------------------------------------------------- helpers
    def _mode(self, context) -> str:
        if self.tool_mode == 'ERASER':
            return 'ERASE'
        return context.scene.bloxel_tools.brush_mode  # 'ADD' | 'PAINT'

    def _target(self, context, event):
        """(base_cell, normal, mode) or None."""
        res = self.pick(context, event)
        if res is None:
            return None
        mode = self._mode(context)
        if res.hit is not None:
            if mode == 'ADD':
                h = res.hit
                base = (h.cell[0] + h.normal[0],
                        h.cell[1] + h.normal[1],
                        h.cell[2] + h.normal[2])
            else:  # PAINT / ERASE affect the hit voxel itself
                base = res.hit.cell
            return base, res.hit.normal, mode
        # no voxel under the cursor: adding onto empty space lands on the
        # volume entry cell so a fresh model can be started from any view
        if mode == 'ADD' and res.entry_cell is not None:
            return res.entry_cell, res.entry_normal, mode
        return None

    def _variants(self, context, base, normal):
        """(cell, normal) list expanded over the active mirror axes."""
        s = context.scene.bloxel_tools
        return mirror_variants(base, normal,
                               (s.mirror_x, s.mirror_y, s.mirror_z),
                               self.bmin, self.bmax)

    def _stamp(self, context, base, normal, mode) -> int:
        settings = context.scene.bloxel_tools
        mat = palette.active_index(self.obj)
        # recording pre-edit values feeds the stroke mask (plane-locked drag)
        record = self._overlay if self.stroking else None
        changed = 0
        for cell, n in self._variants(context, base, normal):
            changed += apply_brush(self.rt.grid, cell, n, settings.shape,
                                   settings.size, mode, mat, self.bmin, self.bmax,
                                   record=record)
        return changed

    # ------------------------------------------------------------ tool hooks
    def apply_at(self, context, event):
        target = self._target(context, event)
        if target is None:
            self._last_base = None
            self._highlight.clear(area=context.area)
            if not self._changed and not self._miss_reported:
                self.report({'INFO'},
                            "Click on the grid to place voxels")
                self._miss_reported = True
            return
        base, normal, mode = target
        # connect with the previous stamp so fast drags leave no gaps
        path = [base]
        if self._last_base is not None and self._last_base != base:
            path = list(walk_line(self._last_base, base))[1:]
        changed = 0
        for cell in path:
            changed += self._stamp(context, cell, normal, mode)
        self._last_base = base
        if changed:
            self._changed = True
            self.rebuild()
        self._show_highlight(context, base, normal, mode)

    def update_highlight(self, context, event):
        target = self._target(context, event)
        if target is None:
            self._highlight.clear(area=context.area)
            return
        self._show_highlight(context, *target)

    def _show_highlight(self, context, base, normal, mode):
        settings = context.scene.bloxel_tools
        cells = []
        for c, n in self._variants(context, base, normal):
            cells.extend(stamp_cells(c, n, settings.shape, settings.size))
        self._highlight.set(cells, _COLORS[mode], area=context.area)


class BLOXEL_OT_brush(BrushStrokeMixin, bpy.types.Operator):
    bl_idname = "bloxel.brush"
    bl_label = "Voxel Brush"
    bl_description = "Add or paint voxels on a grid (Alt+LMB picks material)"
    bl_options = {'UNDO'}

    tool_mode: bpy.props.EnumProperty(items=_TOOL_MODES, default='BRUSH')


class BLOXEL_OT_eraser(BrushStrokeMixin, bpy.types.Operator):
    bl_idname = "bloxel.eraser"
    bl_label = "Voxel Eraser"
    bl_description = "Remove voxels"
    bl_options = {'UNDO'}

    tool_mode: bpy.props.EnumProperty(items=_TOOL_MODES, default='ERASER')


class BLOXEL_OT_brush_cursor(BrushStrokeMixin, bpy.types.Operator):
    """Updates the brush/eraser highlight preview on cursor motion (no edit).

    Bound to MOUSEMOVE in the brush/eraser tool keymaps. Never runs while a
    stroke modal is active (that consumes the events first).
    """

    bl_idname = "bloxel.brush_cursor"
    bl_label = "Voxel Brush Cursor"
    bl_options = {'INTERNAL'}

    tool_mode: bpy.props.EnumProperty(items=_TOOL_MODES, default='BRUSH')

    def invoke(self, context, event):
        obj = context.active_object
        if not state.is_bloxel(obj):
            cursor_highlight_clear()
            return {'FINISHED'}
        self._bind(context, obj)
        self._highlight = cursor_highlight_for(obj)
        self.update_highlight(context, event)
        return {'FINISHED'}
