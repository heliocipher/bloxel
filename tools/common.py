"""Shared machinery for Bloxel modal tool operators.

Tools are thin modal wrappers: the actual voxel edits live in pure core
functions (grid.apply_brush etc.) so they stay headless-testable.
"""
from __future__ import annotations

import time

import bpy
from bpy_extras import view3d_utils

from ..core import draw, mesher, serialize, state
from ..core.grid import StrokeMaskGrid, raycast

REBUILD_INTERVAL = 0.05  # seconds between mesh rebuilds during a stroke

# ---------------------------------------------------------------------------
# cursor highlight: a persistent Highlight updated by the tools' MOUSEMOVE
# keymap entry, so the target preview is visible without holding the mouse
# button. Keep in sync with the tool ids in workspace.py.
_CURSOR_TOOL_IDS = {"bloxel.brush_tool", "bloxel.eraser_tool"}
_cursor_highlight: draw.Highlight | None = None


def _cursor_highlight_visible() -> bool:
    try:
        context = bpy.context
        if _cursor_highlight is None:
            return False
        obj = bpy.data.objects.get(_cursor_highlight.obj_name)
        if obj is None or not state.is_bloxel(obj):
            return False
        if context.active_object is None or context.active_object.name != obj.name:
            return False
        tool = context.workspace.tools.from_space_view3d_mode('OBJECT')
        return tool is not None and tool.idname in _CURSOR_TOOL_IDS
    except Exception:
        return False


def cursor_highlight_for(obj) -> draw.Highlight:
    global _cursor_highlight
    if _cursor_highlight is not None and _cursor_highlight.obj_name != obj.name:
        cursor_highlight_stop()
    if _cursor_highlight is None:
        _cursor_highlight = draw.Highlight(obj)
        _cursor_highlight.visible_check = _cursor_highlight_visible
        _cursor_highlight.start()
    return _cursor_highlight


def cursor_highlight_clear() -> None:
    if _cursor_highlight is not None:
        _cursor_highlight.clear()


def cursor_highlight_stop() -> None:
    global _cursor_highlight
    if _cursor_highlight is not None:
        _cursor_highlight.stop()
        _cursor_highlight = None


def drag_along_axis(press_mouse, mouse, screen_dir, screen_len) -> float:
    """Signed voxel drag distance along an axis, from screen-space data.

    press_mouse/mouse: (x, y) region coords. screen_dir: region-space vector
    of one voxel along the axis. screen_len: its length. The result is in
    voxels (negative when dragging against the axis).
    """
    if screen_len < 1e-6:
        return 0.0
    proj = ((mouse[0] - press_mouse[0]) * screen_dir[0]
            + (mouse[1] - press_mouse[1]) * screen_dir[1]) / screen_len
    return proj / screen_len


def event_ray(context, event, obj):
    """Mouse event -> (origin, direction) in the object's local space."""
    region = context.region
    rv3d = context.region_data
    if region is None or rv3d is None:
        return None
    coord = (event.mouse_region_x, event.mouse_region_y)
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    if origin is None or direction is None:
        return None
    inv = obj.matrix_world.inverted()
    local_origin = inv @ origin
    local_dir = (inv.to_3x3() @ direction).normalized()
    return local_origin, local_dir


class BloxelStrokeMixin:
    """Mixin with the stroke lifecycle: raycast picking, highlight preview,
    throttled mesh rebuild, snapshot-based cancel, single undo step.

    IMPORTANT: plain object mixin. Never subclass a *registered* bpy type
    (breaks the base's Python<->RNA binding: 'unable to get Python class
    for RNA struct' and inoperative operator calls).
    """

    #: allow Alt+LMB material picking mid-tool
    supports_alt_pick = True

    def _bind(self, context, obj) -> None:
        """Attach the operator to a Bloxel object's runtime state."""
        self.obj = obj
        self.rt = state.runtime(obj)
        self.bmin, self.bmax = state.get_bounds(obj)
        self.stroking = False
        self._overlay = None

    def invoke(self, context, event):
        obj = context.active_object
        if not state.is_bloxel(obj):
            self.report({'WARNING'}, "Select a Bloxel object first")
            return {'CANCELLED'}
        self._bind(context, obj)
        self._changed = False
        self._snapshot = None
        self._last_base = None
        self._last_rebuild = 0.0
        self._miss_reported = False
        self._highlight = draw.Highlight(obj)
        self._highlight.start()

        if event.alt and self.supports_alt_pick and event.value == 'PRESS':
            self.pick_material(context, event)
            self._highlight.stop()
            return {'FINISHED'}

        cursor_highlight_clear()  # stroke highlight takes over from the cursor highlight
        self.begin_stroke()
        self.apply_at(context, event)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            if self.stroking:
                self.apply_at(context, event)
            else:
                self.update_highlight(context, event)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self.finish(context, cancelled=False)
            return {'FINISHED'}
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            self.finish(context, cancelled=True)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    # ------------------------------------------------------------- lifecycle
    def begin_stroke(self):
        self._snapshot = serialize.dumps(self.rt.grid, self.rt.selection)
        self._overlay = {}  # cell -> value at stroke start (stroke mask)
        self.stroking = True

    def finish(self, context, cancelled: bool):
        self.stroking = False
        self._highlight.stop()
        if cancelled:
            if self._snapshot is not None:
                self.rt.grid, self.rt.selection = serialize.loads(self._snapshot)
                # restored grid has no invalid flags; cached chunks may still
                # hold the stroke's geometry, so drop the cache wholesale
                self.rt.mesher.cache.clear()
                self.rebuild(force=True)
            self._overlay = None
            return
        if self._changed:
            self.rebuild(force=True)
            state.commit(self.obj, self.rt)
        self._overlay = None

    def rebuild(self, force: bool = False):
        now = time.monotonic()
        if not force and now - self._last_rebuild < REBUILD_INTERVAL:
            return
        self._last_rebuild = now
        mesher.rebuild_mesh(self.obj, self.rt)
        draw.tag_redraw_all()

    # ---------------------------------------------------------------- picking
    def pick(self, context, event):
        """RayResult for the current mouse position.

        Mid-stroke the ray runs against the stroke-masked grid (surface as
        it was at stroke start), so placements only happen when the cursor
        reaches a new cell of the original surface.
        """
        ray = event_ray(context, event, self.obj)
        if ray is None:
            return None
        origin, direction = ray
        grid = self.rt.grid
        if self.stroking and self._overlay is not None:
            grid = StrokeMaskGrid(grid, self._overlay)
        return raycast(grid, origin, direction, self.bmin, self.bmax)

    def pick_material(self, context, event):
        res = self.pick(context, event)
        if res is not None and res.hit is not None:
            mat = self.rt.grid.get(*res.hit.cell)
            if mat:
                self.obj.bloxel_palette_index = mat - 1
                self.report({'INFO'}, f"Picked material slot {mat}")

    # ------------------------------------------------------------ for subclass
    def apply_at(self, context, event):
        raise NotImplementedError

    def update_highlight(self, context, event):
        pass
