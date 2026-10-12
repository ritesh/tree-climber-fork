# Fix Python call extraction in nested bodies (2026-10-12)

Tracks GitHub issue #21.

## Problem

`PythonCFGVisitor.get_calls` walked the whole subtree, including the bodies of nested `def` and `class` statements. A `def` below module level is one opaque statement (since #7), and so is a `class` or decorated function, so such a node got call and return edges to every function called anywhere inside it:

```python
def helper(): ...
class A:
    def m(self):
        helper()      # the `class A` statement was linked to helper
```

Defining the class or function does not call `helper`; only calling `m` does. The def/use extractor already stopped at these boundaries, so the two disagreed.

## Design

Count only calls that run when the node executes:

- **`def`:** the body does not run at definition time, so it is skipped. Decorators (children of the enclosing `decorated_definition`), default values, and annotations are evaluated then, so they count.
- **`class`:** the body *does* run at definition time (`x = compute()` at class level is a real call), so it counts, minus its methods' bodies, which the `def` rule skips.
- **`lambda`:** the body counts. The issue suggested excluding it because the call happens when the lambda is called, but a lambda usually runs during the statement that creates it (`sorted(xs, key=lambda x: f(x))`), and dropping those calls loses real interprocedural edges. This matches the def/use extractor, which also counts lambda bodies.

Implemented as an explicit traversal that omits only a function's `body`, replacing the generic `dfs`; call order is unchanged.

## Not changed

When #10 gives nested functions and classes their own graphs, their bodies are visited as separate CFGs, so this boundary stays correct.

## Tests

`test_python_cfg.py::TestCallsThatRunWhenTheNodeRuns`: table-driven `get_calls` cases (function and nested function bodies, decorators, defaults, class bodies with and without methods, lambdas, comprehensions) and CFG-level checks that no call/return edge is created for a class or decorated function, that class-level code does link, and that a real call still links.

## Results

Executive summary: call extraction follows what actually runs. CI-equivalent checks pass locally (`ruff format --check`, `ruff check`, `pyright`, `pytest`: 329 passed, 20 xfailed; was 316). No existing test depended on the old behavior.

- 13 new tests; mutation-checked with 5 deliberate bugs (function bodies counted again, class bodies skipped, lambda bodies skipped, definition-time parts of a `def` skipped, call order changed), each applied and each caught.
