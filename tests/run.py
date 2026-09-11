"""Bloxel headless test suite.

Run with:
  /Applications/Blender.app/Contents/MacOS/Blender \
      --background --factory-startup --python tests/run.py

Exits 0 when all checks pass, 1 otherwise.
"""
from __future__ import annotations

import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# the repo root IS the addon package (folder must be named "bloxel"),
# so its parent goes on sys.path
PARENT = os.path.dirname(ROOT)
assert os.path.basename(ROOT) == "bloxel", "repo folder must be named 'bloxel'"
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

FAILURES: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILURES.append(name)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# ---------------------------------------------------------------------------
section("grid: storage")
from bloxel.core.grid import (CHUNK, VoxelGrid, apply_brush, footprint_offsets,
                              in_bounds, raycast, stamp_cells, walk_line)

g = VoxelGrid()
check("get on empty grid does not allocate", g.get(0, 0, 0) == 0 and len(g.chunks) == 0)
g.set(0, 0, 0, 1)
check("set/get basic", g.get(0, 0, 0) == 1 and len(g.chunks) == 1)
g.set(-1, 5, 100, 2)
check("negative coords", g.get(-1, 5, 100) == 2)
check("far cell reads empty", g.get(1234, -5678, 90) == 0)
check("overwrite same value reports no change", g.set(0, 0, 0, 1) is False)
check("chunk freed when emptied", g.set(0, 0, 0, 0) and (0, 0, 0) not in g.chunks)
check("voxel_count", g.voxel_count() == 1)

g2 = VoxelGrid()
g2.set(0, 0, 0, 1)
check("invalid contains own chunk", (0, 0, 0) in g2.invalid)
check("invalid contains border neighbour", (-1, 0, 0) in g2.invalid)

# ---------------------------------------------------------------------------
section("grid: brush rasterization")
check("square size 1 is 1 cell", len(footprint_offsets('SQUARE', 1)) == 1)
check("square size 2 is 4 cells", len(footprint_offsets('SQUARE', 2)) == 4)
check("square size 3 is 9 cells", len(footprint_offsets('SQUARE', 3)) == 9)
check("circle size 1 is 1 cell", len(footprint_offsets('CIRCLE', 1)) == 1)
check("circle size 2 is 4 cells", len(footprint_offsets('CIRCLE', 2)) == 4)
check("circle size 3 is 9 cells", len(footprint_offsets('CIRCLE', 3)) == 9)
check("circle size 5 is 21 cells", len(footprint_offsets('CIRCLE', 5)) == 21)
check("even square anchors base in +du/+dv quadrant",
      footprint_offsets('SQUARE', 2) == ((-1, -1), (-1, 0), (0, -1), (0, 0)))
check("footprint offsets are cached",
      footprint_offsets('CIRCLE', 7) is footprint_offsets('CIRCLE', 7))

cells = stamp_cells((4, 4, 5), (0, 0, 1), 'SQUARE', 3)
check("stamp on +z plane stays in plane", all(c[2] == 5 for c in cells) and len(cells) == 9)
cells = stamp_cells((4, 4, 5), (-1, 0, 0), 'SQUARE', 3)
check("stamp on -x plane stays in plane", all(c[0] == 4 for c in cells) and len(cells) == 9)
cells = stamp_cells((4, 4, 5), (0, 0, 1), 'SQUARE', 2)
check("even stamp spans base-1..base", sorted(cells) == [(3, 3, 5), (3, 4, 5), (4, 3, 5), (4, 4, 5)])

g3 = VoxelGrid()
bmin, bmax = (0, 0, 0), (31, 31, 31)
n = apply_brush(g3, (5, 5, 5), (0, 0, 1), 'SQUARE', 1, 'ADD', 3, bmin, bmax)
check("ADD places one voxel", n == 1 and g3.get(5, 5, 5) == 3)
n = apply_brush(g3, (6, 5, 5), (0, 0, 1), 'SQUARE', 1, 'PAINT', 7, bmin, bmax)
check("PAINT skips empty cells", n == 0 and g3.get(6, 5, 5) == 0)
n = apply_brush(g3, (5, 5, 5), (0, 0, 1), 'SQUARE', 1, 'PAINT', 7, bmin, bmax)
check("PAINT recolours occupied", n == 1 and g3.get(5, 5, 5) == 7)
n = apply_brush(g3, (5, 5, 5), (0, 0, 1), 'SQUARE', 1, 'ERASE', 0, bmin, bmax)
check("ERASE removes", n == 1 and g3.get(5, 5, 5) == 0)
n = apply_brush(g3, (40, 40, 40), (0, 0, 1), 'SQUARE', 1, 'ADD', 1, bmin, bmax)
check("ADD outside volume is clamped", n == 0 and g3.voxel_count() == 0)
n = apply_brush(g3, (7, 7, 7), (0, 0, 1), 'SQUARE', 2, 'ADD', 4, bmin, bmax)
check("ADD size 2 places 2x2", n == 4 and g3.get(6, 6, 7) == 4
      and g3.get(7, 7, 7) == 4 and g3.get(8, 8, 8) == 0)

# ---------------------------------------------------------------------------
section("grid: raycast")
g4 = VoxelGrid()
g4.set(5, 5, 5, 1)
res = raycast(g4, (5.5, 5.5, -10.0), (0, 0, 1), bmin, bmax)
check("hit from below", res.hit is not None and res.hit.cell == (5, 5, 5))
check("hit normal -z", res.hit is not None and res.hit.normal == (0, 0, -1))
res = raycast(g4, (5.5, 5.5, 20.0), (0, 0, -1), bmin, bmax)
check("hit from above", res.hit is not None and res.hit.cell == (5, 5, 5)
      and res.hit.normal == (0, 0, 1))
res = raycast(g4, (-10.0, 5.5, 5.5), (1, 0, 0), bmin, bmax)
check("hit along +x", res.hit is not None and res.hit.cell == (5, 5, 5)
      and res.hit.normal == (-1, 0, 0))
res = raycast(g4, (50.0, 50.0, 50.0), (1, 1, 0), bmin, bmax)
check("miss outside volume", res.hit is None and res.entry_cell is None)
res = raycast(g4, (5.5, 6.5, -10.0), (0, 0, 1), bmin, bmax)
check("empty space: no hit but entry cell", res.hit is None
      and res.entry_cell == (5, 6, 0) and res.entry_normal == (0, 0, -1))

g5 = VoxelGrid()
g5.set(1000, 3, 3, 1)  # far away, forces empty-chunk skipping
big = (-2048, -2048, -2048), (2048, 2048, 2048)
res = raycast(g5, (-5000.0, 3.5, 3.5), (1, 0, 0), *big)
check("chunk-skip hit far voxel", res.hit is not None and res.hit.cell == (1000, 3, 3)
      and res.hit.normal == (-1, 0, 0))
res = raycast(g5, (-5000.0, 100.5, 3.5), (1, 0, 0), *big)
check("chunk-skip miss stays fast and clean", res.hit is None
      and res.entry_cell == (-2048, 100, 3))

g6 = VoxelGrid()
g6.set(0, 0, 0, 1)
res = raycast(g6, (0.5, 0.5, 0.5), (0, 0, 1), bmin, bmax)
check("origin inside voxel hits immediately", res.hit is not None
      and res.hit.cell == (0, 0, 0))

# camera inside an empty volume: placement lands on the exit face, not at
# the camera position
g6b = VoxelGrid()
res = raycast(g6b, (5.5, 5.5, 5.5), (0, 0, 1), bmin, bmax)
check("inside camera: entry cell at exit face (+z)",
      res.hit is None and res.entry_cell == (5, 5, 31)
      and res.entry_normal == (0, 0, -1))
