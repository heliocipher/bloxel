"""Line tool: drag a straight run of voxels, place it on release."""
from __future__ import annotations

import bpy

from ..core import palette, state
from ..core.grid import apply_brush, walk_line
from .common import BloxelStrokeMixin

_GHOST_COLOR = (0.30, 1.00, 0.45, 0.35)


class BLOXEL_OT_line(BloxelStrokeMixin, bpy.types.Operator):
    """Click-drag line placement.

    The press fixes the start cell with brush ADD semantics (the empty cell
    in front of the hit face, or the volume entry cell over empty space).
    The ghost preview follows the cursor along the straight cell line until
    release, when the voxels are added as one undo step. A click without a
    drag places a single voxel.
    """

    bl_idname = "bloxel.line"
    bl_label = "Voxel Line"
    bl_description = "Click and drag to draw a straight line of voxels"
    bl_options = {'UNDO'}

    supports_alt_pick = False

    def invoke(self, context, event):
        obj = context.active_object
        # mat 0 means EMPTY: adding would erase voxels instead of writing
        if state.is_bloxel(obj) and palette.active_index(obj) == 0:
            self.report({'WARNING'}, "Add a palette material first")
            return {'CANCELLED'}
        return super().invoke(context, event)

    def _bind(self, context, obj) -> None:
        super()._bind(context, obj)
        self._start = None
        self._end = None
        self._preview = []

    def apply_at(self, context, event):
        target = self._placement(context, event)
        if target is None:
            return
        if self._start is None:
            self._start = target
        self._end = target
        self._preview = list(walk_line(self._start, self._end))
        self._highlight.set(self._preview, _GHOST_COLOR, area=context.area)

    def finish(self, context, cancelled: bool):
        if not cancelled and self._preview:
            if self._place(palette.active_index(self.obj)):
                self._changed = True
        super().finish(context, cancelled)

    # ---------------------------------------------------------------- helpers
    def _placement(self, context, event):
        """Brush ADD placement cell under the cursor, or None."""
        res = self.pick(context, event)
        if res is None:
            return None
        if res.hit is not None:
            h = res.hit
            return (h.cell[0] + h.normal[0],
                    h.cell[1] + h.normal[1],
                    h.cell[2] + h.normal[2])
        return res.entry_cell

    def _place(self, mat: int) -> int:
        changed = 0
        for cell in self._preview:
            changed += apply_brush(self.rt.grid, cell, (0, 0, 1),
                                   'SQUARE', 1, 'ADD', mat,
                                   self.bmin, self.bmax)
        return changed
