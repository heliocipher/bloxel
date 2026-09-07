"""Compressed serialization of a VoxelGrid into a text-safe blob.

The blob is stored in an ID property on the Blender object so that native
undo/redo and .blend saving capture the voxel data automatically.
"""
from __future__ import annotations

import base64
import struct
import zlib

import numpy as np

from .grid import CHUNK, VoxelGrid

MAGIC = b"BLOX01"
_CHUNK_BYTES = CHUNK * CHUNK * CHUNK * 2
_COMPRESS_LEVEL = 6


def dumps(grid: VoxelGrid, selection=()) -> str:
    parts = [MAGIC]
    items = sorted(grid.chunks.items())
    parts.append(struct.pack("<I", len(items)))
    for (cx, cy, cz), arr in items:
        parts.append(struct.pack("<3i", cx, cy, cz))
        parts.append(np.ascontiguousarray(arr, dtype="<u2").tobytes())
    parts.append(struct.pack("<I", len(selection)))
    for x, y, z in sorted(selection):
        parts.append(struct.pack("<3i", x, y, z))
    blob = zlib.compress(b"".join(parts), _COMPRESS_LEVEL)
    return base64.b85encode(blob).decode("ascii")


def loads(text: str) -> tuple[VoxelGrid, set]:
    raw = zlib.decompress(base64.b85decode(text.encode("ascii")))
    if raw[: len(MAGIC)] != MAGIC:
        raise ValueError("not a Bloxel blob")
    mv = memoryview(raw)
    off = len(MAGIC)

    def take(n: int) -> memoryview:
        nonlocal off
        buf = mv[off:off + n]
        off += n
        return buf

    grid = VoxelGrid()
    (nchunks,) = struct.unpack("<I", take(4))
    for _ in range(nchunks):
        cx, cy, cz = struct.unpack("<3i", take(12))
        arr = np.frombuffer(take(_CHUNK_BYTES), dtype="<u2").reshape(CHUNK, CHUNK, CHUNK).copy()
        grid.chunks[(cx, cy, cz)] = arr
    (nsel,) = struct.unpack("<I", take(4))
    selection = set()
    for _ in range(nsel):
        selection.add(struct.unpack("<3i", take(12)))
    return grid, selection