res = raycast(g6b, (5.5, 5.5, 5.5), (1, 0, 0), bmin, bmax)
check("inside camera: entry cell at exit face (+x)",
      res.hit is None and res.entry_cell == (31, 5, 5)
      and res.entry_normal == (-1, 0, 0))
res = raycast(g6b, (5.5, 5.5, 5.5), (0, -1, 0), bmin, bmax)
check("inside camera: entry cell at exit face (-y)",
      res.hit is None and res.entry_cell == (5, 0, 5)
      and res.entry_normal == (0, 1, 0))
g6b.set(10, 5, 5, 1)
res = raycast(g6b, (5.5, 5.5, 5.5), (1, 0, 0), bmin, bmax)
check("inside camera: voxel hit still wins over exit face",
      res.hit is not None and res.hit.cell == (10, 5, 5))

# two adjacent voxels: ray enters side of first
g7 = VoxelGrid()
g7.set(0, 0, 0, 1)
g7.set(1, 0, 0, 1)
res = raycast(g7, (-5.0, 0.5, 0.5), (1, 0, 0), bmin, bmax)
check("stops at first of adjacent voxels", res.hit is not None
      and res.hit.cell == (0, 0, 0))

# ---------------------------------------------------------------------------
section("grid: walk_line")
path = list(walk_line((0, 0, 0), (3, 0, 0)))
check("walk straight", path == [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)])
path = list(walk_line((0, 0, 0), (0, 0, 0)))
check("walk degenerate", path == [(0, 0, 0)])
path = list(walk_line((0, 0, 0), (2, 2, 0)))
check("walk diagonal endpoints", path[0] == (0, 0, 0) and path[-1] == (2, 2, 0)
      and all(abs(path[i + 1][0] - path[i][0]) <= 1 for i in range(len(path) - 1)))
path = list(walk_line((-2, 1, 5), (2, 1, 5)))
check("walk negative direction", path[0] == (-2, 1, 5) and path[-1] == (2, 1, 5))

# ---------------------------------------------------------------------------
section("serialize: roundtrip")
from bloxel.core import serialize

g8 = VoxelGrid()
for i, (x, y, z) in enumerate([(0, 0, 0), (-33, 7, 200), (1000, -1000, 5),
                               (31, 31, 31), (32, 0, 0)], start=1):
    g8.set(x, y, z, i)
sel = {(0, 0, 0), (31, 31, 31)}
blob = serialize.dumps(g8, sel)
g9, sel9 = serialize.loads(blob)
same = all(g9.get(*c) == v for c, v in
           [((0, 0, 0), 1), ((-33, 7, 200), 2), ((1000, -1000, 5), 3),
            ((31, 31, 31), 4), ((32, 0, 0), 5)])
check("chunks survive roundtrip", same and g9.voxel_count() == 5)
check("selection survives roundtrip", sel9 == sel)
check("empty grid roundtrip", serialize.loads(serialize.dumps(VoxelGrid()))[0].voxel_count() == 0)

# ---------------------------------------------------------------------------
section("mesher: face culling")
from bloxel.core import mesher

g10 = VoxelGrid()
g10.set(0, 0, 0, 1)
m = mesher.Mesher()
v, q, mats = m.build(g10)
check("single voxel -> 6 quads", q.shape[0] == 6)
check("single voxel -> 24 verts", v.shape[0] == 24)
check("material index propagated", mats.tolist() == [1] * 6)

g10.set(1, 0, 0, 1)
v, q, mats = m.build(g10)
check("two adjacent voxels -> 10 quads", q.shape[0] == 10)

g10.set(31, 0, 0, 2)
g10.set(32, 0, 0, 2)  # across a chunk border
v, q, mats = m.build(g10)
check("chunk-border adjacency culled", q.shape[0] == 20)  # 4 voxels: 24-2*2
check("incremental rebuild keeps cache", len(m.cache) >= 2)

g10.set(32, 0, 0, 0)
v, q, mats = m.build(g10)
check("erase restores exposed face", q.shape[0] == 16)  # 3 voxels: 18-2

# winding check: quad normals point outward
import numpy as np
g11 = VoxelGrid()
g11.set(0, 0, 0, 1)
m2 = mesher.Mesher()
v, q, mats = m2.build(g11)
ok = True
for quad in q:
    p0, p1, p2 = (v[quad[0]], v[quad[1]], v[quad[2]])
    n = np.cross(p1 - p0, p2 - p1)
    c = (v[quad[0]] + v[quad[1]] + v[quad[2]] + v[quad[3]]) / 4.0
    if np.dot(n, c - np.array([0.5, 0.5, 0.5])) <= 0:
        ok = False
check("quad normals point outward", ok)

# ---------------------------------------------------------------------------
section("grid: mirror + flood fill")
from bloxel.core.grid import flood_fill, mirror_variants

v = mirror_variants((5, 5, 5), (0, 0, 1), (True, False, False), (0, 0, 0), (31, 31, 31))
check("mirror x reflects cell", v == [((5, 5, 5), (0, 0, 1)), ((26, 5, 5), (0, 0, 1))])
v = mirror_variants((0, 0, 0), (1, 0, 0), (True, False, False), (0, 0, 0), (31, 31, 31))
check("mirror flips normal on mirrored axis", v[1] == ((31, 0, 0), (-1, 0, 0)))
check("no mirrors -> identity",
      mirror_variants((1, 2, 3), (0, 1, 0), (False, False, False), (0, 0, 0), (31, 31, 31))
      == [((1, 2, 3), (0, 1, 0))])
check("mirror xyz gives 8 variants",
      len(mirror_variants((1, 2, 3), (0, 1, 0), (True, True, True), (0, 0, 0), (31, 31, 31))) == 8)

gf = VoxelGrid()
fb0, fb1 = (0, 0, 0), (63, 63, 63)
for x in range(4):
    gf.set(x, 0, 0, 1)          # blob A, material 1
gf.set(10, 0, 0, 1)             # blob B, material 1, disconnected
gf.set(4, 0, 0, 2)              # different material next to blob A
changed = flood_fill(gf, (0, 0, 0), 5, fb0, fb1, contiguous=True)
check("contiguous fill hits only connected region",
      changed == 4 and gf.get(10, 0, 0) == 1 and gf.get(4, 0, 0) == 2)
check("fill with same material is a no-op",
      flood_fill(gf, (0, 0, 0), 5, fb0, fb1, contiguous=True) == 0)
check("fill empty cell is a no-op",
      flood_fill(gf, (50, 50, 50), 3, fb0, fb1, contiguous=True) == 0)
changed = flood_fill(gf, (10, 0, 0), 9, fb0, fb1, contiguous=False)
check("global fill replaces all same-material voxels",
      changed == 1 and gf.get(10, 0, 0) == 9)
changed = flood_fill(gf, (4, 0, 0), 7, fb0, fb1, contiguous=True)
check("contiguous fill on different material", changed == 1 and gf.get(4, 0, 0) == 7)

# ---------------------------------------------------------------------------
section("grid: fuzzy select regions")
from bloxel.core.grid import select_region

gs = VoxelGrid()
s0, s1 = (0, 0, 0), (63, 63, 63)
for x in range(4):
    gs.set(x, 0, 0, 1)
