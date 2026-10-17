# Worklist data-flow solver (#82), 2026-10-17

## Problem
`RoundRobinSolver` re-evaluates every node of the file on every pass, until no OUT set changes anywhere, so one awkward function makes the whole file pay for many passes. `Objects/unicodeobject.c` needs 53 passes over 8,490 nodes, and reaching definitions take 4.2 s. Each transfer also builds new gen facts, so set operations compare facts by value (7M `__eq__` calls) instead of by identity. Taint pays the same cost again.

## Plan
- **`WorklistSolver`** in `dataflow/solver.py`, with the same `solve(cfg, problem)` interface and the same `DataflowProblem`:
  - filter the predecessors and successors once, leaving out call and return edges as now;
  - seed the worklist with every node in reverse postorder (from the nodes with no predecessors, then any node not yet reached), so each node is evaluated at least once, as in round robin;
  - when a node's OUT set changes, queue those of its successors that are not already queued.
  
  For a monotone problem the fixpoint is the same as round robin's.
- **Reaching definitions transfer**: build each node's gen facts once and reuse them, so that facts compare by identity. Skip the kill scan when the node defines nothing. The cache is checked against the node object, so a problem reused on another CFG cannot see stale facts.
- **Make it the default** everywhere the code base solves data flow: `CodeGraph`, taint, the CLI, the web API, the stress runner and `dataflow/main.py`. Tests that build their own reaching definitions switch too.
- **Keep `RoundRobinSolver`** as the oracle.

## Tests
- Solver unit tests: a loop that needs a second visit, unreachable nodes, call and return edges ignored, a problem whose initial OUT sets are not empty, and a result that is equal to round robin's.
- Oracle test: for every source file used as test input (C, Java and Python), the worklist and round-robin solvers give equal IN and OUT sets for every node.
- The property tests: compare the two solvers on generated programs.
- The transfer cache: the same gen objects are reused, and a different CFG with the same node ids gets its own facts.

## Measure
Reaching definitions on `unicodeobject.c`, `posixmodule.c`, `test_typing.py` and `win32con.pyi`, before and after, plus the stress runner's dataflow and taint stages on the CPython C corpus.

## Results
Executive summary: `WorklistSolver` is now the default everywhere, and `RoundRobinSolver` stays as the test oracle. Both give identical IN and OUT sets:
- on every C, Java and Python test input (95 files);
- on generated programs;
- on all four review files.

Gen facts are built once per node. Over the corpora, data flow is 2.7–3× faster and taint 2.2–2.3× faster. `unicodeobject.c` goes from 16.7 s to 3.6 s for its data-flow and taint stages.

| Stress runner, 3 workers, stage seconds summed | master | this branch |
|---|---|---|
| CPython C sources (813 files), dataflow | 23.1 s | 8.7 s |
| CPython C sources, taint | 28.0 s | 13.0 s |
| typeshed (5,478 files), dataflow | 172 s | 57 s |
| typeshed, taint | 152 s | 67 s |
| `winerror.pyi` (#70), dataflow + taint | 204 s | 72 s |

Reaching definitions alone, each solver in its own process. Timings on this container vary by up to 2× between runs, so compare within a row:

| File | master (round robin) | branch, round robin | branch, worklist |
|---|---|---|---|
| `Objects/unicodeobject.c` | 6.84 s | 3.47 s | **0.54 s** |
| `Modules/posixmodule.c` | 0.34 s | 0.26 s | 0.28 s |
| `Lib/test/test_typing.py` | 0.47 s | 0.46 s | 0.20 s |
| typeshed `win32con.pyi` | 33.4 s | 18.7 s | 15.8 s |

- **Two changes.**
  - The worklist removes the 53 whole-file passes on `unicodeobject.c`.
  - The gen-fact cache lets facts compare by identity, which halves round robin's time too.
- **Long modules (#70) are still slow.** Every node's IN set holds most module-level definitions, so copying the sets stays O(N²).
- **Smaller changes.** The `Union` meet no longer copies each predecessor set before the union; this is kept. Building OUT in one comprehension, instead of kill, difference and union, was slower on long stubs: it adds every surviving fact in Python, while the set difference copies in C. It was reverted.
- **Correctness detail.** Successors are derived from the filtered predecessors, so the worklist re-queues exactly the nodes whose meet reads a changed OUT set, even if a CFG's successor and predecessor lists ever disagree.
- **Tests.** `test/dfg/test_solver.py`:
  - the oracle over every test input file;
  - a loop, unreachable code, and call and return edges;
  - a problem with initial facts;
  - reverse postorder, including where a loop is entered;
  - the gen cache: identity, a different node with the same id, and a pass-through copy.

  `test/test_property.py` compares both solvers on Hypothesmith programs.
- **Mutation check:** 17 mutants. The first run caught 14. The new loop-entry test catches two of the three survivors. The last one removes the shortcut for nodes that define nothing; it is equivalent, since it only affects speed.
- **Checks:** ruff format and lint are clean, pyright reports 0 errors, and the suite gives 2,033 passed, 39 xfailed.
