# CLI drawing speed (#81), 2026-10-17

## Problem
`tree-climber Lib/json/decoder.py --draw-cfg --draw-dfg` (356 lines, 211 CFG nodes) takes about 37 s. The review (#80) blamed rasterising at `DEFAULT_DPI = 300`. Measuring again, with the DFG overlay that `--draw-dfg` adds to the CFG drawing, shows two causes:

| Step (decoder.py, CFG with DFG overlay) | Time |
|---|---|
| `dot` layout | 25–34 s |
| PNG at 300 dpi (196 × 51 inches, scaled down by cairo) | 31 s, 14 MB |
| PNG with the pixel area capped at 25 MP (50 dpi) | 2.8 s, 3 MB |
| SVG | 0.07 s |

`dot -v` shows that almost all of the layout time is in one network-simplex run: x-coordinate positioning, on 14,280 nodes (mostly virtual nodes for def-use edges that span many ranks), taking 11,323 iterations and 34 s. The `nslimit` graph attribute caps that run at `nslimit` × the number of graph nodes. With `nslimit=1` it stops after 211 iterations (0.6 s) and the whole layout takes 6 s. The drawing is also narrower (8,745 points wide instead of 14,089). The CFG alone (0.8 s) and the DFG alone (0.4 s) are not affected.

## Plan
- **`--format png|svg|pdf`** on the drawing command and on `taint`. The default stays `png`, so existing paths, docs and scripts keep working. The file extension follows the format.
- **One drawing helper** in `cli/visualizers/utils.py`, used by every visualizer and by the taint drawings:
  - set `nslimit` on the graph;
  - lay out once with `dot`;
  - for PNG, choose the dpi from the laid-out size: `DEFAULT_DPI` (300) unless the image would exceed `MAX_PNG_PIXELS` (25 MP), in which case the largest dpi under the cap;
  - render from the computed positions (`neato -n2`, which pygraphviz uses after `layout()`).
- Remove the fixed `dpi` from the visualizers' graph attributes. It only makes sense for bitmaps, and it also scaled SVG output.
- Docs: mention `--format` where the guides describe the output images.

## Tests
- `--format svg` and `--format pdf` write files with that extension, for the drawing command and for `taint --draw-cfg`. An unknown format is rejected.
- The dpi helper: a small graph gets 300 dpi; a large one gets a dpi that keeps the image under the cap.
- The drawing helper sets `nslimit` and writes a valid file.
- The existing CLI tests keep checking the `.png` defaults.

## Not in scope
SVG as the default. It would be the fastest choice, but it changes every output path that users, the guides and the guide test rely on. With the two fixes above PNG becomes fast enough, and `--format svg` is available.

## Results
Executive summary: drawing `decoder.py` with `--draw-cfg --draw-dfg` now takes 11 s instead of 67 s, and 7.6 s with `--format svg`. Two causes were fixed. The overlay layout spent 34 s in one unbounded network-simplex run, now limited by `nslimit`. PNGs were rasterised at 300 dpi whatever their size, and the dpi is now chosen to keep each image under 25 megapixels. PNG stays the default; `--format svg|pdf` is available on the drawing command and on `taint`.

| `decoder.py`, `--draw-cfg --draw-dfg` | master | this branch |
|---|---|---|
| CFG with DFG overlay | 61.6 s (32,767 × 8,629 px, scaled down by cairo) | 8.5 s (7,666 × 3,250 px, 63 dpi) |
| DFG | 5.0 s | 2.6 s |
| Whole command, `--format svg` | | 7.6 s |

- **Layout.** `draw_graph` sets `nslimit=1`, lays the graph out once with `dot`, then renders from those positions. On the overlay graph the positioning run stops after 211 iterations (0.6 s) instead of 11,323 (34 s), and the drawing is narrower (8,745 points instead of 14,089). On `test/example.c` the drawings are the same as before, apart from coordinate rounding.
- **Resolution.** `png_dpi` keeps 300 dpi unless the image would exceed `MAX_PNG_PIXELS`; otherwise it uses the largest dpi under the cap. The text in the new `decoder.py` drawing is still readable.
- **No fixed dpi in the graph attributes.** It used to scale SVG output too.
- **A test fix.** The deep-nesting CLI tests stubbed `AGraph.draw` to skip Graphviz. They now stub `AGraph.layout` as well, since drawing lays the graph out first.
- **Tests:**
  - `--format svg|pdf` for each drawing and for `taint`;
  - an unknown format is rejected;
  - `png_dpi` for a small image, a large one, one exactly at the cap and one just over it;
  - `draw_graph` for PNG and SVG, and a large drawing saved under the cap.
- **Mutation check:** 12 mutants, 11 caught. The survivor turns `<=` into `<` at the cap. It is equivalent: at exactly the cap the scaled dpi is also 300. A first run left a line dead (`image_format` passed to the finding drawings' options, which never use it for the path); it is removed.
- **Checks:** ruff format and lint are clean, pyright reports 0 errors, and the suite gives 1,938 passed, 39 xfailed.
