# Fix AssertionError on a program with nothing to analyze (2026-10-12)

Tracks GitHub issue #27.

## Problem

`CCFGVisitor.visit_translation_unit` and `JavaCFGVisitor.visit_program` asserted that at least one function (C) or class (Java) was found. The assert fires for far more than the empty string in the issue:

| Input | Result before |
|---|---|
| C: empty file, only comments | `AssertionError: Translation unit must have at least one entry node` |
| C: only declarations (a typical header: `int x; struct S {...};`) | same |
| Java: empty file, or only `package`/`import` lines | same |

In the web app, clearing the editor (or switching language with an empty buffer) returned `success: false` with that message instead of an empty graph.

## Design

A program with no functions or classes has an empty CFG: no nodes, no entry or exit ids. The two root visits return `None` instead of asserting, as `visit_comment` already does for ignorable nodes; `CFGBuilder` does not use the root visit's result. Python is unchanged: an empty module keeps its `<module>` ENTRY/EXIT pair because a module always has top-level flow.

I did not give C and Java a placeholder ENTRY/EXIT pair: there is no function or class for it to belong to.

## Checked downstream, not assumed

An empty CFG now reaches the dataflow solvers, the API, and every CLI renderer. I ran all of them: `RoundRobinSolver` with reaching definitions, def-use and use-def solvers; `POST /parse`-style handler; and the CLI with `--draw_ast/cfg/dfg/cpg` on five empty-ish files (20 combinations). All succeed. The frontend only declares `entry_node_ids`/`exit_node_ids` as types and does not index into them.

## Tests

`test/test_empty_program.py` (24 tests): empty CFG for each input above; solvers accept it; the API returns an empty graph with `success: true`; Python keeps its module flow; declarations or imports around real code do not hide it; and the CLI handles empty files.

## Results

Executive summary: empty and declaration-only C and Java inputs build an empty CFG. CI-equivalent checks pass locally (`ruff format --check`, `ruff check`, `pyright`, `pytest`: 340 passed, 20 xfailed; was 316).

- 24 new tests; 21 of them fail against the old code (the other 3 are Python and regression cases). Re-adding either assert is caught. Two further mutations (the visit returning `None` even when functions exist) are equivalent, because the builder ignores the root visit's result, so no test can distinguish them.
