# Bloxel Add-on

Bloxel Add-on is a voxel modeling add-on for Blender.

## Requirements

- Blender 5.0 or later.

## Install

1. Download `bloxel-0.1.0.zip`. See Build to create the package.
2. Open Blender.
3. Select `Edit > Preferences > Add-ons`.
4. Select the dropdown at the top right.
5. Select `Install from Disk...`.
6. Select `bloxel-0.1.0.zip`.
7. Enable `Bloxel` in the add-on list.

## Quick start

1. Open the 3D viewport.
2. Open the sidebar. Select the `Bloxel` tab.
3. Select `New Bloxel Model`. Bloxel creates a model with a working volume
   and a palette.
4. Select the `Voxel Brush` tool in the toolbar.
5. Click in the viewport to add a voxel. Drag to add a stroke of voxels.
6. Select `Export to Godot (glTF)` to write the model to a `.glb` file.

## Tools

Select a tool in the 3D viewport toolbar. The sidebar shows the settings for
the active tool.

| Tool | Purpose | Notes |
|---|---|---|
| Voxel Brush | Add or paint voxels | `Alt+LMB` picks a material. Size, shape, and mirror options apply. |
| Voxel Eraser | Remove voxels | Size, shape, and mirror options apply. |
| Voxel Line | Draw a straight line of voxels | Drag from the start voxel to the end voxel. |
| Voxel Fill | Fill a region with the active material | Contiguous or global mode. |
| Voxel Fuzzy Select | Select the region of the clicked voxel | Connected or material mode. `Shift` adds. `Ctrl` removes. |
| Voxel Rectangle Select | Select the voxels in a screen rectangle | Visible-only or strikethrough mode. `Shift` adds. `Ctrl` removes. |
| Voxel Move & Rotate | Move or rotate the selected voxels | Drag an arrow to move. Drag a ring to rotate in 90-degree steps. |
| Voxel Extrude | Pull coplanar same-material faces outward | Drag farther to add more layers. |
| Voxel Picker | Set the active palette slot | Bloxel reads the material of the clicked voxel. |

The Move & Rotate gizmo uses Blender axis colors: X red, Y green, Z blue.
Right mouse or `Escape` cancels a drag.

## Copy and paste

- `Ctrl+C` copies the selected voxels. On macOS, use `Cmd+C`.
- `Ctrl+V` writes the copied voxels at their original position. On macOS,
  use `Cmd+V`.
- Bloxel selects the pasted voxels and activates the Voxel Move & Rotate
  tool. Drag the gizmo to move the pasted voxels.
- The shortcuts work while a Bloxel tool is active in the 3D viewport.

## Working volume

- `Min` and `Max` define the editable cell range on each axis.
- The default volume is 32 x 32 x 32 cells.
- Tools clamp edits to the volume. Bloxel drops cells outside the volume.

## Palette

- Each model owns a palette of Blender materials.
- A new model starts with 8 materials.
- Select `Add` to append a material.
- The panel edits the viewport color. Bloxel syncs the Principled Base Color
  to the viewport color, so renders match the viewport.

## Export

- `Export to Godot (glTF)` writes the selected models to a `.glb` file.
- The file includes the model materials.
- Blender opens its glTF export dialog for the export options.

## Data model

- Voxels live in a sparse grid of 32 x 32 x 32 chunks.
- Bloxel serializes the grid and the selection into a compressed blob.
- The blob lives in an ID property on the object.
- Undo, redo, load, and save restore the blob, so Bloxel needs no custom
  undo system.

## Development

Project layout:

```
core/    grid, mesher, serialization, runtime state, drawing, palette, gizmo
tools/   modal viewport tools (brush, eraser, line, fill, select, transform, extrude, picker)
ops/     non-modal operators (new model, palette, copy/paste, export)
ui/      sidebar panel
tests/   headless test suite
```

Run the test suite:

```
blender --background --factory-startup --python tests/run.py
```

The suite prints `PASS` or `FAIL` for each check. The process exits with
code 1 after a failure.

Build the extension package:

```
blender --command extension build --source-dir . --output-dir dist
blender --command extension validate dist/bloxel-0.1.0.zip
```

The build writes `dist/bloxel-0.1.0.zip`.

## License

Bloxel uses the GPL-3.0-or-later license. See `LICENSE`.