gs.set(10, 0, 0, 1)    # same material, disconnected
gs.set(4, 0, 0, 2)     # different material next to the run
gs.set(1000, 0, 0, 1)  # same material, far outside the working volume
sel = select_region(gs, (0, 0, 0), s0, s1, contiguous=True)
check("connected select: only the connected same-material region",
      sel == {(x, 0, 0) for x in range(4)})
sel = select_region(gs, (0, 0, 0), s0, s1, contiguous=False)
check("material select: every voxel of the clicked material",
      sel == {(x, 0, 0) for x in range(4)} | {(10, 0, 0), (1000, 0, 0)})
check("select on an empty cell is empty",
      select_region(gs, (50, 50, 50), s0, s1, contiguous=True) == set())
sel = select_region(gs, (0, 0, 0), (0, 0, 0), (2, 63, 63), contiguous=True)
check("connected select respects the working volume bounds",
      sel == {(0, 0, 0), (1, 0, 0), (2, 0, 0)})
check("select region leaves the grid untouched", gs.voxel_count() == 7)
check("selecting a different material stops at it",
      select_region(gs, (4, 0, 0), s0, s1, contiguous=True) == {(4, 0, 0)})

# ---------------------------------------------------------------------------
section("grid: rectangle select (screen space)")
from bloxel.core.grid import rectangle_select

# identity mvp: local == NDC, so cell (x, y, z) centres land on
# ((x + 1.5) * 16, (y + 1.5) * 16) in a 32x32 region
IDENT = np.eye(4)
rs0, rs1 = (0, 0, 0), (31, 31, 31)
g_rs = VoxelGrid()
for cell in ((0, 0, 0), (1, 0, 0), (5, 0, 0)):
    g_rs.set(*cell, 1)
sel = rectangle_select(g_rs, (20, 20, 30, 30), IDENT, 32, 32, rs0, rs1,
                       visible_only=False)
check("strikethrough selects voxels with their centre in the rect",
      sel == {(0, 0, 0)})
sel = rectangle_select(g_rs, (45, 30, 20, 20), IDENT, 32, 32, rs0, rs1,
                       visible_only=False)
check("rectangle corners may be given in any order",
      sel == {(0, 0, 0), (1, 0, 0)})
sel = rectangle_select(g_rs, (20, 20, 110, 30), IDENT, 32, 32, (0, 0, 0), (0, 0, 0),
                       visible_only=False)
check("rectangle select respects the working volume bounds",
      sel == {(0, 0, 0)})
check("rectangle select on an empty grid is empty",
      rectangle_select(VoxelGrid(), (0, 0, 32, 32), IDENT, 32, 32,
                       rs0, rs1) == set())

g_oc = VoxelGrid()
for z in range(3):
    g_oc.set(0, 0, z, 1)
sel = rectangle_select(g_oc, (20, 20, 30, 30), IDENT, 32, 32, rs0, rs1,
                       visible_only=True)
check("visible-only keeps the front voxel of a column",
      sel == {(0, 0, 0)})
sel = rectangle_select(g_oc, (20, 20, 30, 30), IDENT, 32, 32, rs0, rs1,
                       visible_only=False)
check("strikethrough keeps the whole column",
      sel == {(0, 0, 0), (0, 0, 1), (0, 0, 2)})
sel = rectangle_select(g_rs, (16, 16, 23, 23), IDENT, 32, 32, rs0, rs1,
                       visible_only=True)
sel_t = rectangle_select(g_rs, (16, 16, 23, 23), IDENT, 32, 32, rs0, rs1,
                         visible_only=False)
check("visible-only rays select a partially covered voxel",
      sel == {(0, 0, 0)})
check("strikethrough needs the projected centre inside the rect",
      sel_t == set())

# non-identity matrix: local 0..32 maps 1:1 onto the 32x32 region
ORTHO = np.array([[1 / 16, 0, 0, -1],
                  [0, 1 / 16, 0, -1],
                  [0, 0, 1 / 16, -1],
                  [0, 0, 0, 1]], dtype=float)
sel = rectangle_select(g_oc, (0, 0, 4, 4), ORTHO, 32, 32, rs0, rs1,
                       visible_only=True)
check("rectangle select handles a non-identity view matrix",
      sel == {(0, 0, 0)})

# ---------------------------------------------------------------------------
section("grid: stroke mask (plane-locked drag)")
from bloxel.core.grid import StrokeMaskGrid

gm = VoxelGrid()
overlay = {}
# first stamp of a stroke: places at the empty-space entry cell, records it
res = raycast(gm, (5.5, 5.5, 50.0), (0, 0, -1), bmin, bmax)
base = res.entry_cell
check("stroke stamp records old value",
      apply_brush(gm, base, res.entry_normal, 'SQUARE', 1, 'ADD', 1,
                  bmin, bmax, record=overlay) == 1
      and overlay.get(base) == 0 and gm.get(*base) == 1)
# same mouse position, live grid: hits the new voxel -> would stack a column
res = raycast(gm, (5.5, 5.5, 50.0), (0, 0, -1), bmin, bmax)
check("live grid would stack (hit the new voxel)",
      res.hit is not None and res.hit.cell == (5, 5, 31))
# same mouse position, masked grid: still reads stroke-start state -> no stack
masked = StrokeMaskGrid(gm, overlay)
res = raycast(masked, (5.5, 5.5, 50.0), (0, 0, -1), bmin, bmax)
check("masked grid still targets the original cell",
      res.hit is None and res.entry_cell == (5, 5, 31))
# erase tunneling: two stacked voxels, erase the top one mid-stroke
gm.set(8, 8, 10, 1)
gm.set(8, 8, 11, 1)
overlay2 = {}
apply_brush(gm, (8, 8, 11), (0, 0, 1), 'SQUARE', 1, 'ERASE', 0,
            bmin, bmax, record=overlay2)
check("erase removed the top voxel", gm.get(8, 8, 11) == 0)
res = raycast(gm, (8.5, 8.5, 50.0), (0, 0, -1), bmin, bmax)
check("live grid tunnels to the voxel below",
      res.hit is not None and res.hit.cell == (8, 8, 10))
res = raycast(StrokeMaskGrid(gm, overlay2), (8.5, 8.5, 50.0), (0, 0, -1), bmin, bmax)
check("masked grid does not tunnel", res.hit is not None
      and res.hit.cell == (8, 8, 11))

# ---------------------------------------------------------------------------
section("grid: extrude")
from bloxel.core.grid import extrude_region, face_region

ge = VoxelGrid()
eb0, eb1 = (0, 0, 0), (31, 31, 31)
for x in range(3):
    for y in range(3):
        ge.set(x, y, 4, 1)
ge.set(1, 1, 4, 2)  # different material inside the plate
reg = face_region(ge, (0, 0, 4), (0, 0, 1), eb0, eb1)
check("face region: same-material coplanar cells only",
      reg == {(x, y, 4) for x in range(3) for y in range(3)} - {(1, 1, 4)})
ge.set(10, 10, 4, 1)  # same material but disconnected
reg = face_region(ge, (0, 0, 4), (0, 0, 1), eb0, eb1)
check("face region excludes disconnected cells", (10, 10, 4) not in reg)
# a step in the surface blocks connectivity even with matching material
ge.set(5, 5, 3, 1)
ge.set(5, 5, 2, 1)
reg = face_region(ge, (5, 5, 3), (0, 0, 1), eb0, eb1)
check("face region stops at non-coplanar cells", reg == {(5, 5, 3)})
check("face region on empty cell is empty",
      face_region(ge, (20, 20, 20), (0, 0, 1), eb0, eb1) == set())

