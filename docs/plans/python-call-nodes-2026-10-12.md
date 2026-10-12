# Expose Python call nodes (2026-10-12)

Preparation for the taint-tracking epic (#44), in particular structured call sites (#45). No behavior change.

## Problem
`PythonCFGVisitor.get_calls` walked the tree and returned callee names directly, so the traversal rules (what counts as a call that runs when a statement runs: decorators, defaults, class bodies and lambdas count; function bodies do not) were fused with name extraction. A call-site extractor needs the same set of calls but wants the tree-sitter `call` node itself, to read the receiver, the arguments and the surrounding assignment.

## Change
Split the traversal out as `call_nodes(ast_node)`, a generator of `call` nodes in source order (outer call before its inner calls), and make `get_calls` map it to names. Same rules, same output; the existing `get_calls` tests are the regression suite.

## Tests
`TestCallNodes` in `test_python_cfg.py`: order, an unnamed callee (`f()()`) is a call node but not a name, arguments and callee reachable from the node, definition-time calls counted and function bodies skipped, lambdas and comprehensions counted, and `get_calls` equals the named call nodes. Mutation-checked with 4 deliberate bugs (body not skipped, order reversed, nothing yielded, unnamed callees kept); all caught.

## Results
Pure refactor plus tests. `ruff format --check`, `ruff check`, `pyright`, `pytest` pass (586 passed, 20 strict xfails).
