"""Chunked sparse voxel grid plus grid-space queries (raycast, rasterization).

The grid is sparse: space is divided into CHUNK^3 blocks that are only
allocated when they contain a non-empty cell. This keeps memory proportional
to the occupied volume, so the working volume itself can be arbitrarily large.

Cell values are uint16 palette indices; 0 means empty.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Iterable, Iterator, NamedTuple

import numpy as np

CHUNK = 32
CHUNK_SHIFT = 5
CHUNK_MASK = CHUNK - 1
EMPTY = 0

Vec3 = tuple[int, int, int]


class VoxelGrid:
    """Sparse grid of CHUNK^3 uint16 blocks."""

    __slots__ = ("chunks", "invalid")

    def __init__(self) -> None:
        self.chunks: dict[Vec3, np.ndarray] = {}
        # chunks whose display geometry needs rebuilding (includes border
        # neighbours, because their exposed faces change too)
        self.invalid: set[Vec3] = set()

    # ------------------------------------------------------------------ cells
    def get(self, x: int, y: int, z: int) -> int:
        chunk = self.chunks.get((x >> CHUNK_SHIFT, y >> CHUNK_SHIFT, z >> CHUNK_SHIFT))
        if chunk is None:
            return EMPTY
        return int(chunk[x & CHUNK_MASK, y & CHUNK_MASK, z & CHUNK_MASK])

    def set(self, x: int, y: int, z: int, mat: int) -> bool:
        """Set a cell. Returns True when the cell actually changed."""
        key = (x >> CHUNK_SHIFT, y >> CHUNK_SHIFT, z >> CHUNK_SHIFT)
        lx, ly, lz = x & CHUNK_MASK, y & CHUNK_MASK, z & CHUNK_MASK
        chunk = self.chunks.get(key)
        if mat == EMPTY:
            if chunk is None or chunk[lx, ly, lz] == EMPTY:
                return False
            chunk[lx, ly, lz] = EMPTY
            self._invalidate(key, lx, ly, lz)
            if not chunk.any():
                del self.chunks[key]
            return True
        if chunk is None:
            chunk = np.zeros((CHUNK, CHUNK, CHUNK), dtype=np.uint16)
            self.chunks[key] = chunk
        if chunk[lx, ly, lz] == mat:
            return False
        chunk[lx, ly, lz] = mat
        self._invalidate(key, lx, ly, lz)
        return True

    def _invalidate(self, key: Vec3, lx: int, ly: int, lz: int) -> None:
        self.invalid.add(key)
        cx, cy, cz = key
        if lx == 0:
            self.invalid.add((cx - 1, cy, cz))
        if lx == CHUNK_MASK:
            self.invalid.add((cx + 1, cy, cz))
        if ly == 0:
            self.invalid.add((cx, cy - 1, cz))
        if ly == CHUNK_MASK:
            self.invalid.add((cx, cy + 1, cz))
        if lz == 0:
            self.invalid.add((cx, cy, cz - 1))
        if lz == CHUNK_MASK:
            self.invalid.add((cx, cy, cz + 1))

    def set_cells(self, cells: Iterable[Vec3], mat: int) -> int:
        changed = 0
        for x, y, z in cells:
            if self.set(x, y, z, mat):
                changed += 1
        return changed

    def voxel_count(self) -> int:
        return sum(int(np.count_nonzero(c)) for c in self.chunks.values())

    def occupied_bounds(self) -> tuple[Vec3, Vec3] | None:
        """Min/max (inclusive) of occupied cells, or None when empty."""
        if not self.chunks:
            return None
        mn = [math.inf, math.inf, math.inf]
        mx = [-math.inf, -math.inf, -math.inf]
        for (cx, cy, cz), arr in self.chunks.items():
            nz = np.nonzero(arr)
            if nz[0].size == 0:
                continue
            base = (cx * CHUNK, cy * CHUNK, cz * CHUNK)
            for axis, idx in enumerate(nz):
                mn[axis] = min(mn[axis], base[axis] + int(idx.min()))
                mx[axis] = max(mx[axis], base[axis] + int(idx.max()))
        if math.isinf(mn[0]):
            return None
        return (int(mn[0]), int(mn[1]), int(mn[2])), (int(mx[0]), int(mx[1]), int(mx[2]))


# ---------------------------------------------------------------------------
# raster helpers

def plane_axes(normal: Vec3) -> tuple[Vec3, Vec3]:
    """Two unit vectors spanning the plane perpendicular to `normal`."""
    nx, ny, nz = normal
    if nx != 0:
        return (0, 1, 0), (0, 0, 1)
    if ny != 0:
        return (0, 0, 1), (1, 0, 0)
    return (1, 0, 0), (0, 1, 0)


@lru_cache(maxsize=None)
def footprint_offsets(shape: str, size: int) -> tuple[tuple[int, int], ...]:
    """(du, dv) cross-section offsets of the brush footprint.

    `size` is the footprint side length in voxels: 1 -> single cell,
    2 -> 2x2, 3 -> 3x3, ... Even sizes anchor with the base cell in the
    +du/+dv quadrant (offsets run -(N//2) .. N-1-(N//2)).
    Cached: brush strokes recompute it for every stamp along the drag path.
    """
    n = max(1, int(size))
    lo = -(n // 2)
    hi = lo + n - 1
    out: list[tuple[int, int]] = []
    if shape == 'CIRCLE':
        rr = (n / 2.0) ** 2
        if n % 2:  # odd: centered on the base cell
            for du in range(lo, hi + 1):
                for dv in range(lo, hi + 1):
                    if du * du + dv * dv <= rr:
                        out.append((du, dv))
        else:  # even: centered on the corner between the 4 middle cells
            for du in range(lo, hi + 1):
                for dv in range(lo, hi + 1):
                    if (du + 0.5) ** 2 + (dv + 0.5) ** 2 <= rr:
                        out.append((du, dv))
    else:  # SQUARE
        for du in range(lo, hi + 1):
            for dv in range(lo, hi + 1):
                out.append((du, dv))
    return tuple(out)


def stamp_cells(base: Vec3, normal: Vec3, shape: str, size: int) -> list[Vec3]:
    """Cells covered by one brush stamp anchored at `base`."""
    u, v = plane_axes(normal)
    return [
        (base[0] + du * u[0] + dv * v[0],
         base[1] + du * u[1] + dv * v[1],
         base[2] + du * u[2] + dv * v[2])
        for du, dv in footprint_offsets(shape, size)
    ]


def in_bounds(cell: Vec3, bmin: Vec3, bmax: Vec3) -> bool:
    return (bmin[0] <= cell[0] <= bmax[0]
            and bmin[1] <= cell[1] <= bmax[1]
            and bmin[2] <= cell[2] <= bmax[2])


def apply_brush(grid: VoxelGrid, base: Vec3, normal: Vec3, shape: str, size: int,
                mode: str, mat: int, bmin: Vec3, bmax: Vec3,
                record: dict | None = None) -> int:
    """Apply one brush stamp. Returns the number of changed cells.

    mode: 'ADD' (set regardless), 'PAINT' (only occupied cells), 'ERASE'.
    ADD/PAINT with mat == EMPTY are refused: writing the empty value would
    erase voxels instead of painting them. record: optional dict collecting
    {cell: pre-stamp value} - used to build the stroke mask (see
    StrokeMaskGrid).
    """
    if mat == EMPTY and mode != 'ERASE':
        return 0
    changed = 0
    for cell in stamp_cells(base, normal, shape, size):
        if not in_bounds(cell, bmin, bmax):
            continue
        if record is not None and cell not in record:
            record[cell] = grid.get(*cell)
        if mode == 'PAINT':
            if grid.get(*cell) == EMPTY:
                continue
            if grid.set(*cell, mat):
                changed += 1
        elif mode == 'ERASE':
            if grid.set(*cell, EMPTY):
                changed += 1
        else:  # ADD
            if grid.set(*cell, mat):
                changed += 1
    return changed


class StrokeMaskGrid:
    """Read-only view of a grid masked by a stroke's pre-edit values.

    Picking through this view sees the grid as it was when the stroke
    started: a drag cannot stack voxels onto ones placed moments earlier
    (column stacking) nor tunnel through ones just erased. New voxels only
    appear when the cursor reaches a new cell of the original surface.
    """

    __slots__ = ("grid", "overlay")

    def __init__(self, grid: VoxelGrid, overlay: dict) -> None:
        self.grid = grid
        self.overlay = overlay  # {cell: value at stroke start}

    def get(self, x: int, y: int, z: int) -> int:
        key = (x, y, z)
        if key in self.overlay:
            return self.overlay[key]
        return self.grid.get(x, y, z)

    @property
    def chunks(self):
        # superset for DDA chunk-skipping: stroke-created chunks are marched
        # cell by cell (their masked cells read empty), which stays correct
        return self.grid.chunks


def mirror_variants(cell: Vec3, normal: Vec3, mirrors, bmin: Vec3, bmax: Vec3):
    """All (cell, normal) variants under the active mirror axes.

    mirrors: (mx, my, mz) booleans. Mirroring is across the working volume
    centre per axis. Normals flip sign on mirrored axes so footprints stay
    correctly oriented.
    """
    variants = [(cell, normal)]
    for axis in range(3):
        if not mirrors[axis]:
            continue
        lo, hi = bmin[axis], bmax[axis]
        mirrored = []
        for c, n in variants:
            mc = list(c)
            mc[axis] = lo + hi - c[axis]
            mn = list(n)
            mn[axis] = -n[axis]
            if mc[axis] != c[axis]:
                mirrored.append((tuple(mc), tuple(mn)))
        variants += mirrored
    return variants


def flood_fill(grid: VoxelGrid, start: Vec3, mat: int, bmin: Vec3, bmax: Vec3,
               contiguous: bool = True) -> int:
    """Replace voxels with `mat`. Returns the number of changed cells.

    contiguous=True: 6-connected region of same-material voxels around start.
    contiguous=False: every voxel with the start voxel's material.
    Empty start cells do nothing, and so does mat == EMPTY (filling with the
    empty value would delete the region).
    """
    if mat == EMPTY:
        return 0
    target = grid.get(*start)
    if target == EMPTY or target == mat:
        return 0
    if not contiguous:
        changed = 0
        for key, chunk in grid.chunks.items():
            mask = chunk == target
            if mask.any():
                chunk[mask] = mat
                # material change only affects this chunk's own faces
                grid.invalid.add(key)
                changed += int(mask.sum())
        return changed
    changed = 0
    stack = [start]
    seen = {start}
    while stack:
        cell = stack.pop()
        if grid.get(*cell) != target:
            continue
        grid.set(*cell, mat)
        changed += 1
        for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
            n = (cell[0] + d[0], cell[1] + d[1], cell[2] + d[2])
            if n not in seen and in_bounds(n, bmin, bmax):
                seen.add(n)
                stack.append(n)
    return changed


# ---------------------------------------------------------------------------
# ray casting (sparse DDA with empty-chunk skipping)

_EPS = 1e-6
# direction components below this are treated as zero, otherwise a ray
# parallel to an axis plane would never cross a cell boundary
_MIN_DIR = 1e-12
# march step limit (guard: should never trigger)
_MAX_STEPS = 2_000_000


class RayHit(NamedTuple):
    cell: Vec3
    normal: Vec3  # outward normal of the face the ray entered through
    distance: float


class RayResult(NamedTuple):
    hit: RayHit | None
    entry_cell: Vec3 | None    # cell where the ray enters the working volume
    entry_normal: Vec3 | None  # face normal at volume entry


_MISS = RayResult(None, None, None)


def raycast(grid: VoxelGrid, origin, direction, bmin: Vec3, bmax: Vec3) -> RayResult:
    """March a ray through the working volume [bmin, bmax] (inclusive cells).

    Returns the first occupied cell hit, and/or the volume entry cell (used to
    place voxels into empty space). `direction` need not be normalized.
    """
    o = [float(origin[i]) for i in range(3)]
    d = [float(direction[i]) for i in range(3)]
    lo = [float(bmin[i]) for i in range(3)]
    hi = [float(bmax[i]) + 1.0 for i in range(3)]

    # slab test against the working volume box
    tmin, tmax = -math.inf, math.inf
    entry_axis = 0
    exit_axis = 0
    for i in range(3):
        if abs(d[i]) < 1e-12:
            if o[i] < lo[i] or o[i] >= hi[i]:
                return _MISS
        else:
            inv = 1.0 / d[i]
            t1 = (lo[i] - o[i]) * inv
            t2 = (hi[i] - o[i]) * inv
            if t1 > t2:
                t1, t2 = t2, t1
            if t1 > tmin:
                tmin, entry_axis = t1, i
            if t2 < tmax:
                tmax, exit_axis = t2, i
            if tmin > tmax:
                return _MISS
    if tmax < 0.0:
        return _MISS

    step = [1 if d[i] > 0 else -1 for i in range(3)]
    t_start = max(tmin, 0.0)
    origin_inside = tmin <= 0.0

    def pos_at(t: float) -> list[float]:
        return [o[i] + d[i] * t for i in range(3)]

    # placement cell for empty-space clicks: where the ray enters the volume
    # (camera outside) or where it exits (camera inside) - always a cell
    # whose face the camera is looking at
    if origin_inside:
        ep = pos_at(max(tmax - _EPS, 0.0))
        entry_normal = [0, 0, 0]
        entry_normal[exit_axis] = -step[exit_axis]
    else:
        ep = pos_at(t_start + _EPS)
        entry_normal = [0, 0, 0]
        entry_normal[entry_axis] = -step[entry_axis]
    entry_cell = tuple(min(max(math.floor(ep[i]), bmin[i]), bmax[i]) for i in range(3))
    entry_normal = tuple(entry_normal)

    pos = pos_at(t_start + _EPS)
    cell = [min(max(math.floor(pos[i]), bmin[i]), bmax[i]) for i in range(3)]
    t_cur = t_start + _EPS
    normal = [0, 0, 0]
    if t_start > 0.0:
        normal[entry_axis] = -step[entry_axis]
    else:
        dom = max(range(3), key=lambda i: abs(d[i]))
        normal[dom] = -step[dom]

    def inside() -> bool:
        return (bmin[0] <= cell[0] <= bmax[0]
                and bmin[1] <= cell[1] <= bmax[1]
                and bmin[2] <= cell[2] <= bmax[2])

    iterations = 0
    while t_cur <= tmax and inside():
        iterations += 1
        if iterations > _MAX_STEPS:  # guard: should never trigger
            break
        if grid.get(cell[0], cell[1], cell[2]) != EMPTY:
            return RayResult(RayHit(tuple(cell), tuple(normal), t_cur),
                             entry_cell, entry_normal)
        ckey = (cell[0] >> CHUNK_SHIFT, cell[1] >> CHUNK_SHIFT, cell[2] >> CHUNK_SHIFT)
        if ckey not in grid.chunks:
            # current chunk is entirely empty: jump straight to its exit face
            t_jump = math.inf
            jump_axis = -1
            for i in range(3):
                if abs(d[i]) < _MIN_DIR:
                    continue
                boundary = (ckey[i] + 1) * CHUNK if step[i] > 0 else ckey[i] * CHUNK
                tj = t_cur + (boundary - pos[i]) / d[i]
                if tj < t_jump:
                    t_jump, jump_axis = tj, i
            if t_jump > tmax:
                break
            t_cur = t_jump + _EPS
            pos = pos_at(t_cur)
            cell = [math.floor(pos[i]) for i in range(3)]
            normal = [0, 0, 0]
            if jump_axis >= 0:
                normal[jump_axis] = -step[jump_axis]
        else:
            # step to the next cell boundary within this chunk
            t_next = math.inf
            axis = -1
            for i in range(3):
                if abs(d[i]) < _MIN_DIR:
                    continue
                boundary = cell[i] + 1 if step[i] > 0 else cell[i]
                ti = t_cur + (boundary - pos[i]) / d[i]
                if ti < t_next:
                    t_next, axis = ti, i
            if axis < 0 or t_next > tmax:
                break
            t_cur = t_next + _EPS
            pos = pos_at(t_cur)
            cell = [math.floor(pos[i]) for i in range(3)]
            normal = [0, 0, 0]
            normal[axis] = -step[axis]

    return RayResult(None, entry_cell, entry_normal)


def walk_line(a: Vec3, b: Vec3) -> Iterator[Vec3]:
    """Integer DDA from cell a to cell b (both inclusive)."""
    if a == b:
        yield a
        return
    pa = (a[0] + 0.5, a[1] + 0.5, a[2] + 0.5)
    d = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    step = [1 if d[i] > 0 else -1 for i in range(3)]
    t_max = [math.inf, math.inf, math.inf]
    t_delta = [math.inf, math.inf, math.inf]
    cell = [a[0], a[1], a[2]]
    for i in range(3):
        if d[i] == 0:
            continue
        boundary = cell[i] + 1 if step[i] > 0 else cell[i]
        t_max[i] = (boundary - pa[i]) / d[i]
        t_delta[i] = abs(1.0 / d[i])
    yield tuple(cell)
    while True:
        axis = min(range(3), key=lambda i: t_max[i])
        if t_max[axis] > 1.0:
            break
        cell[axis] += step[axis]
        t_max[axis] += t_delta[axis]
        yield tuple(cell)


# ---------------------------------------------------------------------------
# extrusion

def face_region(grid: VoxelGrid, cell: Vec3, normal: Vec3,
                bmin: Vec3, bmax: Vec3) -> set:
    """The connected, coplanar, same-material face region around `cell`.

    Contains every voxel 6-connected to `cell` that shares its material and
    exposes a face in the `normal` direction. Non-coplanar voxels block
    connectivity (a step in the surface stops the region).
    """
    mat = grid.get(*cell)
    if mat == EMPTY:
        return set()
    region: set = set()
    stack = [cell]
    seen = {cell}
    while stack:
        c = stack.pop()
        region.add(c)
        for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
            nb = (c[0] + d[0], c[1] + d[1], c[2] + d[2])
            if nb in seen or not in_bounds(nb, bmin, bmax):
                continue
            seen.add(nb)
            if grid.get(*nb) != mat:
                continue
            fwd = (nb[0] + normal[0], nb[1] + normal[1], nb[2] + normal[2])
            exposed = (not in_bounds(fwd, bmin, bmax)) or grid.get(*fwd) == EMPTY
            if exposed:
                stack.append(nb)
    return region


def extrude_region(grid: VoxelGrid, region, normal: Vec3, layers: int,
                   mat: int, bmin: Vec3, bmax: Vec3,
                   record: set | None = None) -> int:
    """Stack `layers` voxels outward from each region cell along `normal`.

    Only cells adjacent to the current front are created, one layer at a
    time. Occupied destinations are left alone; running out of the volume
    stops that column. Returns the number of changed cells. `record`, when
    given, collects the cells actually created (stroke ownership tracking).
    """
    changed = 0
    for cx, cy, cz in region:
        for k in range(1, layers + 1):
            x = cx + normal[0] * k
            y = cy + normal[1] * k
            z = cz + normal[2] * k
            if not in_bounds((x, y, z), bmin, bmax):
                break
            if grid.get(x, y, z) == EMPTY and grid.set(x, y, z, mat):
                changed += 1
                if record is not None:
                    record.add((x, y, z))
    return changed


def extrude_layers(grid: VoxelGrid, region, normal: Vec3, current: int,
                   target: int, mat: int, bmin: Vec3, bmax: Vec3,
                   added: set, deleted: dict) -> int:
    """Adjust a stroke's extrusion height from `current` to `target` layers.

    target >= 1: layers 1..target exist outward from the face (stroke-created
    cells tracked in `added`). target < 0: additionally the surface voxels
    and |target|-1 deeper cells along -normal are deleted; their previous
    values are recorded in `deleted`, so dragging forward restores them
    exactly. `current`/`target` may move in either direction repeatedly.
    Returns the number of changed cells.
    """
    changed = 0
    nx, ny, nz = normal
    if target > current:
        for k in range(current + 1, target + 1):
            if k >= 1:  # create outward layers
                for cx, cy, cz in region:
                    x, y, z = cx + nx * k, cy + ny * k, cz + nz * k
                    if not in_bounds((x, y, z), bmin, bmax):
                        continue
                    if grid.get(x, y, z) == EMPTY and grid.set(x, y, z, mat):
                        added.add((x, y, z))
                        changed += 1
            else:  # k <= 0: restore a previously deleted original voxel
                for cx, cy, cz in region:
                    cell = (cx + nx * k, cy + ny * k, cz + nz * k)
                    old = deleted.pop(cell, None)
                    if old is not None and grid.set(*cell, old):
                        changed += 1
    else:  # target < current
        for k in range(target + 1, current + 1):
            for cx, cy, cz in region:
                cell = (cx + nx * k, cy + ny * k, cz + nz * k)
                if k >= 1:  # remove stroke-created layers only
                    if cell in added and grid.set(*cell, EMPTY):
                        added.discard(cell)
                        changed += 1
                else:  # k <= 0: delete the original voxel (recorded)
                    if not in_bounds(cell, bmin, bmax):
                        continue
                    value = grid.get(*cell)
                    if value != EMPTY and grid.set(*cell, EMPTY):
                        deleted[cell] = value
                        changed += 1
    return changed