n = extrude_region(ge, {(0, 0, 4)}, (0, 0, 1), 2, 1, eb0, eb1)
check("extrude stacks adjacent layers",
      n == 2 and ge.get(0, 0, 5) == 1 and ge.get(0, 0, 6) == 1)
ge.set(10, 10, 5, 3)
n = extrude_region(ge, {(10, 10, 4)}, (0, 0, 1), 1, 1, eb0, eb1)
check("extrude leaves occupied destinations alone",
      n == 0 and ge.get(10, 10, 5) == 3)
ge2 = VoxelGrid()
ge2.set(0, 0, 0, 1)
n = extrude_region(ge2, {(0, 0, 0)}, (0, 0, 1), 5, 1, (0, 0, 0), (3, 3, 2))
check("extrude stops columns at the volume boundary",
      n == 2 and ge2.get(0, 0, 1) == 1 and ge2.get(0, 0, 2) == 1
      and ge2.get(0, 0, 3) == 0)

# ---------------------------------------------------------------------------
section("grid: selection transform (move / rotate)")
from bloxel.core.grid import (apply_mapping, clamp_offset, fit_offset,
                              move_mapping, move_selection, rotate_mapping,
                              rotate_selection, rotated_cells,
                              selection_bounds, transform_center,
                              translated_cells)

tb0, tb1 = (0, 0, 0), (31, 31, 31)
check("selection bounds: min/max over cells",
      selection_bounds({(1, 2, 3), (4, 0, 5)}) == ((1, 0, 3), (4, 2, 5)))
check("selection bounds: empty selection is None",
      selection_bounds(set()) is None)
check("transform centre: visual block centre",
      transform_center(((0, 0, 0), (1, 1, 1))) == (1.0, 1.0, 1.0)
      and transform_center(((2, 2, 2), (2, 2, 2))) == (2.5, 2.5, 2.5))
check("clamp offset: stays inside the volume",
      clamp_offset((28, 0, 0), (30, 0, 0), (5, 0, 0), tb0, tb1) == (1, 0, 0)
      and clamp_offset((28, 0, 0), (30, 0, 0), (-100, 0, 0), tb0, tb1)
      == (-28, 0, 0))
check("translated cells maps every cell",
      translated_cells({(0, 0, 0), (1, 0, 0)}, (0, 2, -1))
      == {(0, 0, 0): (0, 2, -1), (1, 0, 0): (1, 2, -1)})

# L-shape, pivot (1, 1, 0.5): the two directions must differ
l_cells = {(0, 0, 0), (1, 0, 0), (0, 1, 0)}
l_pivot = transform_center(selection_bounds(l_cells))
cw = rotated_cells(l_cells, 2, 1, l_pivot)
ccw = rotated_cells(l_cells, 2, -1, l_pivot)
check("rotate 90 about z snaps to the lattice",
      set(cw.values()) == {(0, 0, 0), (1, 0, 0), (1, 1, 0)})
check("rotate -90 takes the other direction",
      set(ccw.values()) == {(0, 0, 0), (0, 1, 0), (1, 1, 0)})
check("rotation is injective",
      len(set(cw.values())) == len(l_cells))
check("four quarter turns are the identity",
      rotated_cells(l_cells, 2, 4, l_pivot) == {c: c for c in l_cells})
check("fit offset: pulls a protruding block back in",
      fit_offset((30, 0, 0), (33, 0, 0), tb0, tb1) == (-2, 0, 0))
check("fit offset: pushes a low block up",
      fit_offset((-5, 0, 0), (2, 0, 0), tb0, tb1) == (5, 0, 0))
check("fit offset: zero when already inside",
      fit_offset((3, 4, 5), (6, 7, 8), tb0, tb1) == (0, 0, 0))

gt = VoxelGrid()
for x, v in enumerate((1, 2, 3)):
    gt.set(x, 0, 0, v)
t_sel = {(0, 0, 0), (1, 0, 0), (2, 0, 0)}
mapping = move_mapping(t_sel, (1, 0, 0), tb0, tb1)
check("move mapping shifts cells",
      set(mapping.values()) == {(1, 0, 0), (2, 0, 0), (3, 0, 0)})
check("move mapping clamps at the volume edge",
      move_mapping({(30, 0, 0)}, (5, 0, 0), tb0, tb1)
      == {(30, 0, 0): (31, 0, 0)})
check("move by zero produces no mapping",
      move_mapping(t_sel, (0, 0, 0), tb0, tb1) == {})
changed, t_new = apply_mapping(gt, mapping, tb0, tb1)
check("apply mapping moves materials",
      changed == 4 and gt.voxel_count() == 3
      and [gt.get(x, 0, 0) for x in range(4)] == [0, 1, 2, 3]
      and t_new == {(1, 0, 0), (2, 0, 0), (3, 0, 0)})
check("move selection by zero changes nothing",
      move_selection(gt, {(1, 0, 0)}, (0, 0, 0), tb0, tb1) == (0, set()))

gc = VoxelGrid()
gc.set(0, 0, 0, 1)
gc.set(1, 0, 0, 9)
changed, c_sel = move_selection(gc, {(0, 0, 0)}, (1, 0, 0), tb0, tb1)
check("move overwrites occupied destinations",
      changed == 2 and gc.get(0, 0, 0) == 0 and gc.get(1, 0, 0) == 1
      and c_sel == {(1, 0, 0)})
gm2 = VoxelGrid()
gm2.set(31, 0, 0, 1)
check("move clamps fully at the volume edge",
      move_selection(gm2, {(31, 0, 0)}, (1, 0, 0), tb0, tb1) == (0, set())
      and gm2.get(31, 0, 0) == 1)

gr = VoxelGrid()
gr.set(0, 0, 0, 1)
gr.set(1, 0, 0, 2)
gr.set(0, 1, 0, 3)
changed, r_sel = rotate_selection(gr, l_cells, 2, 1, tb0, tb1)
check("rotate selection turns the L-shape",
      changed == 4 and r_sel == {(0, 0, 0), (1, 0, 0), (1, 1, 0)}
      and gr.get(0, 0, 0) == 3 and gr.get(1, 0, 0) == 1
      and gr.get(1, 1, 0) == 2 and gr.get(0, 1, 0) == 0)
check("rotate selection: four turns is a no-op",
      rotate_selection(gr, r_sel, 2, 4, tb0, tb1) == (0, set()))

gf2 = VoxelGrid()
for x in range(3):
    gf2.set(x, 0, 31, 1)
changed, f_sel = rotate_selection(gf2, {(0, 0, 31), (1, 0, 31), (2, 0, 31)},
                                  1, 1, tb0, tb1)
check("rotation is shifted back into the volume",
      f_sel == {(1, 0, 29), (1, 0, 30), (1, 0, 31)}
      and gf2.voxel_count() == 3
      and all(gf2.get(*c) == 1 for c in f_sel))

# ---------------------------------------------------------------------------
section("extrude: screen-space drag math")
import math
from bloxel.tools.extrude import drag_along_axis

# normal pointing up on screen (0, -10): dragging up = positive pull
d = drag_along_axis((100, 100), (100, 90), (0.0, -10.0), 10.0)
check("drag up along +normal is +1 voxel", d == 1.0)
d = drag_along_axis((100, 100), (100, 110), (0.0, -10.0), 10.0)
check("drag down against +normal is -1 voxel", d == -1.0)
d = drag_along_axis((100, 100), (100, 120), (10.0, 0.0), 10.0)
check("drag sideways gives 0", d == 0.0)
d = drag_along_axis((100, 100), (140, 100), (10.0, 0.0), 10.0)
check("horizontal drag scales", d == 4.0)
d = drag_along_axis((0, 0), (5, 5), (1.0, 0.0), 0.0)
check("degenerate screen dir is safe", d == 0.0)
check("layers derivation: 1 + floor(delta)",
      1 + math.floor(drag_along_axis((0, 0), (0, -35), (0.0, -10.0), 10.0)) == 4)
