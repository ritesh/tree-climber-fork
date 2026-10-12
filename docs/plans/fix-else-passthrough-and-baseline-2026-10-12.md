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

To be filled in when the work is done.
