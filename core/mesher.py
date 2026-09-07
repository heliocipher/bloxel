"""Turns the sparse voxel grid into a single display mesh.

Strategy: per-chunk culled meshing (numpy-vectorized) with a geometry cache.
Only chunks touched by an edit are re-meshed; the final mesh is the
concatenation of all chunk caches, written via mesh.from_pydata.

A face is emitted only where the neighbouring cell is empty, so interior
faces never exist. Per-face material index = palette index of the voxel
(slot index = palette index - 1).
"""
from __future__ import annotations

import numpy as np

from .grid import CHUNK, VoxelGrid

# (normal, corner offsets) per direction; corners wound CCW seen from outside
FACES = [
    ((1, 0, 0), [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)]),
    ((-1, 0, 0), [(0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)]),
    ((0, 1, 0), [(0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)]),
    ((0, -1, 0), [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]),
    ((0, 0, 1), [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]),
    ((0, 0, -1), [(0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)]),
]

FACE_BY_NORMAL = {n: c for n, c in FACES}

_EMPTY_VERTS = np.zeros((0, 3), dtype=np.float32)
_EMPTY_QUADS = np.zeros((0, 4), dtype=np.int32)
_EMPTY_MATS = np.zeros((0,), dtype=np.int32)


def _halo(grid: VoxelGrid, ckey) -> np.ndarray:
    """(CHUNK+2)^3 occupancy+material view: the chunk plus a 1-cell border
    filled from neighbouring chunks (needed for correct culling at edges)."""
    halo = np.zeros((CHUNK + 2, CHUNK + 2, CHUNK + 2), dtype=np.uint16)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                arr = grid.chunks.get((ckey[0] + dx, ckey[1] + dy, ckey[2] + dz))
                if arr is None:
                    continue
                src, dst = [], []
                for axis, dd in enumerate((dx, dy, dz)):
                    n0 = (ckey[axis] + dd) * CHUNK      # neighbour world start
                    h0 = ckey[axis] * CHUNK - 1         # halo world start
                    lo = max(n0, h0)
                    hi = min(n0 + CHUNK, h0 + CHUNK + 2)
                    src.append(slice(lo - n0, hi - n0))
                    dst.append(slice(lo - h0, hi - h0))
                halo[dst[0], dst[1], dst[2]] = arr[src[0], src[1], src[2]]
    return halo


def mesh_chunk(grid: VoxelGrid, ckey):
    """(verts (N,3) f32, quads (M,4) i32, mats (M,) u16) for one chunk."""
    chunk = grid.chunks.get(ckey)
    if chunk is None:
        return _EMPTY_VERTS, _EMPTY_QUADS, _EMPTY_MATS
    halo = _halo(grid, ckey)
    occ = halo != 0
    center = occ[1:-1, 1:-1, 1:-1]
    base = np.array([ckey[0] * CHUNK, ckey[1] * CHUNK, ckey[2] * CHUNK])

    vert_parts, quad_parts, mat_parts = [], [], []
    vert_offset = 0
    for (dx, dy, dz), corners in FACES:
        if dx == 1:
            exposed = center & ~occ[2:, 1:-1, 1:-1]
        elif dx == -1:
            exposed = center & ~occ[:-2, 1:-1, 1:-1]
        elif dy == 1:
            exposed = center & ~occ[1:-1, 2:, 1:-1]
        elif dy == -1:
            exposed = center & ~occ[1:-1, :-2, 1:-1]
        elif dz == 1:
            exposed = center & ~occ[1:-1, 1:-1, 2:]
        else:
            exposed = center & ~occ[1:-1, 1:-1, :-2]
        idx = np.nonzero(exposed)
        n = idx[0].shape[0]
        if n == 0:
            continue
        cells = np.stack(idx, axis=1) + base                    # (n,3) world cell
        cm = np.asarray(corners, dtype=np.int32)                # (4,3)
        verts = (cells[:, None, :] + cm[None, :, :]).reshape(-1, 3)
        quads = (np.arange(n * 4, dtype=np.int32).reshape(-1, 4) + vert_offset)
        mats = chunk[idx]                                       # palette index
        vert_parts.append(verts.astype(np.float32))
        quad_parts.append(quads)
        mat_parts.append(mats)
        vert_offset += n * 4

    if not vert_parts:
        return _EMPTY_VERTS, _EMPTY_QUADS, _EMPTY_MATS
    return (np.concatenate(vert_parts),
            np.concatenate(quad_parts),
            np.concatenate(mat_parts))


class Mesher:
    """Per-chunk geometry cache with incremental updates."""

    def __init__(self) -> None:
        self.cache: dict[tuple, tuple] = {}

    def sync(self, grid: VoxelGrid) -> None:
        for key in grid.invalid:
            if key in grid.chunks:
                self.cache[key] = mesh_chunk(grid, key)
            else:
                self.cache.pop(key, None)
        grid.invalid.clear()
        for key in list(self.cache):
            if key not in grid.chunks:
                del self.cache[key]
        for key in grid.chunks:  # fresh load: compute anything missing
            if key not in self.cache:
                self.cache[key] = mesh_chunk(grid, key)

    def build(self, grid: VoxelGrid):
        self.sync(grid)
        vert_parts, quad_parts, mat_parts = [], [], []
        vert_offset = 0
        for key in sorted(self.cache):
            verts, quads, mats = self.cache[key]
            if quads.shape[0] == 0:
                continue
            vert_parts.append(verts)
            quad_parts.append(quads + vert_offset)
            mat_parts.append(mats)
            vert_offset += verts.shape[0]
        if not vert_parts:
            return _EMPTY_VERTS, _EMPTY_QUADS, _EMPTY_MATS
        return (np.concatenate(vert_parts),
                np.concatenate(quad_parts),
                np.concatenate(mat_parts))


def rebuild_mesh(obj, runtime) -> None:
    """Rebuild the object's mesh datablock from the current grid state."""
    mesh = obj.data
    verts, quads, mats = runtime.mesher.build(runtime.grid)
    mesh.clear_geometry()
    if quads.shape[0]:
        mesh.from_pydata(verts, [], quads)
        slot_count = max(len(mesh.materials), 1)
        # palette index (1-based) -> material slot index (0-based)
        indices = np.clip(mats.astype(np.int32) - 1, 0, slot_count - 1)
        mesh.polygons.foreach_set("material_index", indices)
    mesh.update()