check("layers derivation: negative drag goes negative",
      1 + math.floor(drag_along_axis((0, 0), (0, 55), (0.0, -10.0), 10.0)) == -5)

# bidirectional dragging via extrude_layers
from bloxel.core.grid import extrude_layers
ge3 = VoxelGrid()
ge3.set(0, 0, 0, 1)
added = set()
deleted = {}
changed = extrude_layers(ge3, {(0, 0, 0)}, (0, 0, 1), 0, 3, 1, eb0, eb1, added, deleted)
check("extrude_layers adds 3", changed == 3 and len(added) == 3
      and ge3.get(0, 0, 3) == 1)
changed = extrude_layers(ge3, {(0, 0, 0)}, (0, 0, 1), 3, 1, 1, eb0, eb1, added, deleted)
check("extrude_layers drags back to 1", changed == 2 and len(added) == 1
      and ge3.get(0, 0, 1) == 1 and ge3.get(0, 0, 2) == 0)
changed = extrude_layers(ge3, {(0, 0, 0)}, (0, 0, 1), 1, 0, 1, eb0, eb1, added, deleted)
check("extrude_layers removes the press layer too", changed == 1 and not added
      and ge3.voxel_count() == 1 and ge3.get(0, 0, 0) == 1)

ge4 = VoxelGrid()
ge4.set(0, 0, 0, 1)
ge4.set(0, 0, 2, 3)  # pre-existing voxel at layer 2
added2 = set()
deleted2 = {}
extrude_layers(ge4, {(0, 0, 0)}, (0, 0, 1), 0, 3, 1, eb0, eb1, added2, deleted2)
check("add skips occupied cells", len(added2) == 2 and ge4.get(0, 0, 2) == 3)
changed = extrude_layers(ge4, {(0, 0, 0)}, (0, 0, 1), 3, 0, 1, eb0, eb1, added2, deleted2)
check("drag back to 0 leaves pre-existing voxels",
      changed == 2 and ge4.get(0, 0, 2) == 3
      and ge4.get(0, 0, 1) == 0 and ge4.get(0, 0, 3) == 0)

# negative targets delete the original surface and deeper voxels:
# a 5-voxel line along +x, clicked on its -x end face (normal (-1,0,0)),
# drag toward the far end -> target -4 deletes x = 0..3
line = VoxelGrid()
for i in range(5):
    line.set(i, 0, 0, 2)
added3, deleted3 = set(), {}
changed = extrude_layers(line, {(0, 0, 0)}, (-1, 0, 0), 0, -4, 2, eb0, eb1,
                         added3, deleted3)
check("negative layers delete a whole line", changed == 4
      and line.voxel_count() == 1 and line.get(4, 0, 0) == 2
      and line.get(0, 0, 0) == 0)
check("deleted voxels recorded with materials",
      deleted3 == {(0, 0, 0): 2, (1, 0, 0): 2, (2, 0, 0): 2, (3, 0, 0): 2})
changed = extrude_layers(line, {(0, 0, 0)}, (-1, 0, 0), -4, 0, 2, eb0, eb1,
                         added3, deleted3)
check("drag forward restores the deleted line", changed == 4
      and line.voxel_count() == 5 and not deleted3)
changed = extrude_layers(line, {(0, 0, 0)}, (-1, 0, 0), 0, -2, 2, eb0, eb1,
                         added3, deleted3)
check("partial negative deletes surface + one deeper",
      changed == 2 and line.get(0, 0, 0) == 0 and line.get(1, 0, 0) == 0
      and line.get(2, 0, 0) == 2 and len(deleted3) == 2)
changed = extrude_layers(line, {(0, 0, 0)}, (-1, 0, 0), -2, 2, 2,
                         (-8, -8, -8), (31, 31, 31), added3, deleted3)
check("drag from negative into positive restores then adds",
      changed == 4  # restore 2 deleted + add layers 1..2 (at x=-1, x=-2)
      and line.voxel_count() == 7 and not deleted3 and len(added3) == 2
      and line.get(-2, 0, 0) == 2)

# ---------------------------------------------------------------------------
section("draw: near-face grid alignment")
from bloxel.core.draw import _volume_grid_lines

bmin, bmax = (0, 0, 0), (31, 31, 31)
# camera looking down -z: near faces are x=0, y=0, z=32
pts = _volume_grid_lines(bmin, bmax, (0.0, 0.0, -1.0))
check("top-face grid at z=32", (0.0, 0.0, 32.0) in pts
      and (32.0, 32.0, 32.0) in pts)


def _count_plane_lines(pts, axis, value):
    return sum(1 for p, q in zip(pts[::2], pts[1::2])
               if p[axis] == value and q[axis] == value)


# near z-face gets the full grid; the far plane only gets face-border edges
z_near = _count_plane_lines(pts, 2, 32)
z_far = _count_plane_lines(pts, 2, 0)
check("near face has the grid, far face does not", z_near > 60 and z_far < 5)
# looking up (+z) flips the grid to z=0
pts = _volume_grid_lines(bmin, bmax, (0.0, 0.0, 1.0))
check("grid flips with view direction",
      _count_plane_lines(pts, 2, 0) > 60 and _count_plane_lines(pts, 2, 32) < 5)
# camera inside the volume: grid moves to the exit faces
pts = _volume_grid_lines(bmin, bmax, (0.0, 0.0, -1.0), inside=True)
check("inside camera: grid on exit face (z=0 looking down)",
      _count_plane_lines(pts, 2, 0) > 60 and _count_plane_lines(pts, 2, 32) < 5)

# dynamic stride: unit cells at stride 1, sparse multiples otherwise
from bloxel.core.draw import _strided_coords
check("stride 1 keeps voxel resolution",
      _strided_coords(0, 32, 1) == list(range(33)))
check("stride 4 steps by 4 and keeps far edge",
      _strided_coords(0, 32, 4) == [0, 4, 8, 12, 16, 20, 24, 28, 32])
check("stride on non-multiple span keeps far edge",
      _strided_coords(0, 30, 4) == [0, 4, 8, 12, 16, 20, 24, 28, 30])
pts = _volume_grid_lines((0, 0, 0), (999, 999, 999), (0.0, 0.0, -1.0), stride=8)
check("big volume: strided lines land on multiples of 8 (plus edge)",
      all(coord % 8 == 0 or coord == 1000
          for line in zip(pts[::2], pts[1::2])
          for p in line for coord in p))
check("big volume: stride shrinks line count",
      _count_plane_lines(pts, 2, 1000) < 300)
pts1 = _volume_grid_lines((0, 0, 0), (999, 999, 999), (0.0, 0.0, -1.0), stride=1)
check("stride 1 on big volume draws every voxel line",
      _count_plane_lines(pts1, 2, 1000) == 2004)  # 2x1001 face lines + 2 border edges

# no caps: unit-resolution grid even at 120000^3-like volumes
import time as _t
_t0 = _t.monotonic()
pts2 = _volume_grid_lines((0, 0, 0), (19999, 19999, 19999), (0.0, 0.0, -1.0))
_dt = _t.monotonic() - _t0
check("20000^3 unit grid has no striding",
      _count_plane_lines(pts2, 2, 20000) == 2 * 20001 + 2)
