"""Move & Rotate gizmo: handle geometry, drawing and screen-space picking.

The gizmo belongs to the current selection (not to an operator): it stays
visible while the Move & Rotate tool is active, and the operator uses the
same geometry to hit-test the handle under the cursor.

The handles hug the selection's bounding cage instead of meeting at its
centre: each move arrow starts on the cage face and points outward along an
axis, and each rotation half-ring is centred on the cage centre. All three
half-rings share one radius: the largest cage cross-section diagonal, so
every ring clears the whole cage. Arrows are long - they match that radius
when the cage is large, and never shrink below a minimum screen length.

Handles use Blender's axis colours: X red, Y green, Z blue. Arrows translate
the selection along one local axis, half-rings rotate it around one local
axis.
"""
from __future__ import annotations

import math
from typing import NamedTuple

import bpy
import gpu
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector

from . import draw, state
from .grid import selection_bounds, transform_center

TOOL_ID = "bloxel.transform_tool"
MOVE = "move"
ROTATE = "rotate"

AXIS_COLORS = ((1.00, 0.25, 0.25),   # X red
               (0.35, 1.00, 0.35),   # Y green
               (0.45, 0.60, 1.00))   # Z blue
ARROW_MIN_PX = 96.0    # smallest arrow length in screen pixels
PICK_PX = 16.0         # handle click tolerance in screen pixels
THICK_PX = 6.0         # handle thickness in screen pixels
DASH_PX = 4.0          # cage dash length in screen pixels
RING_MIN_PX = 34.0     # smallest ring radius in screen pixels
RING_MARGIN_PX = 8.0   # ring clearance past the cage corners in pixels
ACTIVE_ALPHA = 1.0
IDLE_ALPHA = 0.85
RING_SEGMENTS = 64     # full circle; half-rings use half of it

_UNIT = (Vector((1.0, 0.0, 0.0)),
         Vector((0.0, 1.0, 0.0)),
         Vector((0.0, 0.0, 1.0)))

_active: tuple[str, int] | None = None
_handler = None


class GizmoInfo(NamedTuple):
    center: Vector                       # world-space cage centre
    axes: tuple[Vector, Vector, Vector]  # world-space unit axes
    length: float                        # arrow length in world units
    center_xy: tuple[float, float]       # centre in region pixels
    axis_px: tuple                       # per axis: ((dx, dy), length) per voxel
    toward: tuple[bool, bool, bool]      # ring axis points at the camera
    bounds: tuple                        # local cell bounds (min, max)
    matrix: Matrix                       # object matrix at sample time
    half: tuple[float, float, float]     # cage half-extents in world units
    radii: tuple[float, float, float]    # half-ring radii in world units
    px_per_unit: float                   # screen pixels per world unit


def set_active(handle: tuple[str, int] | None) -> None:
    """Mark a handle as dragged; it draws brighter until cleared."""
    global _active
    _active = handle


def active() -> tuple[str, int] | None:
    return _active


def tool_active(context) -> bool:
    try:
        tool = context.workspace.tools.from_space_view3d_mode('OBJECT')
        return tool is not None and tool.idname == TOOL_ID
    except Exception:
        return False


def info(context) -> GizmoInfo | None:
    """Geometry data for the current selection, or None when unavailable."""
    obj = getattr(context, "active_object", None)
    if not state.is_bloxel(obj):
        return None
    region = getattr(context, "region", None)
    rv3d = getattr(context, "region_data", None)
    if region is None or rv3d is None:
        return None
    bounds = selection_bounds(state.runtime(obj).selection)
    if bounds is None:
        return None
    mw = obj.matrix_world
    center = mw @ Vector(transform_center(bounds))
    center_xy = view3d_utils.location_3d_to_region_2d(region, rv3d, center)
    if center_xy is None:
        return None
    rot = mw.to_3x3()
    raw = []
    for unit in _UNIT:
        v = rot @ unit
        if v.length < 1e-9:
            return None
        raw.append(v)
    axes = tuple(v.normalized() for v in raw)
    # constant screen size: use the axis most perpendicular to the view
    px_per_unit = 0.0
    for axis in axes:
        probe = view3d_utils.location_3d_to_region_2d(region, rv3d, center + axis)
        if probe is not None:
            px_per_unit = max(px_per_unit, math.hypot(probe[0] - center_xy[0],
                                                      probe[1] - center_xy[1]))
    if px_per_unit < 1e-6:
        return None
    # cage half-extents in world units: arrows start on a cage face
    half = tuple((bounds[1][i] + 1 - bounds[0][i]) * 0.5 * raw[i].length
                 for i in range(3))
    # all rings share the largest cage cross-section diagonal, plus clearance;
    # arrows are at least as long as the rings, and never shorter on screen
    # than ARROW_MIN_PX
    base = cage_radius(half) + RING_MARGIN_PX / px_per_unit
    min_radius = RING_MIN_PX / px_per_unit
    radius = max(base, min_radius)
    radii = (radius, radius, radius)
    length = max(base, ARROW_MIN_PX / px_per_unit)
    inv_rot = mw.inverted().to_3x3()
    axis_px = []
    for i, axis in enumerate(axes):
        start = center + axis * half[i]
        tip = view3d_utils.location_3d_to_region_2d(region, rv3d,
                                                    start + axis * length)
        # the arrow spans this many local units (= voxels); the object scale
        # must not change the voxels-per-pixel drag sensitivity
        voxels = (inv_rot @ (axis * length)).length
        start_xy = view3d_utils.location_3d_to_region_2d(region, rv3d, start)
        if tip is None or start_xy is None or voxels < 1e-9:
            axis_px.append(((0.0, 0.0), 0.0))
        else:
            dx, dy = tip[0] - start_xy[0], tip[1] - start_xy[1]
            axis_px.append(((dx / voxels, dy / voxels),
                            math.hypot(dx, dy) / voxels))
    view_dir = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))
    toward = tuple((-view_dir).dot(axis) >= 0.0 for axis in axes)
    return GizmoInfo(center, axes, length, center_xy, tuple(axis_px), toward,
                     bounds, mw.copy(), half, radii, px_per_unit)


