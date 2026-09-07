"""Per-model palette: real Blender materials held in the mesh's material slots.

Palette index (what voxels store, 1-based) = material slot index + 1.
Materials are unique per model so each model owns its palette.
"""
from __future__ import annotations

import bpy

DEFAULT_COLORS = [
    (1.00, 1.00, 1.00, 1.0),   # white
    (0.55, 0.55, 0.55, 1.0),   # gray
    (0.15, 0.15, 0.15, 1.0),   # dark
    (0.85, 0.20, 0.20, 1.0),   # red
    (0.25, 0.75, 0.25, 1.0),   # green
    (0.20, 0.40, 0.95, 1.0),   # blue
    (0.95, 0.80, 0.15, 1.0),   # yellow
    (0.50, 0.30, 0.12, 1.0),   # brown
]


def _new_material(name: str, rgba) -> bpy.types.Material:
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.diffuse_color = rgba
    mat["bloxel_palette"] = True
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = rgba
    return mat


def create_palette(obj, colors=DEFAULT_COLORS) -> None:
    for i, rgba in enumerate(colors, start=1):
        obj.data.materials.append(_new_material(f"{obj.name}.{i:03d}", rgba))


def add_material(obj) -> int:
    """Append a material slot; returns its 1-based palette index."""
    idx = len(obj.data.materials) + 1
    rgba = DEFAULT_COLORS[(idx - 1) % len(DEFAULT_COLORS)]
    obj.data.materials.append(_new_material(f"{obj.name}.{idx:03d}", rgba))
    return idx


def active_index(obj) -> int:
    """1-based palette index the tools paint with (0 when palette empty)."""
    count = len(obj.data.materials)
    if count == 0:
        return 0
    return min(obj.bloxel_palette_index, count - 1) + 1


def bsdf(mat):
    """The material's Principled BSDF node, or None (missing/custom tree)."""
    if not mat.use_nodes or mat.node_tree is None:
        return None
    return mat.node_tree.nodes.get("Principled BSDF")


# ---------------------------------------------------------------------------
# viewport color -> render color sync
#
# The palette UI edits Material.diffuse_color (solid viewport shading). Keep
# the Principled Base Color in sync so renders match. Materials are tagged
# with the "bloxel_palette" ID property so renames cannot break detection.

_MSGBUS_OWNER = object()


def _sync_principled_colors(*_args) -> None:
    for mat in bpy.data.materials:
        if not mat.get("bloxel_palette"):
            continue
        node = bsdf(mat)
        if node is not None:
            node.inputs["Base Color"].default_value = mat.diffuse_color


def register_msgbus() -> None:
    bpy.msgbus.subscribe_rna(
        key=(bpy.types.Material, "diffuse_color"),
        owner=_MSGBUS_OWNER,
        args=(),
        notify=_sync_principled_colors,
        options={'PERSISTENT'},
    )


def unregister_msgbus() -> None:
    bpy.msgbus.clear_by_owner(_MSGBUS_OWNER)