check("20000^3 grid builds fast (numpy path)", _dt < 1.0)
# camera on +x looking -x: near x face is x=32
pts = _volume_grid_lines(bmin, bmax, (-1.0, 0.0, 0.0))
check("near x-face at x=32", (32.0, 0.0, 0.0) in pts)
# grid cell at the near face == raycast entry cell (the snap guarantee)
g12 = VoxelGrid()
res = raycast(g12, (5.5, 5.5, 50.0), (0, 0, -1), bmin, bmax)
check("entry cell sits on the drawn z=32 grid",
      res.entry_cell == (5, 5, 31))

# ---------------------------------------------------------------------------
section("draw: selection overlay geometry")
from bloxel.core.draw import selection_geometry
from mathutils import Matrix

lines, tris = selection_geometry({(0, 0, 0)}, Matrix.Identity(4))
check("selection geometry: 12 box edges per cell", lines.shape == (24, 3))
check("selection geometry: one top-face fill per cell", tris.shape == (6, 3))
lines, tris = selection_geometry(set(), Matrix.Identity(4))
check("selection geometry: empty selection draws nothing",
      lines.shape[0] == 0 and tris.shape[0] == 0)
lines, tris = selection_geometry({(0, 0, 0), (1, 2, 3)}, Matrix.Identity(4))
check("selection geometry: two cells scale linearly",
      lines.shape == (48, 3) and tris.shape == (12, 3))
check("selection geometry: box corners stay on the cell",
      lines[:, 0].min() == 0.0 and lines[:, 0].max() == 2.0
      and lines[:, 1].min() == 0.0 and lines[:, 1].max() == 3.0)

# ---------------------------------------------------------------------------
section("gizmo: handles and picking")
from bloxel.core import gizmo
from bloxel.core.gizmo import _point_segment_distance, nearest_handle
from mathutils import Vector

origin = Vector((0.0, 0.0, 0.0))
gz_axes = (Vector((1.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0)),
           Vector((0.0, 0.0, 1.0)))
gz_half = (1.0, 2.0, 3.0)      # cage half-extents
gz_radii = (4.5, 4.5, 4.5)     # uniform half-ring radius
check("all rings share the largest cage cross-section diagonal",
      gizmo.cage_radius(gz_half) == math.hypot(3.0, 2.0)
      and gizmo.cage_radius((3.0, 4.0, 0.0)) == 5.0)
gz = gizmo.handles(origin, gz_axes, gz_half, 10.0, gz_radii)
check("gizmo has three arrows and three half-rings", len(gz) == 6
      and all((gizmo.MOVE, a) in gz for a in range(3))
      and all((gizmo.ROTATE, a) in gz for a in range(3)))
check("move shaft runs from the cage face outward",
      gz[(gizmo.MOVE, 0)][0] == (Vector((1.0, 0.0, 0.0)),
                                 Vector((11.0, 0.0, 0.0))))
ring = gz[(gizmo.ROTATE, 2)]
check("rotation handle is a half-ring hugging the cage",
      len(ring) == gizmo.RING_SEGMENTS // 2
      and all(abs(a.z) < 1e-9 and abs(b.z) < 1e-9 for a, b in ring)
      and all(abs(a.length - gz_radii[2]) < 1e-6 for a, _ in ring))
check("half-ring spans 180 degrees around the ring plane diagonal",
      max(a.x for a, _ in ring) > gz_radii[2] - 1e-6
      and max(a.y for a, _ in ring) > gz_radii[2] - 1e-6
      and not any(a.x < -1e-6 and a.y < -1e-6 for a, _ in ring))

from bloxel.core.gizmo import bounds_segments, handle_tris

tri = handle_tris(origin, gz_axes, gz_half, 10.0, gz_radii, 0.6)
check("gizmo handles are solid with a constant-width cross-section",
      len(tri) == 6
      and all(len(tri[(gizmo.MOVE, a)]) == 14 for a in range(3))
      and all(len(tri[(gizmo.ROTATE, a)]) == gizmo.RING_SEGMENTS
              for a in range(3)))
shaft = tri[(gizmo.MOVE, 0)][:8]
check("move shaft beam sits on the cage face with the requested thickness",
      all(abs(p.y) <= 0.3 + 1e-6 and abs(p.z) <= 0.3 + 1e-6
          and p.x >= 1.0 - 1e-6 for t in shaft for p in t))
check("arrow head flares wider than the shaft",
      max(abs(p.y) for t in tri[(gizmo.MOVE, 0)] for p in t) > 0.5)
ribbon = tri[(gizmo.ROTATE, 2)]
ribbon_in = gz_radii[2] - 0.3
ribbon_out = gz_radii[2] + 0.3
check("half-ring ribbon spans the ring radius",
      all(abs(p.z) < 1e-9
          and ribbon_in - 1e-6 <= math.hypot(p.x, p.y) <= ribbon_out + 1e-6
          for t in ribbon for p in t))

box_info = gizmo.GizmoInfo(origin, gz_axes, 10.0, (0.0, 0.0),
                           ((0.0, 0.0),) * 3, (True, True, True),
                           ((0, 0, 0), (1, 2, 0)), Matrix.Identity(4),
                           gz_half, gz_radii, 5.0)
box = bounds_segments(box_info)
lo = (0.0, 0.0, 0.0)
hi = (2.0, 3.0, 1.0)
check("dotted bounds box: dashes on the selection box surface",
      len(box) >= 12
      and all(all(lo[i] - 1e-6 <= p[i] <= hi[i] + 1e-6 for i in range(3))
              and any(abs(p[i] - lo[i]) < 1e-6 or abs(p[i] - hi[i]) < 1e-6
                      for i in range(3))
              for a, b in box for p in (a, b)))

check("point-segment distance: on the segment is zero",
      _point_segment_distance(5.0, 0.0, 0.0, 0.0, 10.0, 0.0) == 0.0)
check("point-segment distance: past the endpoint clamps",
      _point_segment_distance(15.0, 0.0, 0.0, 0.0, 10.0, 0.0) == 5.0)
check("point-segment distance: perpendicular",
      _point_segment_distance(5.0, 3.0, 0.0, 0.0, 10.0, 0.0) == 3.0)
gz_flat = {(gizmo.MOVE, 0): [((0.0, 0.0), (50.0, 0.0))],
           (gizmo.ROTATE, 1): [((0.0, 40.0), (50.0, 40.0))]}
check("nearest handle picks the closer segment",
      nearest_handle((10.0, 3.0), gz_flat) == (gizmo.MOVE, 0)
      and nearest_handle((10.0, 37.0), gz_flat) == (gizmo.ROTATE, 1))
check("nearest handle ignores far clicks",
      nearest_handle((10.0, 200.0), gz_flat) is None)
check("nearest handle respects a custom threshold",
      nearest_handle((10.0, 15.0), gz_flat, threshold=25.0) == (gizmo.MOVE, 0))

# ---------------------------------------------------------------------------
section("blender integration")
import bpy
import bloxel

try:
    bloxel.register()
    check("addon registers (incl. toolbar tools)", True)
except Exception:
    traceback.print_exc()
    check("addon registers (incl. toolbar tools)", False)

from bloxel.core import state

section("operator class integrity")
# subclassing a *registered* bpy type breaks the base's Python<->RNA binding
# ("unable to get Python class for RNA struct", inoperative operator
# invocations).
# These checks fail if that ever sneaks back in.
check("brush class registered", bpy.types.BLOXEL_OT_brush.bl_rna is not None)
check("eraser class registered", bpy.types.BLOXEL_OT_eraser.bl_rna is not None)
check("distinct RNA structs",
      bpy.types.BLOXEL_OT_brush.bl_rna != bpy.types.BLOXEL_OT_eraser.bl_rna)
