# Compute data flow once and share it (#84), 2026-10-17

## Problem
`taint.analyze` builds a `_Program`, which solves reaching definitions and def-use chains, runs `analyze_interprocedural`, and with `implicit_flows` computes `control_dependence`. `CodeGraph` computes the same things, lazily and cached, but neither passes its results to the other. So:
- `/parse` solves data flow, then `/taint` builds a new CFG and solves it again for the same text;
- `tree-climber taint --draw-dfg` solves it once for the findings and once for the drawing;
- the stress runner's `taint` and `taint-precise` stages each redo what its `dataflow`, `interprocedural` and `control` stages just did.

On ordinary files this is about half of taint's time.

## Plan
- **`CodeGraph` exposes its cached analyses** as read-only properties:
  - `reaching_definitions`;
  - `def_use_chains`;
  - `interprocedural_flows` (the `analyze_interprocedural` result, from which `interprocedural_edges` are now built);
  - `control_dependence`.
  
  The private caches use them.
- **`analyze` accepts a `CodeGraph` or a CFG.** A CFG is wrapped in a new `CodeGraph`, so existing callers keep working. `_Program` reads the four analyses from the graph instead of solving them. It only reads them, building its own dictionaries.
- **The API** keeps a small LRU cache of `CodeGraph`s keyed by language and source text, so `/parse`, `/taint` and `/query` on the same text share one CFG and one data flow. `/parse` reads its def-use chains from the graph. Node ids already match between the endpoints; with the cache, the CFG is the same object.
- **The CLI's `taint`** builds one `CodeGraph` for the findings and the DFG drawing.
- **The stress runner** keeps one `CodeGraph` per file across stages. Each stage then times only its own work: `taint` no longer includes the data flow that the `dataflow` stage computed.

## Tests
- `analyze` on a `CodeGraph` gives the same findings as on its CFG, with and without `implicit_flows`, on the taint corpus.
- `analyze` on a prepared graph does not solve reaching definitions, interprocedural flows or control dependence again (spies on the solvers).
- The graph's analyses are not changed by `analyze`.
- The API returns the same graph object for the same text and language, and a different one when either changes. `/taint` after `/parse` does not rebuild the CFG.
- The CLI's `taint --draw-dfg` solves data flow once.
- Stress: the stages share the work's graph.

## Measure
`analyze` time on `test_typing.py` and `unicodeobject.c` with a fresh CFG against a graph that `/parse` already analysed. The stress runner's taint stages on CPython `Lib`, before and after.

## Results
Executive summary: the data flow is now solved once per graph and shared. `analyze` accepts a `CodeGraph` and reads its reaching definitions, def-use chains, interprocedural flows and control dependence instead of solving them again. On CPython `Lib`, the stress runner's taint stages take 25 s and 26 s instead of 40 s and 45 s. The API shares one graph per text between `/parse`, `/taint` and `/query`, and the CLI's `taint --draw-dfg` solves data flow once.

| Stress runner, CPython `Lib` (1,790 files, 3 workers, stage seconds summed) | master | this branch |
|---|---|---|
| dataflow | 12.4 s | 10.8 s |
| interprocedural | 4.5 s | 5.0 s |
| control | 3.9 s | 3.7 s |
| taint | 39.6 s | **24.9 s** |
| taint-precise | 44.6 s | **26.0 s** |

Taint on a fresh CFG, against taint on a graph whose data flow `/parse` has already solved:

| File | On a CFG | On an analysed graph | Data flow, solved once |
|---|---|---|---|
| `Lib/test/test_typing.py` | 0.73 s | 0.48 s | 0.28 s |
| `Objects/unicodeobject.c` | 0.85 s | 0.21 s | 0.45 s |
| `Modules/posixmodule.c` | 0.29 s | 0.09 s | 0.30 s |

What remains is mostly source discovery and the runs themselves (#85 and #87).

- **`CodeGraph`.** `reaching_definitions`, `def_use_chains`, `interprocedural_flows` and `control_dependence` are public cached properties. `interprocedural_edges` is built from the cached flows: `interprocedural_edges(cfg, flows)` takes them optionally.
- **Taint.** `analyze(code, ...)` takes a CFG or a `CodeGraph`; a CFG is wrapped in a new graph. `_Program` only reads the graph's analyses and builds its own dictionaries from them. A test checks that the analyses are unchanged after a run.
- **API.** `code_graph(language, source)` is an LRU cache of 4 graphs. `/parse` builds the AST, when asked, from a separate parse, and reads its DFG from the graph's def-use chains.
- **CLI and stress.** The CLI's `taint` uses one graph for the findings and the DFG drawings. In the stress runner, `Work` holds a `CodeGraph`, and the `dataflow`, `interprocedural` and `control` stages fill its caches; `taint` and `taint-precise` reuse them. The per-stage seconds are therefore not comparable with older reports: taint no longer includes the data flow it shares.
- **Tests:**
  - a graph gives the findings of its CFG, on the taint corpus and with and without implicit flows;
  - a prepared graph is not solved again (the solvers are replaced with spies that fail);
  - the analysis leaves the graph unchanged;
  - edges are built from the cached flows;
  - the API shares one graph per text and language, and `/taint` and `/query` after `/parse` neither rebuild nor re-solve;
  - `taint --draw-dfg` solves data flow once;
  - the stress stages solve data flow once.
- **Mutation check:** 13 mutants, all caught.
- **Checks:** ruff format and lint are clean, pyright reports 0 errors, and the suite gives 2,072 passed, 39 xfailed.