def cage_radius(half) -> float:
    """Largest half-ring radius that reaches past every cage cross-section.

    The same value feeds all three rotation rings, so they always match.
    """
    return max(math.hypot(half[(i + 1) % 3], half[(i + 2) % 3])
               for i in range(3))


def _ring_angles(segments: int = RING_SEGMENTS) -> list:
    """Half-ring angles, centred on the +u+v diagonal of the ring plane."""
    n = max(segments // 2, 4)
    step = math.pi / n
    start = 0.25 * math.pi - 0.5 * math.pi
    return [start + step * i for i in range(n + 1)]


def handles(center, axes, half, arrow_len, radii) -> dict:
    """World-space handle segments: {(kind, axis): [((ax,ay,az),(bx,by,bz))]}.

    Move shafts run from the cage face outward; rotation handles are half
    circles around the cage centre at the given radii.
    """
    out = {}
    head = arrow_len * 0.15
    flare = arrow_len * 0.06
    for axis in range(3):
        u = axes[axis]
        p = axes[(axis + 1) % 3]
        q = axes[(axis + 2) % 3]
        start = center + u * half[axis]
        tip = start + u * arrow_len
        base = tip - u * head
        out[(MOVE, axis)] = [
            (start, tip),
            (tip, base + p * flare), (tip, base - p * flare),
            (tip, base + q * flare), (tip, base - q * flare),
        ]
    for axis in range(3):
        u = axes[(axis + 1) % 3]
        v = axes[(axis + 2) % 3]
        pts = [center + (u * math.cos(a) + v * math.sin(a)) * radii[axis]
               for a in _ring_angles()]
        out[(ROTATE, axis)] = [(pts[i], pts[i + 1])
                               for i in range(len(pts) - 1)]
    return out


def _quad(a, b, c, d) -> list:
    return [(a, b, c), (a, c, d)]


def handle_tris(center, axes, half, arrow_len, radii, width) -> dict:
    """Solid world-space geometry for the handles: {(kind, axis): [triangles]}.

    GPU line width is not honored on every backend (Metal draws everything
    1 px), so the gizmo draws solid geometry instead: a square beam per
    arrow shaft, a pyramid per arrow head, a flat ribbon per half-ring.
    `width` is in world units - callers scale it for constant on-screen
    thickness.
    """
    hw = width * 0.5
    head = arrow_len * 0.15
    flare = arrow_len * 0.06
    out = {}
    for axis in range(3):
        u = axes[axis]
        p = axes[(axis + 1) % 3]
        q = axes[(axis + 2) % 3]
        start = center + u * half[axis]
        tip = start + u * arrow_len
        base = tip - u * head
        offsets = (p * hw + q * hw, -p * hw + q * hw,
                   -p * hw - q * hw, p * hw - q * hw)
        c = [start + o for o in offsets]
        b = [base + o for o in offsets]
        tris = []
        for i in range(4):
            j = (i + 1) % 4
            tris += _quad(c[i], c[j], b[j], b[i])
        h = [base + p * flare + q * flare, base - p * flare + q * flare,
             base - p * flare - q * flare, base + p * flare - q * flare]
        for i in range(4):
            tris.append((tip, h[i], h[(i + 1) % 4]))
        tris += _quad(h[0], h[1], h[2], h[3])
        out[(MOVE, axis)] = tris
    for axis in range(3):
        u = axes[(axis + 1) % 3]
        v = axes[(axis + 2) % 3]
        r_in = max(radii[axis] - hw, 0.0)
        r_out = radii[axis] + hw
        inner, outer = [], []
        for angle in _ring_angles():
            d = u * math.cos(angle) + v * math.sin(angle)
            inner.append(center + d * r_in)
            outer.append(center + d * r_out)
        tris = []
        for i in range(len(inner) - 1):
            j = i + 1
            tris.append((inner[i], inner[j], outer[j]))
            tris.append((inner[i], outer[j], outer[i]))
        out[(ROTATE, axis)] = tris
    return out


_BOX_CORNERS = tuple((x, y, z) for x in (0, 1) for y in (0, 1) for z in (0, 1))
_BOX_EDGES = tuple((i, j) for i in range(8) for j in range(i + 1, 8)
                   if bin(i ^ j).count("1") == 1)


def bounds_segments(data: GizmoInfo) -> list:
    """Dashed world-space outline of the selection bounding box.

    Not a pickable handle: it shows what the gizmo will transform.
    """
    mn, mx = data.bounds
    lo = (mn[0], mn[1], mn[2])
    hi = (mx[0] + 1, mx[1] + 1, mx[2] + 1)
    corners = [data.matrix @ Vector((lo[0] + cx * (hi[0] - lo[0]),
                                     lo[1] + cy * (hi[1] - lo[1]),
                                     lo[2] + cz * (hi[2] - lo[2])))
               for cx, cy, cz in _BOX_CORNERS]
    dash = DASH_PX / data.px_per_unit
    out = []
    for i, j in _BOX_EDGES:
        a, b = corners[i], corners[j]
        total = (b - a).length
        if total < 1e-9:
            continue
        n = max(1, int(total / (dash * 2.0)))
        step = (b - a) / (n * 2.0)
        p = a.copy()
        for _ in range(n):
            out.append((p.copy(), p + step))
            p = p + step * 2.0
    return out


def _point_segment_distance(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    if len2 < 1e-9:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def nearest_handle(mouse, projected: dict, threshold: float = PICK_PX):
    """Nearest projected handle within `threshold` pixels, or None."""
    best = None
    best_dist = threshold
    for key, segments in projected.items():
        for (ax, ay), (bx, by) in segments:
            dist = _point_segment_distance(mouse[0], mouse[1], ax, ay, bx, by)
            if dist < best_dist:
                best, best_dist = key, dist
    return best


def project_handles(data: GizmoInfo, region, rv3d) -> dict:
    """Projected 2D segments per handle; handles behind the camera drop out."""
    out = {}
    for key, segments in handles(data.center, data.axes, data.half,
                                 data.length, data.radii).items():
        projected = []
        for a, b in segments:
            pa = view3d_utils.location_3d_to_region_2d(region, rv3d, a)
            pb = view3d_utils.location_3d_to_region_2d(region, rv3d, b)
            if pa is None or pb is None:
                continue
            projected.append(((pa[0], pa[1]), (pb[0], pb[1])))
        if projected:
            out[key] = projected
    return out


def pick(context, mouse_xy) -> tuple[str, int] | None:
    """Handle ('move'|'rotate', axis) under the cursor, or None."""
    data = info(context)
    if data is None:
        return None
    region = context.region
    rv3d = context.region_data
    return nearest_handle(mouse_xy, project_handles(data, region, rv3d))


def _draw() -> None:
    try:
        _draw_impl()
    except Exception:
        draw._report_draw_error_once()


def _draw_impl() -> None:
    context = bpy.context
    if not tool_active(context):
        return
    data = info(context)
    if data is None:
        return
    shader = draw._uniform_color_shader()
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    box_pts = []
    for a, b in bounds_segments(data):
        box_pts.append(tuple(a))
        box_pts.append(tuple(b))
    if box_pts:
        box_batch = batch_for_shader(shader, 'LINES', {"pos": box_pts})
        gpu.state.line_width_set(1.5)
        shader.bind()
        shader.uniform_float("color", (1.0, 1.0, 1.0, 0.35))
        box_batch.draw(shader)
    width = THICK_PX / data.px_per_unit  # constant pixels -> world
    items = list(handle_tris(data.center, data.axes, data.half, data.length,
                             data.radii, width).items())
    items.sort(key=lambda item: item[0] == _active)  # active handle on top
    for key, tris in items:
        r, g, b = AXIS_COLORS[key[1]]
        pts = []
        for a, b2, c in tris:
            pts.extend((tuple(a), tuple(b2), tuple(c)))
        batch = batch_for_shader(shader, 'TRIS', {"pos": pts})
        shader.bind()
        shader.uniform_float(
            "color", (r, g, b, ACTIVE_ALPHA if key == _active else IDLE_ALPHA))
        batch.draw(shader)
    gpu.state.blend_set('NONE')


def register() -> None:
    global _handler, _active
    _active = None
    if _handler is None:
        _handler = bpy.types.SpaceView3D.draw_handler_add(
            _draw, (), 'WINDOW', 'POST_VIEW')


def unregister() -> None:
    global _handler, _active
    _active = None
    if _handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handler, 'WINDOW')
        _handler = None
