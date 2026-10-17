# Compute data flow once (#84), 2026-10-17

## Problem
`taint.analyze` builds a `_Program`, which solves reaching definitions, def-use chains, the interprocedural flows and, with `implicit_flows`, control dependence from scratch. `CodeGraph` computes the same results lazily and caches them, but nothing passes one to the other. So:
- On `Lib/test/test_typing.py`, about half of taint's time is recomputed data flow, and on `Objects/unicodeobject.c` almost all of it.
- Each editor edit sends `/parse` and `/taint` at the same time; each builds its own CFG and solves reaching definitions.
- The CLI's `taint --dfg` solves the data flow twice, and the stress runner solves it in each stage.

## Plan
- **`CodeGraph` exposes its cached results** as read-only properties: `reaching_definitions`, `def_use_chains`, `interprocedural_flows` and `control_dependence`. Its own queries use them, and `interprocedural_edges` is built from the cached flows.
- **`taint.analyze` takes a `CFG` or a `CodeGraph`.** `_Program` reads the graph's results instead of solving; a bare CFG is wrapped in a new `CodeGraph`, so existing callers are unchanged. `analyze_source` builds a `CodeGraph`.
- **API:** `/parse`, `/taint` and `/query` share a small cache of analyses keyed by language and source, holding the parse tree and the `CodeGraph`. Each entry is built once under its own lock, def-use chains included, so the concurrent `/parse` and `/taint` of one edit wait for one build instead of doing two. The cache keeps the last 4 sources.
- **CLI:** `taint` builds one `CodeGraph`, and `--dfg` reuses its def-use chains.
- **Stress runner:** each file keeps one `CodeGraph` across stages, so a stage's time no longer includes what an earlier stage computed.
- The cached results are shared, so consumers must not mutate them; check that taint and the API only read them.

## Tests
- `analyze` on a `CodeGraph` gives the same findings as on its CFG, and solves no data flow of its own.
- `/parse` then `/taint` (and `/query`) of the same source solve reaching definitions once; concurrent `/parse` and `/taint` too. A different source is analysed afresh, and the cache keeps only the last few sources.
- The stress runner solves reaching definitions once per file across all stages.

## Measure
Taint time on `test_typing.py` and `unicodeobject.c` with a fresh CFG against a `CodeGraph` whose data flow is already solved; the time of a `/parse` plus `/taint` edit on `test_typing.py`, before and after.

## Results
Executive summary: the data flow of a source is now solved once and shared. An editor edit of `test_typing.py`, with `/parse` and `/taint` sent together, takes 3.9 s instead of 6.6 s. Taint on a `CodeGraph` whose data flow is already solved takes 0.40 s instead of 0.86 s on `test_typing.py`, and 0.06 s instead of 0.46 s on `unicodeobject.c`. `CodeGraph` exposes its cached results, `taint.analyze` takes a `CodeGraph` as well as a CFG, and the API, the CLI's `taint` and the stress runner each build one `CodeGraph` per source.

Measured in one process, with CPython 3.13.0's `Lib/test/test_typing.py` (376 KB) and `Objects/unicodeobject.c`, and the worklist solver of #82 on both sides:

| | master | this branch |
|---|---|---|
| Taint on a CFG, `test_typing.py` | 0.86 s | 0.88 s (unchanged) |
| Taint on a solved `CodeGraph`, `test_typing.py` | n/a | **0.40 s** |
| Taint on a CFG, `unicodeobject.c` | 0.46 s | 0.47 s (unchanged) |
| Taint on a solved `CodeGraph`, `unicodeobject.c` | n/a | **0.06 s** |
| An edit: `/parse` and `/taint` at once, `test_typing.py` | 6.6 s | **3.9 s** |

- **`CodeGraph`.**
  - `reaching_definitions`, `def_use_chains`, `interprocedural_flows` and `control_dependence` are public cached properties; they replace the private `_reaching`, `_def_use` and `_control`.
  - `interprocedural_edges(cfg, flows)` takes flows that were already computed.
- **Taint.** `_Program` reads the graph's results and solves nothing itself. A bare CFG is wrapped in a new `CodeGraph`, so callers that pass a CFG are unchanged, and it only reads the shared results: def-use uses are copied into its own lists, and the flows and control dependence are only iterated.
- **API.**
  - `/parse`, `/taint` and `/query` share `analysis(language, source)`, a cache of the last 4 sources holding the parse tree and the `CodeGraph`.
  - Each entry is built under its own lock, def-use chains included, so the concurrent `/parse` and `/taint` of one edit wait for one build.
  - A failed build is not kept; the next request tries again.
- **CLI.** `taint --draw-dfg` reuses the analysis's def-use chains.
- **Stress runner.** A file's stages share one `CodeGraph`, so the `dataflow`, `interprocedural` and `control` stages compute what taint then reuses, and the taint stages' times no longer include them.
- **Tests.**
  - Taint gives the same findings on a `CodeGraph` as on its CFG, and solves nothing on a solved one.
  - The cached interprocedural edges reuse the cached flows.
  - One edit (`/parse`, `/taint`, `/query`) and two concurrent requests each solve once.
  - Other sources and languages are analysed afresh; only the last 4 sources are kept; a failed build is not kept.
  - The stress stages solve each result once.
  - The CLI's drawing does not solve again.
- **Mutation check:** 10 mutants, all caught.
- **Checks:** ruff format and lint are clean, pyright reports 0 errors, and the suite gives 2,061 passed, 39 xfailed.
