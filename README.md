# Folio Draw

A quick, uncluttered picture editor for Zorin OS and Ubuntu, in the spirit of the classic desktop
paint program — with layers, blend modes and real transparency. Part of Folio Studio.

It also turns pictures into machine embroidery, which is what the Embroidery tab is for.

## What it does

- **Tools**: pencil, brushes (brush, calligraphy, airbrush, marker), eraser, fill, colour picker,
  magnifier, text, and shapes — line, curve, rectangle, oval, polygon — filled or outlined.
- **Selections**: rectangle, free-form and magic wand; Shift adds, Alt takes away; move, copy,
  transparent selection, crop to the selection.
- **Layers**: add, duplicate, reorder, merge down, flatten; opacity and eight blend modes; text
  stays on its own layer and can be typed again.
- **The picture**: resize, canvas size, rotate by any angle, flip, skew, invert, and adjustments
  for brightness and contrast, hue and saturation, greyscale, sepia, blur and sharpen.
- **Animation**: an animated GIF or WebP opens with one frame per layer; the frames view steps
  through them or plays them.
- **Files**: PNG, JPEG, BMP, GIF, WebP, TIFF, Windows icons, Photoshop PSD and OpenRaster
  (`.ora`, which keeps the layers). Every codec is written here, with no image library.
- **Embroidery**: start a design the size of a hoop, place a picture and convert it to shapes,
  set each shape's thread colour and stitch settings, look at the planned stitches, and save for
  the machine as PES, DST, JEF, EXP, VP3, XXX or PEC. Lettering, envelopes and the density view
  are there too. Made for the Brother Skitch PP1 and Artspira, and usable with any of the above.

## Layout

| Folder | What's in it |
| --- | --- |
| `folio_draw` | the interface, in Python with GTK 3 |
| `engine` | the engine, in Rust (about 20,000 lines) with no third-party crates: layers, brushes, selection, undo, every image codec, and the embroidery planner |
| `data` | icons, thread charts, templates |
| `tests` | the audits (ui, tools, dialogs, embroidery, themes) |
| `tools` | build and release scripts |

A Rust version of the interface is being written in the `folio-cork` workspace (`folio-draw`),
on Folio's portable base. This GTK version ships until that one passes these tests.

## Building and testing

```sh
cd engine && cargo test --release && cargo build --release
sh build-deb.sh out/                    # the package
python3 tests/ui_audit.py               # the interface
python3 tests/emb_audit.py              # embroidery
sh tests/theme_run.sh                   # desktop themes (X2-01)
```

Needs python3-gi, GTK 3 and Cairo.