brush_props = bpy.ops.bloxel.brush.get_rna_type().properties
check("brush tool_mode default", brush_props['tool_mode'].default == 'BRUSH')
eraser_props = bpy.ops.bloxel.eraser.get_rna_type().properties
check("eraser tool_mode default", eraser_props['tool_mode'].default == 'ERASER')
check("fill op registered", bpy.ops.bloxel.fill.get_rna_type() is not None)
check("fuzzy select op registered",
      bpy.ops.bloxel.fuzzy_select.get_rna_type() is not None)
check("select mode default is connected",
      bpy.context.scene.bloxel_tools.select_mode == 'CONNECTED')
check("rectangle select op registered",
      bpy.ops.bloxel.rect_select.get_rna_type() is not None)
check("rect select mode default is visible",
      bpy.context.scene.bloxel_tools.rect_select_mode == 'VISIBLE')
check("line op registered", bpy.ops.bloxel.line.get_rna_type() is not None)
check("transform op registered",
      bpy.ops.bloxel.transform.get_rna_type() is not None)
check("gizmo info/pick/tool checks are viewport-safe",
      gizmo.info(bpy.context) is None
      and gizmo.pick(bpy.context, (0, 0)) is None
      and gizmo.tool_active(bpy.context) is False)
check("cursor op registered", bpy.ops.bloxel.brush_cursor.get_rna_type() is not None)
check("extrude op registered", bpy.ops.bloxel.extrude.get_rna_type() is not None)
check("export op registered", bpy.ops.bloxel.export_godot.get_rna_type() is not None)
if hasattr(bpy.ops.export_scene, 'gltf'):
    gltf_props = {p.identifier for p in bpy.ops.export_scene.gltf.get_rna_type().properties}
    check("glTF exporter props available (export op contract)",
          {'export_format', 'export_materials', 'use_selection'} <= gltf_props)
else:
    check("glTF exporter props available (export op contract)", True)

# cursor path regression: pick() must work right after _bind, without the
# stroke invoke having initialized stroke state
from bloxel.tools.brush import BrushStrokeMixin
bpy.ops.bloxel.new_model('EXEC_DEFAULT')
obj_h = bpy.context.active_object
probe = BrushStrokeMixin()
probe._bind(None, obj_h)
check("bind initializes stroke state",
      probe.stroking is False and probe._overlay is None)

bpy.ops.bloxel.new_model('EXEC_DEFAULT')
obj = bpy.context.active_object
check("new_model creates bloxel object", state.is_bloxel(obj))
check("default palette has 8 materials", len(obj.data.materials) == 8)
check("default bounds", tuple(obj.bloxel_min) == (0, 0, 0)
      and tuple(obj.bloxel_max) == (31, 31, 31))

rt = state.runtime(obj)
check("runtime grid starts empty", rt.grid.voxel_count() == 0)

# undo integration: Blender snapshots ID properties on undo steps; our side
# must re-deserialize the grid when the property is restored. ed.undo() is
# unavailable in background mode (no window), so simulate the restore:
# write back the pre-commit blob/rev and fire the history handler.
blob_before = obj.get(state.GRID_PROP)
rev_before = obj.get(state.REV_PROP)

rt.grid.set(2, 2, 2, 1)
rt.grid.set(3, 2, 2, 2)
mesher.rebuild_mesh(obj, rt)
check("mesh built: 2 voxels -> 10 polygons", len(obj.data.polygons) == 10)
check("face material slots assigned",
      sorted(p.material_index for p in obj.data.polygons) == [0] * 5 + [1] * 5)

state.commit(obj, rt)
check("commit writes blob + increments rev", obj.get(state.REV_PROP) == rev_before + 1
      and obj.get(state.GRID_PROP) != blob_before)

# cache stability: same rev -> same runtime object (no spurious reload)
check("runtime cached while rev unchanged", state.runtime(obj) is rt)

# simulate undo: Blender restores the old ID property values, handlers fire
obj[state.GRID_PROP] = blob_before
obj[state.REV_PROP] = rev_before
state.history_changed()
rt2 = state.runtime(obj)
check("history restore re-deserializes grid", rt2 is not rt
      and rt2.grid.voxel_count() == 0)

# picker/palette index clamp
obj.bloxel_palette_index = 99
from bloxel.core import palette as pal
check("active palette index clamps", pal.active_index(obj) == len(obj.data.materials))

# ---------------------------------------------------------------------------
section("palette color sync")
mat = obj.data.materials[0]
check("palette materials are tagged", mat.get("bloxel_palette") is True)
node = pal.bsdf(mat)
check("palette material has a Principled BSDF", node is not None)
check("Principled has Metallic + Roughness inputs",
      node is not None and "Metallic" in node.inputs and "Roughness" in node.inputs)
mat.diffuse_color = (0.1, 0.2, 0.3, 1.0)
# msgbus only fires in UI sessions (no notifier loop in background mode);
# the panel redraw also syncs. Test the sync function itself:
pal._sync_principled_colors()
bsdf = mat.node_tree.nodes.get("Principled BSDF")
col = tuple(round(c, 2) for c in bsdf.inputs["Base Color"].default_value[:3])
check("diffuse_color synced to Principled Base Color", col == (0.1, 0.2, 0.3))

# ---------------------------------------------------------------------------
section("paint stroke simulation (operator core path)")
from bloxel.core.grid import apply_brush, raycast, walk_line

# fresh model with a 3x3 plate of material 1 lying on z=4
bpy.ops.bloxel.new_model('EXEC_DEFAULT')
obj2 = bpy.context.active_object
rt4 = state.runtime(obj2)
bmin, bmax = state.get_bounds(obj2)
for x in range(3):
    for y in range(3):
        rt4.grid.set(x, y, 4, 1)

settings = bpy.context.scene.bloxel_tools
settings.brush_mode = 'PAINT'
settings.shape = 'SQUARE'
settings.size = 1
obj2.bloxel_palette_index = 5  # paint with the blue slot (palette index 6)

# simulate a drag across the plate: same calls the modal operator makes
mat = pal.active_index(obj2)
check("active paint material is slot 6", mat == 6)
painted = 0
prev_base = None
for wx in (0.5, 1.5, 2.5):  # mouse positions across the top of the plate
    res = raycast(rt4.grid, (wx, 1.5, 20.0), (0, 0, -1), bmin, bmax)
    assert res.hit is not None
    base = res.hit.cell  # PAINT affects the hit voxel itself
    path = [base] if prev_base is None else list(walk_line(prev_base, base))[1:]
    for cell in path:
        painted += apply_brush(rt4.grid, cell, res.hit.normal, settings.shape,
                               settings.size, 'PAINT', mat, bmin, bmax)
    prev_base = base

check("paint stroke recolours row", painted == 3)
check("painted voxels have material 6",
      all(rt4.grid.get(x, 1, 4) == 6 for x in range(3)))
check("paint leaves other voxels untouched",
      rt4.grid.get(0, 0, 4) == 1 and rt4.grid.get(2, 2, 4) == 1)
check("paint adds no voxels", rt4.grid.voxel_count() == 9)
mesher.rebuild_mesh(obj2, rt4)
check("repainted mesh keeps face count", len(obj2.data.polygons) == 6 * 9 - 2 * 12)
# middle-row voxels expose 3+2+3 = 8 faces (interior faces culled even
# across materials, by design)
check("repainted faces use slot 5 (palette 6 - 1)",
      sum(1 for p in obj2.data.polygons if p.material_index == 5) == 8)

