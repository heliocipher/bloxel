"""Runtime state: the live (deserialized) grid per Bloxel object.

Voxel data persists as a compressed blob in an ID property on the object,
so Blender's native undo/redo and .blend saving capture it. The runtime
cache is keyed by object name and validated against a revision counter;
undo/redo/load handlers clear the cache so the next access re-deserializes
from the (restored) ID property.
"""
from __future__ import annotations

import bpy

from . import serialize
from .grid import VoxelGrid
from .mesher import Mesher

FLAG_PROP = "bloxel"        # True on Bloxel objects
GRID_PROP = "bloxel_data"   # compressed voxel blob
REV_PROP = "bloxel_rev"     # incremented on every commit

_EMPTY_BLOB = serialize.dumps(VoxelGrid())


class Runtime:
    __slots__ = ("rev", "grid", "mesher", "selection")

    def __init__(self, rev: int, grid: VoxelGrid, selection: set) -> None:
        self.rev = rev
        self.grid = grid
        self.mesher = Mesher()
        self.selection = selection


_runtimes: dict[str, Runtime] = {}


def clear_runtimes() -> None:
    _runtimes.clear()


def is_bloxel(obj) -> bool:
    return bool(obj) and obj.type == 'MESH' and bool(obj.get(FLAG_PROP))


def runtime(obj) -> Runtime:
    """Live grid/mesher for an object, lazily deserialized after undo/load."""
    rev = obj.get(REV_PROP, 0)
    rt = _runtimes.get(obj.name)
    if rt is None or rt.rev != rev:
        blob = obj.get(GRID_PROP, _EMPTY_BLOB)
        grid, selection = serialize.loads(blob)
        rt = Runtime(rev, grid, selection)
        _runtimes[obj.name] = rt
    return rt


def commit(obj, rt: Runtime | None = None) -> None:
    """Persist the runtime state into ID properties (undo snapshot point)."""
    rt = rt or runtime(obj)
    if rt.selection:
        # selection always refers to live voxels: edits that empty a selected
        # cell (eraser, extrude delete) drop it from the selection here
        rt.selection = {cell for cell in rt.selection if rt.grid.get(*cell) != 0}
    obj[GRID_PROP] = serialize.dumps(rt.grid, rt.selection)
    rev = obj.get(REV_PROP, 0) + 1
    obj[REV_PROP] = rev
    rt.rev = rev


def init_object(obj) -> None:
    """Tag a fresh object as a Bloxel model with an empty grid."""
    obj[FLAG_PROP] = True
    obj[GRID_PROP] = _EMPTY_BLOB
    obj[REV_PROP] = 1


# ---------------------------------------------------------------------------
# RNA properties (native undo + file save cover these automatically)

def register_properties() -> None:
    bpy.types.Object.bloxel_min = bpy.props.IntVectorProperty(
        name="Volume Min", size=3, default=(0, 0, 0),
        description="First editable cell of the working volume")
    bpy.types.Object.bloxel_max = bpy.props.IntVectorProperty(
        name="Volume Max", size=3, default=(31, 31, 31),
        description="Last editable cell of the working volume (inclusive)")
    bpy.types.Object.bloxel_palette_index = bpy.props.IntProperty(
        name="Active Palette Slot", default=0, min=0)


def unregister_properties() -> None:
    del bpy.types.Object.bloxel_min
    del bpy.types.Object.bloxel_max
    del bpy.types.Object.bloxel_palette_index


def get_bounds(obj) -> tuple[tuple, tuple]:
    """Working volume bounds, normalized per axis (min <= max always).

    The panel allows entering min > max; every consumer (raycast, overlay
    grid, brush rasterization) assumes a valid range, so swap here instead
    of guarding in each of them.
    """
    mn, mx = tuple(obj.bloxel_min), tuple(obj.bloxel_max)
    return tuple(min(a, b) for a, b in zip(mn, mx)), tuple(max(a, b) for a, b in zip(mn, mx))


def history_changed(*_args) -> None:
    """Called on undo/redo/load: drop caches so grids re-deserialize."""
    clear_runtimes()
