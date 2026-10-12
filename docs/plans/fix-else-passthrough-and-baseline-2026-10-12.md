# Fix "else" passthrough bug and restore green baseline (2026-10-12)

Tracks GitHub issues #3 (bug) and #2 (baseline), prerequisites for Python support (#1).

## #3: passthrough removes nodes by source-text substring

`CFGVisitor._passthrough_entry_exit_nodes` (`src/tree_climber/cfg/visitor.py`) selects nodes to splice out using `NodeType` plus text checks: `"else" in source_text.lower()`, `startswith("CASE:")`, `== "DEFAULT"`.

Findings:
- No visitor creates a node for the `else` keyword (it is an unnamed token and `generic_visit` skips it), so the `"else"` check can only match user statements. `int elsewhere = a;` is deleted from the CFG.
- Every case/default node is already created with `NodeType.CASE`; `NodeType.DEFAULT` is unused. ENTRY/EXIT helper nodes already carry `NodeType.ENTRY`/`EXIT`.

Plan:
1. Add regression tests (C and Java) that build CFGs containing identifiers/strings with `else`, `CASE:`, `DEFAULT`, and assert the statements survive. Confirm they fail first.
2. Select passthrough nodes by `NodeType` only (ENTRY, EXIT, CASE, DEFAULT), excluding function entry/exit as today.
3. Run the full suite to confirm existing CFG expectations are unchanged.

## #2: baseline

Target is what `.github/workflows/ci.yml` runs: `ruff format --check .`, `ruff check .`, `pyright`, `pytest`, plus the frontend build.

Plan, in order of risk:
1. `ruff check --fix`, then hand-fix the remainder.
2. Repair `test/dfg/` (stale imports first, then triage the remaining failures: fix tests that drifted, fix code if the test exposes a real bug).
3. pyright errors in `src/` first, then `test/`.
4. Make `viz/test_api.py` use FastAPI `TestClient` so it needs no live server.
5. Fix or delete stale `test/oneoff/` scripts.
6. Frontend `tsc -b` errors in `Graph.tsx`.

## Results

Executive summary: CI-equivalent checks are green (`ruff format --check`, `ruff check`, `pyright`, `pytest`, frontend `tsc -b` and `vite build`). `pytest`: 99 passed, 28 strict xfails.

### #3
Passthrough nodes are now selected by `NodeType` only. Regression tests added for C and Java. No existing CFG expectations changed.

### #2
- Lint/types: 55 ruff findings and 22 pyright errors resolved. One stale debug script (`test/oneoff/debug_java_simple_if.py`) deleted because both its import path and its sample directory no longer exist.
- Two real analysis bugs found while repairing the DFG tests and fixed with a regression test (C and Java): an identifier used as an initializer (`int y = x;`) or as the value of an assignment (`y = x;`) was not recorded as a use, because the rules skipped identifiers by parent node type instead of by field. This silently dropped def-use chains.
- `test/dfg/` repaired: stale imports, a `test.dfg` import that could not resolve, tests calling a fixture function as an object, and a use-def lookup comparing text against a node id.
- 28 DFG tests are marked `xfail(strict=True)`, verified with `--runxfail` to fail only for the stated reason:
  - 20 assert interprocedural parameter aliasing, deliberately deferred to vNext in commit 77acb86 and TODO.md.
  - 8 (`TestIncrementOperators`) assert that `a++` is a def-use self-reference outside loops. The fixpoint solver (cff4844) correctly does not produce that. Whether this convention should be reinstated is an open design decision.
- `viz/test_api.py` moved to `test/viz/` and rewritten to call the endpoint coroutines directly, so it needs no live server and no new dependency (`TestClient` would require `httpx`).
- Frontend: `Graph.tsx` collection call simplified; type stub for `cytoscape-node-html-label` split into a module augmentation file and an ambient module declaration.

### Noticed, not changed
- CLI `--help` examples use hyphenated flags (`--draw-cfg`) but the real options are `--draw_cfg`, `--draw_dfg`, `--draw_cpg`.
- `.claude/settings.json` runs a bare `ruff format` after every Edit/Write, which reformats unrelated files (including code blocks in markdown) with a different ruff version than the project's.