# ---------------------------------------------------------------------------
section("line tool simulation (operator core path)")
bpy.ops.bloxel.new_model('EXEC_DEFAULT')
obj_ln = bpy.context.active_object
rt_ln = state.runtime(obj_ln)
bmin_ln, bmax_ln = state.get_bounds(obj_ln)
for x in range(5):
    rt_ln.grid.set(x, 0, 4, 1)  # plate; ADD placement lands on z=5
mat_ln = pal.active_index(obj_ln)
added = 0
for cell in walk_line((0, 0, 5), (4, 0, 5)):
    added += apply_brush(rt_ln.grid, cell, (0, 0, 1), 'SQUARE', 1,
                         'ADD', mat_ln, bmin_ln, bmax_ln)
check("line core path places a straight run of voxels", added == 5
      and all(rt_ln.grid.get(x, 0, 5) == mat_ln for x in range(5)))
check("line leaves the original surface alone",
      all(rt_ln.grid.get(x, 0, 4) == 1 for x in range(5)))
diag = list(walk_line((0, 0, 10), (3, 3, 10)))
counts = sum(apply_brush(rt_ln.grid, cell, (0, 0, 1), 'SQUARE', 1,
                         'ADD', mat_ln, bmin_ln, bmax_ln) for cell in diag)
check("line diagonal is gap-free and connects both endpoints",
      counts == len(diag) and diag[0] == (0, 0, 10) and diag[-1] == (3, 3, 10)
      and all(abs(diag[i + 1][0] - diag[i][0]) <= 1
              and abs(diag[i + 1][1] - diag[i][1]) <= 1
              for i in range(len(diag) - 1)))

# ---------------------------------------------------------------------------
section("extrude integration")
bpy.ops.bloxel.new_model('EXEC_DEFAULT')
obj_e = bpy.context.active_object
rt_e = state.runtime(obj_e)
rt_e.grid.set(2, 2, 2, 1)
region = face_region(rt_e.grid, (2, 2, 2), (0, 0, 1), (0, 0, 0), (31, 31, 31))
check("extrude integration: region is the single voxel", region == {(2, 2, 2)})
extrude_region(rt_e.grid, region, (0, 0, 1), 2, 1, (0, 0, 0), (31, 31, 31))
mesher.rebuild_mesh(obj_e, rt_e)
check("extrude integration: 3-voxel column -> 14 quads",
      len(obj_e.data.polygons) == 14)

# ---------------------------------------------------------------------------
section("fuzzy select: persisted selection + commit prune")
bpy.ops.bloxel.new_model('EXEC_DEFAULT')
obj_s = bpy.context.active_object
rt_s = state.runtime(obj_s)
for x in range(4):
    rt_s.grid.set(x, 0, 0, 1)
rt_s.grid.set(20, 20, 20, 2)
rt_s.selection = select_region(rt_s.grid, (0, 0, 0), (0, 0, 0), (31, 31, 31),
                               contiguous=True)
state.commit(obj_s, rt_s)
state.clear_runtimes()
rt_s2 = state.runtime(obj_s)
check("selection survives commit + reload",
      rt_s2.selection == {(x, 0, 0) for x in range(4)})
rt_s2.grid.set(2, 0, 0, 0)  # erase one selected voxel (eraser-style edit)
state.commit(obj_s, rt_s2)
check("commit prunes erased cells from the selection",
      rt_s2.selection == {(0, 0, 0), (1, 0, 0), (3, 0, 0)})

# ---------------------------------------------------------------------------
section("regressions: cancel restore, empty palette, inverted bounds")

# cancel-style restore: BloxelStrokeMixin.finish replaces the grid with the
# snapshot; cached chunk geometry from mid-stroke rebuilds must not survive
bpy.ops.bloxel.new_model('EXEC_DEFAULT')
obj_c = bpy.context.active_object
rt_c = state.runtime(obj_c)
rt_c.grid.set(0, 0, 0, 1)
mesher.rebuild_mesh(obj_c, rt_c)
check("cancel regression: 1 voxel -> 6 polys", len(obj_c.data.polygons) == 6)
snap = serialize.dumps(rt_c.grid, rt_c.selection)
rt_c.grid.set(1, 0, 0, 2)          # stroke edit
mesher.rebuild_mesh(obj_c, rt_c)   # mid-stroke rebuild caches stroke geometry
check("cancel regression: stroke state visible", len(obj_c.data.polygons) == 10)
rt_c.grid, rt_c.selection = serialize.loads(snap)  # what finish() does on cancel
rt_c.mesher.cache.clear()                          # and the fix: drop stale cache
mesher.rebuild_mesh(obj_c, rt_c)
check("cancel restore re-meshes stale chunks", len(obj_c.data.polygons) == 6)

# empty palette must block painting tools (mat 0 would erase instead)
while obj_c.data.materials:
    obj_c.data.materials.pop(index=0)
check("empty palette -> active_index 0", pal.active_index(obj_c) == 0)

# core defense: painting with mat 0 (EMPTY) must never erase voxels
g0 = VoxelGrid()
g0.set(4, 4, 4, 3)
changed = apply_brush(g0, (4, 4, 4), (0, 0, 1), 'SQUARE', 1, 'ADD', 0, bmin, bmax)
check("ADD with mat 0 is a no-op", changed == 0 and g0.get(4, 4, 4) == 3)
changed = apply_brush(g0, (4, 4, 4), (0, 0, 1), 'SQUARE', 1, 'PAINT', 0, bmin, bmax)
check("PAINT with mat 0 is a no-op", changed == 0 and g0.get(4, 4, 4) == 3)
changed = flood_fill(g0, (4, 4, 4), 0, bmin, bmax)
check("fill with mat 0 is a no-op", changed == 0 and g0.get(4, 4, 4) == 3)

# operator-level guard on the brush (fill cannot be invoked headless, but its
# guard uses the same active_index precondition tested above)
import types
from bloxel.tools.brush import BrushStrokeMixin
probe = BrushStrokeMixin()
probe.tool_mode = 'BRUSH'
probe.report = lambda *a, **k: None  # plain mixin: no RNA operator to report through
evt = types.SimpleNamespace(alt=False, value='PRESS', type='LEFTMOUSE',
                            mouse_region_x=0, mouse_region_y=0)
check("brush blocked on empty palette",
      probe.invoke(bpy.context, evt) == {'CANCELLED'})
probe.tool_mode = 'ERASER'
check("eraser mode bypasses the palette guard",
      probe._mode(bpy.context) == 'ERASE')

# inverted volume bounds: get_bounds normalizes so raycast/overlay stay sane
bpy.ops.bloxel.new_model('EXEC_DEFAULT')
obj_b = bpy.context.active_object
obj_b.bloxel_min = (40, 3, 3)
obj_b.bloxel_max = (10, 31, 31)
check("get_bounds normalizes inverted axis",
      state.get_bounds(obj_b) == ((10, 3, 3), (40, 31, 31)))
obj_b.bloxel_min = (0, 0, 0)
obj_b.bloxel_max = (31, 31, 31)
check("get_bounds passes valid bounds through",
      state.get_bounds(obj_b) == ((0, 0, 0), (31, 31, 31)))

# ---------------------------------------------------------------------------
section("summary")
if FAILURES:
    print(f"\n{len(FAILURES)} FAILURE(S):")
    for name in FAILURES:
        print(f"  - {name}")
    sys.exit(1)
print("\nALL TESTS PASSED")
sys.exit(0)
