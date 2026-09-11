"""Extrude tool: pull coplanar same-material face regions outward."""
from __future__ import annotations

import math

import bpy
from mathutils import Vector

from ..core import state
from ..core.grid import extrude_layers, face_region
from .common import BloxelStrokeMixin, drag_along_axis, event_ray

_ADD_COLOR = (1.00, 0.60, 0.20, 0.35)
_DEL_COLOR = (1.00, 0.25, 0.20, 0.35)
_MAX_LAYERS = 256


class BLOXEL_OT_extrude(BloxelStrokeMixin, bpy.types.Operator):
    """Bidirectional face pull.

    The region is fixed at press time: all same-material voxels connected to
    the hit face that expose a face in the same direction. Dragging along
    the normal pulls layers outward; dragging the opposite way deletes the
    original surface voxels and removes voxels deeper along the axis (for
    example, delete a whole line by clicking one end and dragging toward
    the other). Everything is reversible within the stroke.
    """

    bl_idname = "bloxel.extrude"
    bl_label = "Voxel Extrude"
    bl_description = "Pull the coplanar same-material face region outward"
    bl_options = {'UNDO'}

    supports_alt_pick = False

    def _bind(self, context, obj) -> None:
        super()._bind(context, obj)
        self._region = None
        self._normal = None
        self._mat = 0
        self._press_mouse = (0, 0)
        self._screen_dir = None
        self._screen_len = 0.0
        self._layers = 0
        self._added = set()    # cells created by this stroke
        self._deleted = {}     # pre-existing cells removed: cell -> old value

    # ------------------------------------------------------------- lifecycle
    def apply_at(self, context, event):
        if self._region is None:
            self._begin_region(context, event)
            if self._region is None:
                return
        target = self._drag_layers(event)
        if target is None:
            return
        target = max(-_MAX_LAYERS, min(_MAX_LAYERS, target))
        if target != self._layers:
            changed = extrude_layers(self.rt.grid, self._region, self._normal,
                                     self._layers, target, self._mat,
                                     self.bmin, self.bmax,
                                     self._added, self._deleted)
            self._layers = target
            if changed:
                self.rebuild()
        # net state: the stroke counts only if something it did survives
        self._changed = bool(self._added or self._deleted)
        self._show_highlight(context)

    # ---------------------------------------------------------------- picking
    def _begin_region(self, context, event) -> None:
        res = self.pick(context, event)
        if res is None or res.hit is None:
            if not self._miss_reported:
                self.report({'INFO'}, "Click on a voxel face to extrude")
                self._miss_reported = True
            return
        cell, normal = res.hit.cell, res.hit.normal
        mat = self.rt.grid.get(*cell)
        if mat == 0:
            return
        face_set = face_region(self.rt.grid, cell, normal, self.bmin, self.bmax)
        if not face_set:
            return
        # screen-space direction of one voxel along the face normal: the
        # pull distance comes from the cursor travel projected onto it
        self._press_mouse = (event.mouse_region_x, event.mouse_region_y)
        self._screen_dir = None
        self._screen_len = 0.0
        rv3d = getattr(context, "region_data", None)
        if rv3d is not None:
            from bpy_extras import view3d_utils
            win_region = context.region
            if win_region is not None:
                mw = self.obj.matrix_world
                ray = event_ray(context, event, self.obj)
                face_point = ray[0] + ray[1] * res.hit.distance
                p_world = mw @ face_point
                n_world = mw.to_3x3() @ Vector(normal)
                p2 = view3d_utils.location_3d_to_region_2d(win_region, rv3d, p_world)
                p3 = view3d_utils.location_3d_to_region_2d(win_region, rv3d,
                                                           p_world + n_world)
                if p2 is not None and p3 is not None:
                    self._screen_dir = p3 - p2
                    self._screen_len = self._screen_dir.length
        self._region = face_set
        self._normal = normal
        self._mat = mat
        self._layers = 0
        self._added = set()
        self._deleted = {}

    def _drag_layers(self, event):
        """1 + floor(dragged voxels along the normal). Positive = pull out,
        negative = delete the surface and deeper voxels along -normal.
        None when the screen-space setup is unavailable."""
        if self._screen_dir is None:
            return self._layers
        mouse = (event.mouse_region_x, event.mouse_region_y)
        delta = drag_along_axis(self._press_mouse, mouse,
                                self._screen_dir, self._screen_len)
        return 1 + math.floor(delta)

    def _show_highlight(self, context) -> None:
        add_cells = []
        del_cells = []
        nx, ny, nz = self._normal
        for cx, cy, cz in self._region:
            for k in range(1, max(self._layers, 0) + 1):
                add_cells.append((cx + nx * k, cy + ny * k, cz + nz * k))
            for k in range(self._layers + 1, 1):  # k = layers..0 (deleted)
                del_cells.append((cx + nx * k, cy + ny * k, cz + nz * k))
        self._highlight.set(add_cells, _ADD_COLOR, del_cells, _DEL_COLOR,
                            area=context.area)

