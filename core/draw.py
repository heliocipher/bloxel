"""Viewport overlays: working-volume grid and tool highlight previews.

Performance notes: GPU batches are cached and only rebuilt when their data
changes (rebuilding per draw causes lag on orbit/zoom). Redraw requests are
coalesced to ~60 Hz (cursor motion fires per mousemove; without throttling
every cell crossing forces a full viewport redraw).
"""
from __future__ import annotations

import time
import traceback

import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from . import state

_CORNERS = [(x, y, z) for x in (0, 1) for y in (0, 1) for z in (0, 1)]
_EDGES = [(a, b) for i, a in enumerate(_CORNERS) for b in _CORNERS[i + 1:]
          if sum(1 for k in range(3) if a[k] != b[k]) == 1]

_overlay_error_reported = False
_overlay_shader = None


def _uniform_color_shader():
    """Shared UNIFORM_COLOR shader (from_builtin per draw call is wasteful)."""
    global _overlay_shader
    if _overlay_shader is None:
        _overlay_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    return _overlay_shader


def _report_draw_error_once() -> None:
    """Draw-callback exceptions flood the console on every redraw; report once."""
    global _overlay_error_reported
    if not _overlay_error_reported:
        _overlay_error_reported = True
        traceback.print_exc()
        print("[bloxel] overlay draw error (further errors suppressed)")


# ---------------------------------------------------------------------------
# redraw coalescing

_REDRAW_INTERVAL = 1.0 / 60.0
_redraw_last = 0.0
_redraw_flush_scheduled = False


def request_redraw(area=None) -> None:
    """Tag a viewport redraw, at most ~60x/sec; bursts coalesce via a timer."""
    global _redraw_last, _redraw_flush_scheduled
    now = time.monotonic()
    if now - _redraw_last >= _REDRAW_INTERVAL:
        _redraw_last = now
        if area is not None:
            area.tag_redraw()
        else:
            tag_redraw_all()
    elif not _redraw_flush_scheduled:
        _redraw_flush_scheduled = True
        bpy.app.timers.register(_flush_redraw, first_interval=_REDRAW_INTERVAL)


def _flush_redraw():
    global _redraw_flush_scheduled, _redraw_last
    _redraw_flush_scheduled = False
    _redraw_last = time.monotonic()
    tag_redraw_all()
    return None  # one-shot timer


def tag_redraw_all() -> None:
    wm = bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


# ---------------------------------------------------------------------------
# volume grid overlay

_GRID_COLOR = (0.45, 0.45, 0.45, 0.55)

_overlay_handler = None
_highlights: list["Highlight"] = []
_overlay_cache_key = None
_overlay_cache_batch = None


def _strided_coords(v0: int, v1: int, stride: int = 1) -> list[int]:
    """Integer line positions from v0 to v1 inclusive at `stride` steps."""
    coords = list(range(v0, v1 + 1, max(stride, 1)))
    if coords[-1] != v1:
        coords.append(v1)
    return coords


def _axis_coords(v0: int, v1: int, stride: int) -> np.ndarray:
    coords = np.arange(v0, v1 + 1, max(stride, 1), dtype=np.float32)
    if coords[-1] != v1:
        coords = np.append(coords, v1)
    return coords


def _face_grid(plane_axis, pcoord, a0_axis, a0_start, a0_end,
               a1_axis, a1_start, a1_end, stride):
    """Line endpoints for one grid face (numpy-vectorized)."""
    c0 = _axis_coords(a0_start, a0_end, stride)
    c1 = _axis_coords(a1_start, a1_end, stride)
    n = len(c0)
    seg = np.zeros((n, 2, 3), dtype=np.float32)
    seg[:, :, plane_axis] = pcoord
    seg[:, :, a0_axis] = c0[:, None]
    seg[:, 0, a1_axis] = a1_start
    seg[:, 1, a1_axis] = a1_end
    pts = [seg.reshape(-1, 3)]
    n = len(c1)
    seg = np.zeros((n, 2, 3), dtype=np.float32)
    seg[:, :, plane_axis] = pcoord
    seg[:, :, a1_axis] = c1[:, None]
    seg[:, 0, a0_axis] = a0_start
    seg[:, 1, a0_axis] = a0_end
    pts.append(seg.reshape(-1, 3))
    return np.concatenate(pts, axis=0)


