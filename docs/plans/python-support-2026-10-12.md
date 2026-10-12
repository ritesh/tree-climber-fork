# Python Support Plan (2026-10-12)

Status: milestone 1 done (2026-10-12). This file started as the sketch that opened the epic (#1) and now carries its results at the bottom. Follow-up work is tracked in the epic for graph queries and taint tracking (#44).

## Baseline (measured 2026-10-12, before any Python work)

- Build: `uv sync --dev` succeeds once `graphviz` and `graphviz-dev` are installed (needed to compile `pygraphviz`). Frontend `bun install` and `bunx vite build` succeed.
- Tests: `uv run pytest` reports 75 passed but 2 collection errors in `test/dfg/` (stale `UseDefSolver` import from `def_use`, and `from test.dfg...` import that does not resolve). With the first import fixed in a scratch copy, 36 of 42 DFG tests still fail, so that suite has drifted from the implementation.
- `src/tree_climber/viz/test_api.py` is outside `testpaths` and needs a live server on port 8001; it fails when run directly.
- CLI smoke test: `tree-climber` produces CFG and CPG PNGs for C and Java.
- CI checks currently failing on main: `ruff check` (55 findings), `pyright` (22 errors), frontend `tsc -b` (2 errors in `Graph.tsx`). `ruff format --check` passes.
- Bug found while scoping: `CFGVisitor._passthrough_entry_exit_nodes` removes every node whose text contains the substring "else". In C, `int elsewhere = a;` is deleted from the CFG. Python's `a if b else c` and `for/while ... else` make this a hard prerequisite.

## Starting point

- `tree-sitter-languages` 1.10.2 already bundles the Python grammar; no new dependency is needed.
- Languages are registered by hand in several places: `cfg/builder.py:get_visitor`, `cli/visualizers/constants.py`, `cli/source.py`, `viz/app.py`, `viz/frontend/src/LanguageSelector.tsx`, and a hardcoded `CFGBuilder("java")` in `dataflow/main.py`. The Monaco editor already receives the language id directly, and `python` is a valid Monaco id.
- New visitors subclass `CFGVisitor` and implement `get_calls`, `get_definitions`, `get_uses` plus `visit_<node_type>` handlers (see `languages/c.py`, `languages/java.py`).

## Design decisions

1. Scope of the first milestone is intraprocedural CFG plus def-use/reaching-definitions on a single module, matching C and Java after commit 77acb86.
2. A module is modeled like a Java class body or C translation unit: top-level statements form an implicit entry-to-exit flow, and each `def` gets its own ENTRY/EXIT pair.
3. Python loops have `else` clauses that run when the loop ends without `break`. This needs a dedicated edge from the loop header's false branch to the `else` block, with `break` bypassing it.
4. `try/except/else/finally`, `with`, and `match` need new handling and should reuse `NodeType` values where possible. Add new `NodeType` members only if the visualizer needs to distinguish them.
5. Def/use for Python is name-based: assignment targets (including tuple/star unpacking, annotated assignment, augmented assignment, walrus, `for` targets, `with ... as`, `except ... as`, imports, `del`) define; `global`/`nonlocal` change which scope a name belongs to.
6. Out of scope for the first milestone: interprocedural dataflow, aliasing, decorators' runtime effects, dynamic features (`exec`, `eval`, `setattr`), and type narrowing.

## Issue breakdown

See the epic for the live list and ordering. Prerequisites (baseline health, the "else" bug, language registry) come before visitor work. Visitor work is split by construct family so each issue can ship with its own fixtures and tests under `test/python_cfg/`.

## Results

Executive summary: Python is a third supported language, with CFGs and def-use / reaching-definitions for a single file, in the CLI, the HTTP API and the web UI. CI (lint, type check, tests, frontend build) runs on every pull request, and the suite grew from 75 tests at the start to 640 passed on master when this was written, with 20 strict xfails inherited from the C/Java baseline.

### What was built, by issue
| Issue | Result |
|---|---|
| #2 baseline, #3 `"else"` substring bug, #4 language registry | Green baseline; passthrough nodes are chosen by `NodeType`, never by text; one `language_registry.py` drives the builder, CLI and API |
| #5 skeleton, #6 def/use | Module and function graphs, call/return edges; name-based def/use with weak updates for attribute and subscript writes |
| #7 control flow | `if`/`elif`/`else`, `while`, `for`, `break`/`continue`, loop `else` |
| #8 exceptions | `try`/`except`/`except*`/`else`/`finally`, `raise`, `with`; exception edges leave from the state before a statement; shared `finally` |
| #9 match | One test per case, captures on the `true` edge, guards, no fall-through |
| #10 definitions | Every function and method is its own subgraph; classes, decorators; lambdas stay inline |
| #11 comprehensions, yield, async | Stay inside their statement with correct scoping; async forms share the sync handlers |
| #12 tests, wiring, docs | Fixtures, CLI/API/UI wiring, README, guide, limitations |
| #20-#27, #29, #32 | Review findings fixed or tracked: CI trigger, C/Java def/use bugs, forward call linking, CLI flags, format hook, empty programs |

### Decisions that differ from the sketch
- The `try` model is exact about *where* exceptions leave from (the state before the statement) rather than the "any statement jumps to each handler" over-approximation the sketch allowed.
- A plain module-level `def` has no statement in the module flow; decorated ones, classes and everything nested do.
- Comprehensions, lambdas, `yield` and `await` stay inside their statement.
- Calls are resolved by name only, in the whole file.

### Left open
- Closures and `global`/`nonlocal` are not connected across scopes (#42); this is the same limitation as C globals.
- Frontend lint is not clean and not in CI (#29); Java field/array writes define nothing (#32).
- Graph queries and taint tracking, which the question "how easy is it to trace user input?" opened, are the epic #44.
