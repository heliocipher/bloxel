"""Fuzzy select (click) and rectangle select (drag) tools.

Fuzzy select replaces the selection with the picked region; Shift adds,
Ctrl removes; clicking empty space clears. Rectangle select works the same
way from a screen-space drag, in visible-only or strikethrough mode.

The selection lives in Runtime.selection, persists through the serialized
blob, and is drawn by the selection overlay in core.draw.
"""
from __future__ import annotations

import bpy

from ..core import draw, state
from ..core.grid import raycast, rectangle_select, select_region
from .common import event_ray


def _report_selection(operator, selection) -> None:
    if selection:
        operator.report({'INFO'}, f"Selected {len(selection)} voxels")
    else:
        operator.report({'INFO'}, "Selection cleared")


class BLOXEL_OT_fuzzy_select(bpy.types.Operator):
    bl_idname = "bloxel.fuzzy_select"
    bl_label = "Voxel Fuzzy Select"
    bl_description = ("Select the clicked voxel's connected same-material "
                      "region or all voxels of that material (Shift adds, "
                      "Ctrl removes, empty space clears)")
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
        settings = context.scene.bloxel_tools
        old = set(rt.selection)
        if res.hit is None:
            rt.selection = set()
        else:
            cells = select_region(
                rt.grid, res.hit.cell, bmin, bmax,
                contiguous=(settings.select_mode == 'CONNECTED'))
            if event.shift:
                rt.selection |= cells
            elif event.ctrl:
                rt.selection -= cells
            else:
                rt.selection = set(cells)
        if rt.selection != old:
            state.commit(obj, rt)
            draw.tag_redraw_all()
            _report_selection(self, rt.selection)
        return {'FINISHED'}


class BLOXEL_OT_rect_select(bpy.types.Operator):
    """Box select: drag a screen rectangle over the model.

    Visible Only keeps the first voxel each sample ray hits; Strikethrough
    keeps every voxel whose projected centre is inside the rectangle. The
    selection applies on mouse release as one undo step.
    """

    bl_idname = "bloxel.rect_select"
    bl_label = "Voxel Rectangle Select"
    bl_description = ("Drag a rectangle to select the voxels inside it: "
                      "visible only or strikethrough (Shift adds, Ctrl removes)")
    bl_options = {'UNDO'}

    def invoke(self, context, event):
        obj = context.active_object
        if not state.is_bloxel(obj):
            self.report({'WARNING'}, "Select a Bloxel object first")
            return {'CANCELLED'}
        if context.region is None or context.region_data is None:
            return {'CANCELLED'}
        self.obj = obj
        self.rt = state.runtime(obj)
        self.bmin, self.bmax = state.get_bounds(obj)
        self._start = (event.mouse_region_x, event.mouse_region_y)
        self._shift = event.shift
        self._ctrl = event.ctrl
        self._rect = draw.ScreenRect()
        self._rect.start()
        self._rect.set(context.region, self._start, self._start)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            self._rect.set(context.region, self._start,
                           (event.mouse_region_x, event.mouse_region_y))
            draw.request_redraw(context.area)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self._rect.stop()
            self._apply(context, event)
            return {'FINISHED'}
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            self._rect.stop()
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def _apply(self, context, event) -> None:
        x0, y0 = self._start
        x1, y1 = event.mouse_region_x, event.mouse_region_y
        settings = context.scene.bloxel_tools
        mvp = context.region_data.perspective_matrix @ self.obj.matrix_world
        cells = rectangle_select(
            self.rt.grid, (x0, y0, x1, y1), mvp,
            context.region.width, context.region.height,
            self.bmin, self.bmax,
            visible_only=(settings.rect_select_mode == 'VISIBLE'))
        old = set(self.rt.selection)
        if self._shift:
            self.rt.selection |= cells
        elif self._ctrl:
            self.rt.selection -= cells
        else:
            self.rt.selection = set(cells)
        if self.rt.selection != old:
            state.commit(self.obj, self.rt)
            draw.tag_redraw_all()
            _report_selection(self, self.rt.selection)