def _volume_grid_lines(bmin, bmax, view_dir, inside=False, stride=1):
    """Grey grid on the volume faces the camera looks at, as an (N, 3)
    float32 array of line endpoints (pairs in order).

    Camera outside: the three near faces (where the empty-space raycast
    enters). Camera inside: the three exit faces (where it leaves). Either
    way the visible grid cell is always the placement cell. stride=1 draws
    one line per voxel, at any volume size (no caps - the user's grid is
    unit-resolution by design).
    """
    x0, y0, z0 = bmin
    x1, y1, z1 = bmax[0] + 1, bmax[1] + 1, bmax[2] + 1

    def face(axis: int, lo, hi) -> float:
        if inside:
            return lo if view_dir[axis] < 0 else hi
        return hi if view_dir[axis] < 0 else lo

    return np.concatenate([
        _face_grid(0, face(0, x0, x1), 1, y0, y1, 2, z0, z1, stride),
        _face_grid(1, face(1, y0, y1), 2, z0, z1, 0, x0, x1, stride),
        _face_grid(2, face(2, z0, z1), 0, x0, x1, 1, y0, y1, stride),
    ], axis=0)


def _draw_overlay():
    try:
        _draw_overlay_impl()
    except Exception:
        _report_draw_error_once()


def _draw_overlay_impl():
    global _overlay_cache_key, _overlay_cache_batch
    context = bpy.context
    obj = getattr(context, "active_object", None)
    if not state.is_bloxel(obj):
        return
    bmin, bmax = state.get_bounds(obj)
    mw = obj.matrix_world
    inv = mw.inverted()
    region = getattr(context, "region", None)
    rv3d = getattr(context, "region_data", None)
    if rv3d is not None:
        # camera forward in world space: local -Z of the view rotation
        view_dir = inv.to_3x3() @ (rv3d.view_rotation @ Vector((0.0, 0.0, -1.0)))
        # reference origin matching what the tool raycast uses
        origin = None
        if region is not None and region.width > 0:
            from bpy_extras import view3d_utils
            origin = view3d_utils.region_2d_to_origin_3d(
                region, rv3d, (region.width // 2, region.height // 2))
        if origin is None:
            origin = rv3d.view_matrix.inverted().translation
        o = inv @ origin
        inside = all(bmin[i] <= o[i] < bmax[i] + 1 for i in range(3))
    else:
        view_dir = Vector((0.0, 0.0, -1.0))
        inside = False

    # face choice depends only on the per-axis sign of the view direction
    signs = tuple(0 if view_dir[i] >= 0 else 1 for i in range(3))
    key = (obj.name, bmin, bmax, inside, signs, tuple(mw))
    if key != _overlay_cache_key:
        local_pts = _volume_grid_lines(bmin, bmax, view_dir, inside, 1)
        # vectorized world transform (huge grids must not loop in Python)
        rot = np.array(mw.to_3x3(), dtype=np.float64).T
        trans = np.array(mw.translation, dtype=np.float64)
        world_pts = (local_pts.astype(np.float64) @ rot + trans).astype(np.float32)
        shader = _uniform_color_shader()
        _overlay_cache_batch = batch_for_shader(shader, 'LINES', {"pos": world_pts})
        _overlay_cache_key = key

    shader = _uniform_color_shader()
    gpu.state.blend_set('ALPHA')
    # LESS_EQUAL: boundary voxels share the grid plane; drawing after them
    # at equal depth keeps the grid visible without z-fighting
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.line_width_set(1.0)
    shader.bind()
    shader.uniform_float("color", _GRID_COLOR)
    _overlay_cache_batch.draw(shader)
    gpu.state.blend_set('NONE')


# ---------------------------------------------------------------------------
# selection overlay (fuzzy select tool)
#
# Unlike Highlight, this reads the live selection set from the runtime on
# every draw, so undo/redo/load restore the selection display with no extra
# handlers. Geometry is built with numpy: a selection can hold many thousands
# of cells and a per-cell Python loop would stall the viewport.

_SELECTION_COLOR = (1.00, 0.85, 0.10, 0.40)
_SELECTION_MAX_CELLS = 65536  # display cap for pathologically large selections

_NP_EDGE_A = np.asarray([a for a, _ in _EDGES], dtype=np.float32)
_NP_EDGE_B = np.asarray([b for _, b in _EDGES], dtype=np.float32)
_NP_TOP_TRI = np.asarray([[0, 0, 1], [1, 0, 1], [1, 1, 1],
                          [0, 0, 1], [1, 1, 1], [0, 1, 1]], dtype=np.float32)
_EMPTY_PTS = np.zeros((0, 3), dtype=np.float32)

_selection_handler = None
_selection_cache_key = None
_selection_cache_lines = None
_selection_cache_tris = None


def selection_geometry(cells, mw):
    """World-space (line points (24N, 3), top-face (6N, 3)) for the cells.

    One wireframe box and one top-face fill per cell, both vectorized.
    Cells above _SELECTION_MAX_CELLS are dropped; set order is arbitrary,
    which is fine because an arbitrary subset still marks the selection.
    """
    arr = np.asarray(list(cells)[:_SELECTION_MAX_CELLS],
                     dtype=np.float32).reshape(-1, 3)
    if arr.shape[0] == 0:
        return _EMPTY_PTS, _EMPTY_PTS
    starts = arr[:, None, :] + _NP_EDGE_A[None, :, :]
    ends = arr[:, None, :] + _NP_EDGE_B[None, :, :]
    local_lines = np.stack([starts, ends], axis=2).reshape(-1, 3)
    local_tris = (arr[:, None, :] + _NP_TOP_TRI[None, :, :]).reshape(-1, 3)
    rot = np.array(mw.to_3x3(), dtype=np.float64).T
    trans = np.array(mw.translation, dtype=np.float64)
    lines = (local_lines.astype(np.float64) @ rot + trans).astype(np.float32)
    tris = (local_tris.astype(np.float64) @ rot + trans).astype(np.float32)
    return lines, tris


def _draw_selection():
    try:
        _draw_selection_impl()
    except Exception:
        _report_draw_error_once()


def _draw_selection_impl():
    global _selection_cache_key, _selection_cache_lines, _selection_cache_tris
    context = bpy.context
    obj = getattr(context, "active_object", None)
    if not state.is_bloxel(obj):
        return
    rt = state.runtime(obj)
    if not rt.selection:
        return
    mw = obj.matrix_world
    # rev identifies the selection content: it changes on every commit and is
    # restored by undo/redo, so stale batches cannot survive a history step.
    # as_pointer guards against a different object that reuses the name+rev.
    key = (obj.as_pointer(), rt.rev, tuple(mw))
    if key != _selection_cache_key:
        shader = _uniform_color_shader()
        lines, tris = selection_geometry(rt.selection, mw)
        _selection_cache_lines = batch_for_shader(shader, 'LINES', {"pos": lines})
        _selection_cache_tris = batch_for_shader(shader, 'TRIS', {"pos": tris})
        _selection_cache_key = key

    shader = _uniform_color_shader()
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('LESS_EQUAL')
    shader.bind()
    shader.uniform_float("color", _SELECTION_COLOR)
    _selection_cache_tris.draw(shader)
    gpu.state.line_width_set(2.0)
    shader.uniform_float("color", (*_SELECTION_COLOR[:3], 1.0))
    _selection_cache_lines.draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


class Highlight:
    """Translucent highlight of the cells a tool is about to affect.

    The object is held by name and re-resolved each draw: direct bpy struct
    references go stale across undo/redo and would crash the draw callback.
    `visible_check` (optional callable) can suppress drawing, for example
    when the owning tool is no longer active. Batches are cached; they
    rebuild only when cells or the object matrix change.
    """

    MAX_CELLS = 2048

    def __init__(self, obj) -> None:
        self.obj_name = obj.name
        self.cells: list[tuple] = []
        self.color = (1.0, 1.0, 1.0, 0.35)
        self.cells2: list[tuple] = []
        self.color2 = None
        self.visible_check = None
        self._handler = None
        self._lines_batch = None
        self._tris_batch = None
        self._lines_batch2 = None
        self._tris_batch2 = None
        self._batch_matrix = None

    def start(self) -> None:
        self._handler = bpy.types.SpaceView3D.draw_handler_add(
            self._draw, (), 'WINDOW', 'POST_VIEW')
        _highlights.append(self)

    def stop(self) -> None:
        if self._handler is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handler, 'WINDOW')
            self._handler = None
        if self in _highlights:
            _highlights.remove(self)
        tag_redraw_all()

    def set(self, cells, color, cells2=(), color2=None, area=None) -> None:
        cells = list(cells)[: self.MAX_CELLS]
        cells2 = list(cells2)[: self.MAX_CELLS]
        # cursor motion fires on every mousemove; skip redundant updates and redraws
        if (cells == self.cells and color == self.color
                and cells2 == self.cells2
                and (color2 if color2 is not None else color) == self.color2):
            return
        self.cells = cells
        self.color = color
        self.cells2 = cells2
        self.color2 = color2 if color2 is not None else color
        self._batch_matrix = None  # force batch rebuild on next draw
        request_redraw(area)

    def clear(self, area=None) -> None:
        if self.cells or self.cells2:
            self.cells = []
            self.cells2 = []
            self._batch_matrix = None
            request_redraw(area)

    def _draw(self) -> None:
        try:
            self._draw_impl()
        except Exception:
            _report_draw_error_once()

    def _draw_impl(self) -> None:
        if not self.cells and not self.cells2:
            return
        if self.visible_check is not None and not self.visible_check():
            return
        obj = bpy.data.objects.get(self.obj_name)
        if obj is None:
            self.cells = []
            return
        mw = obj.matrix_world

        if self._lines_batch is None or self._batch_matrix is None \
                or mw != self._batch_matrix:
            self._rebuild_batches(mw)

        shader = _uniform_color_shader()
        gpu.state.blend_set('ALPHA')
        shader.bind()
        shader.uniform_float("color", self.color)
        self._tris_batch.draw(shader)
        if self._tris_batch2 is not None:
            shader.uniform_float("color", self.color2)
            self._tris_batch2.draw(shader)
        gpu.state.blend_set('NONE')
        gpu.state.line_width_set(2.0)
        shader.uniform_float("color", (*self.color[:3], 1.0))
        self._lines_batch.draw(shader)
        if self._lines_batch2 is not None:
            shader.uniform_float("color", (*self.color2[:3], 1.0))
            self._lines_batch2.draw(shader)
        gpu.state.line_width_set(1.0)

    @staticmethod
    def _build_group(mw, cells):
        line_pts = []
        tri_pts = []
        for cx, cy, cz in cells:
            for a, b in _EDGES:
                line_pts.append(mw @ Vector((cx + a[0], cy + a[1], cz + a[2])))
                line_pts.append(mw @ Vector((cx + b[0], cy + b[1], cz + b[2])))
            # top-face fill reads well enough; 36 tris/cell is wasteful
            tri_pts.append(mw @ Vector((cx, cy, cz + 1)))
            tri_pts.append(mw @ Vector((cx + 1, cy, cz + 1)))
            tri_pts.append(mw @ Vector((cx + 1, cy + 1, cz + 1)))
            tri_pts.append(mw @ Vector((cx, cy, cz + 1)))
            tri_pts.append(mw @ Vector((cx + 1, cy + 1, cz + 1)))
            tri_pts.append(mw @ Vector((cx, cy + 1, cz + 1)))
        shader = _uniform_color_shader()
        return (batch_for_shader(shader, 'LINES', {"pos": line_pts}),
                batch_for_shader(shader, 'TRIS', {"pos": tri_pts}))

    def _rebuild_batches(self, mw) -> None:
        self._lines_batch, self._tris_batch = self._build_group(mw, self.cells)
        if self.cells2:
            self._lines_batch2, self._tris_batch2 = self._build_group(mw, self.cells2)
        else:
            self._lines_batch2 = self._tris_batch2 = None
        self._batch_matrix = mw.copy()


def register() -> None:
    global _overlay_handler, _selection_handler, _overlay_error_reported
    global _overlay_cache_key, _overlay_shader, _selection_cache_key
    _overlay_error_reported = False
    _overlay_cache_key = None
    _overlay_shader = None
    _selection_cache_key = None
    if _overlay_handler is None:
        _overlay_handler = bpy.types.SpaceView3D.draw_handler_add(
            _draw_overlay, (), 'WINDOW', 'POST_VIEW')
    if _selection_handler is None:
        _selection_handler = bpy.types.SpaceView3D.draw_handler_add(
            _draw_selection, (), 'WINDOW', 'POST_VIEW')


def unregister() -> None:
    global _overlay_handler, _selection_handler
    for highlight in list(_highlights):
        highlight.stop()
    if _overlay_handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_overlay_handler, 'WINDOW')
        _overlay_handler = None
    if _selection_handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_selection_handler, 'WINDOW')
        _selection_handler = None
