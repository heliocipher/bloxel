"""Move & Rotate tool: transform the selection with a viewport gizmo.

The tool owns no geometry of its own; it hit-tests the persistent gizmo in
core.gizmo (drawn while this tool is active) and then drags the picked
handle. Arrows translate the selection along one local axis, rings rotate
it in 90-degree steps around one local axis. The grid changes only on
release, so a cancelled drag leaves no trace and the whole transform is a
single undo step.
"""
from __future__ import annotations

import math

import bpy

from ..core import draw, gizmo, mesher, state
from ..core.grid import apply_mapping, move_mapping, rotate_mapping
from .common import drag_along_axis

_PREVIEW_ALPHA = 0.35
_MIN_RING_RADIUS = 24.0  # pixels: inside this the ring angle is unstable


def apply_transform(obj, rt, mapping: dict, bmin, bmax) -> tuple[int, set]:
    """Apply a finished transform: edit, re-mesh, update selection, commit.

    Kept out of the modal operator so the full path (including the mesh
    rebuild) stays headless-testable.
    """
    changed, selection = apply_mapping(rt.grid, mapping, bmin, bmax)
    if not changed:
        return 0, selection
    rt.selection = selection
    mesher.rebuild_mesh(obj, rt)
    state.commit(obj, rt)
    draw.tag_redraw_all()
    return changed, selection


class BLOXEL_OT_transform(bpy.types.Operator):
    """Move or rotate the selected voxels.

    Drag a coloured arrow to slide the selection along that axis (clamped
    to the working volume). Drag a ring around the selection to rotate it
    by 90-degree steps; the sweep direction follows the cursor. Right mouse
    or Escape cancels.
    """

    bl_idname = "bloxel.transform"
    bl_label = "Voxel Move & Rotate"
    bl_description = ("Drag an axis arrow to move the selected voxels, or a "
                      "ring to rotate them in 90-degree steps")
    bl_options = {'UNDO'}

    def invoke(self, context, event):
        obj = context.active_object
        if not state.is_bloxel(obj):
            self.report({'WARNING'}, "Select a Bloxel object first")
            return {'CANCELLED'}
        self.obj = obj
        self.rt = state.runtime(obj)
        self.bmin, self.bmax = state.get_bounds(obj)
        self.cells = {cell for cell in self.rt.selection
                      if self.rt.grid.get(*cell) != 0}
        if not self.cells:
            self.report({'WARNING'}, "Select voxels first")
            return {'CANCELLED'}
        data = gizmo.info(context)
        if data is None:
            return {'CANCELLED'}
        mouse = (event.mouse_region_x, event.mouse_region_y)
        self.handle = gizmo.pick(context, mouse)
        if self.handle is None:
            self.report({'INFO'}, "Click a gizmo arrow or ring")
            return {'CANCELLED'}
        self.data = data
        self.press = mouse
        self.offset = 0
        self.steps = 0
        self._mapping = {}
        self._prev_angle = None
        self._accum = 0.0
        self._highlight = draw.Highlight(obj)
        self._highlight.start()
        gizmo.set_active(self.handle)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            self._update(event)
            self._preview(context)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            return self._finish(context)
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            self._cancel()
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    # ------------------------------------------------------------- transform
    def _update(self, event) -> None:
        kind, axis = self.handle
        mouse = (event.mouse_region_x, event.mouse_region_y)
        if kind == gizmo.MOVE:
            screen_dir, screen_len = self.data.axis_px[axis]
            self.offset = int(math.floor(
                drag_along_axis(self.press, mouse, screen_dir, screen_len)
                + 0.5))
            offset = [0, 0, 0]
            offset[axis] = self.offset
            self._mapping = move_mapping(self.cells, tuple(offset),
                                         self.bmin, self.bmax)
            return
        cx, cy = self.data.center_xy
        radius = math.hypot(mouse[0] - cx, mouse[1] - cy)
        if radius < _MIN_RING_RADIUS:
            self._prev_angle = None  # the angle here is unstable
            return
        angle = math.atan2(mouse[1] - cy, mouse[0] - cx)
        if self._prev_angle is None:
            self._prev_angle = angle
            return
        delta = angle - self._prev_angle
        while delta > math.pi:
            delta -= 2.0 * math.pi
        while delta < -math.pi:
            delta += 2.0 * math.pi
        self._accum += delta
        self._prev_angle = angle
        # a right-hand turn looks counter-clockwise when the axis points at
        # the camera, clockwise when it points away
        sign = 1.0 if self.data.toward[axis] else -1.0
        self.steps = int(math.floor(
            self._accum / (0.5 * math.pi) * sign + 0.5))
        self._mapping = rotate_mapping(self.cells, axis, self.steps,
                                       self.bmin, self.bmax)

    def _preview(self, context) -> None:
        if not self._mapping:
            self._highlight.clear(area=context.area)
            return
        color = (*gizmo.AXIS_COLORS[self.handle[1]], _PREVIEW_ALPHA)
        self._highlight.set(self._mapping.values(), color, area=context.area)

    def _finish(self, context):
        self._highlight.stop()
        gizmo.set_active(None)
        if not self._mapping:
            return {'FINISHED'}
        changed, selection = apply_transform(self.obj, self.rt, self._mapping,
                                             self.bmin, self.bmax)
        if changed:
            verb = "Moved" if self.handle[0] == gizmo.MOVE else "Rotated"
            self.report({'INFO'}, f"{verb} {len(selection)} voxels")
        return {'FINISHED'}

    def _cancel(self) -> None:
        self._highlight.stop()
        gizmo.set_active(None)
