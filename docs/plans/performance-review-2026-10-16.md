# Architecture review for performance, 2026-10-16

## Goal
Find where time goes in the pipeline (parse, CFG, reaching definitions and def-use, interprocedural flows, control dependence, taint, the query layer, the CLI and API), and file each worthwhile improvement as a GitHub issue with its measurements, so they can be tackled one by one later. No code changes here.

## Plan
1. **Measure, by stage**: the stress runner's per-stage seconds over CPython `Lib` (Python), typeshed's slowest stubs, and CPython's C sources; the slowest files per stage.
2. **Profile the hot stages** with cProfile on a few representative files (a large ordinary module, a long stub, a large C file, a Java file), to find the functions that dominate: CFG construction (tree walks, call-site and binding extraction, caches), the solver, def-use, interprocedural flows, control dependence, taint (`_Program`, the per-origin runs), and `CodeGraph`.
3. **Read the architecture for repeated work**: what each layer recomputes that another already has (does taint rebuild the data flow? does every request reparse?), per-node AST walks, data structures (sets of fact objects, dict-of-lists), Python-level loops that could be batched.
4. **Scaling**: how time grows with file size and with the number of functions, sources and rules (synthetic inputs where the corpora do not show it).
5. **Server and CLI**: what `/parse`, `/taint` and `/query` compute per request, and repeated work across requests.
6. **Write up**: one issue per improvement, each with the measurement, the cause, a proposed change, the expected gain, and the risk; plus a summary here with the order to tackle them in.

## Results
Executive summary: the review measured every stage on three corpora and profiled the hot ones. It filed seven issues under the epic #80, each with its measurements, cause, proposal, expected gain and risk, and linked the existing #70. No code was changed. The two largest user-facing costs are not in the analysis at all:
- PNG rasterisation in the CLI: 26.8 s against 0.4 s for SVG on a 356-line file (#81).
- The web API: 4.7 s plus 3.2 s per keystroke, and a 28 MB `/parse` response, on a 9.7k-line file (#83).

In the analysis itself:
- The round-robin solver makes a whole file pay for its worst function's passes. A worklist prototype gives 14.6× on `unicodeobject.c`, with identical results (#82).
- Taint recomputes all the data flow (#84).
- Taint finds sources slowly and repeats it per rule (#85).
- CFG construction walks each node's AST four times (#86).
- Taint cost grows linearly with the number of sources on shared code (#87).

| Corpus (3 workers) | cfg | dataflow | interprocedural | control | taint | taint (precise) |
|---|---|---|---|---|---|---|
| CPython `Lib` (1,790 files) | 79 s | 14 s | 3 s | 3 s | 33 s | 38 s |
| CPython C sources (599 files) | 39 s | 13 s | 1 s | 2 s | 15 s | 16 s |
| typeshed (5,478 files) | 20 s | 81 s | 1 s | 1 s | 75 s | 81 s |

- Profiles, of `test_typing.py`, `unicodeobject.c` and a synthetic Java file:
  - **CFG:** metadata extraction is 60% of build time, and per-function scope information 24%.
  - **Data flow:** `unicodeobject.c` needs 53 passes and 7M fact comparisons, against 5 passes for the other files.
  - **Taint:** half its time on ordinary files, and 97% on `unicodeobject.c`, is recomputed data flow; `_origins` takes another 40% on ordinary files.
- Scaling:
  - Taint grows linearly with the number of sources that share code: 0.15 s at 10 sources to 0.69 s at 80, while data flow stays at 0.08 s.
  - CFG time is linear in nesting depth.
  - Reaching definitions are quadratic on long modules of distinct names (#70; the worklist gives only 1.4× there).
- Server and UI:
  - The endpoints are `async` but CPU-bound, so they block the event loop.
  - The AST JSON repeats every node's text (26 of the 28 MB).
  - The editor sends `/parse` and `/taint` on every keystroke, with no debounce.
  - `/parse` and `/taint` each build the CFG.
- No issue needed: the query layer (slices and lookups take about 10 ms once the data flow is cached), Graphviz layout itself (0.5 s), and Java (8k nodes in 1.3 s for all stages).
- Suggested order: #81, #82, #83, #84, #85, #86, #87, then #70. Quick, contained wins come first; #86 and #87 touch the most code.
