# Names bound by a match pattern read the subject (#76), 2026-10-16

## Problem
A `case` pattern's names are defined by a `capture` node that reads nothing, so def-use chains, slices and taint never connect them to the subject:

```python
match input().split():
    case [verb, target]:
        os.system(verb + " " + target)   # not reported
```

The same holds for a variable subject (`match command:`): `verb` and `target` start at the capture, not at `command`.

## Plan
- The capture reads the subject. When the subject is a plain name, the capture uses that name: `match command:` gives `command: ... => match command, capture verb, target`.
- Otherwise the subject is an expression the `match` evaluates once. Re-reading it in each capture would repeat its calls (and their sinks and call edges), so the `match` head instead defines a synthetic name, `<match subject>`, that each capture of that `match` reads. It cannot clash with a Python name. It is added to the enclosing function's locals, so the interprocedural layer keeps it in its function (otherwise an unknown name is global, and two functions' matches would be connected).
- Nothing else changes: the `case` tests read only their pattern's value names (as now), and implicit flows still start from the `match` head.
- Docs: the `match` section of the Python guide (the capture reads the subject; the synthetic name). Corpus: the `todoruleid` in `control_flow.py` becomes `ruleid`.

## Tests
A variable subject and an expression subject (chains from the subject to the capture and on to the body; the head's definition), a nested `match` (each capture reads its own head), two functions with expression subjects (no free-variable flow between them), module-level `match`, the taint corpus case, a `match` subject that is a source call and one that is a tainted variable, and the existing match tests updated where the capture now has uses.

## Results
Executive summary: a `capture` node now reads the subject. For `match command:` it uses `command`; for an expression subject the `match` head defines the synthetic local `<match subject>`, which every capture of that `match` uses. Def-use chains, slices and taint now follow a value into the names a case binds. The corpus case from #51 is now an expected finding, and two cases were added (a variable subject reached through a call, and a constant subject that stays clean).
- `<match subject>` is added to the enclosing function's `FunctionInfo.locals`, so two functions' matches are not linked as free variables (checked by a test); at module level it is global like any module name.
- Tests: 4 new match tests (named subject, expression subject, nested matches, locality), the capture's uses in `test_call_sites.py` updated, and 2 corpus cases.
- Mutation check: 6 mutations (no uses, no direct uses, always and never synthetic, the local not added, `_add_local` a no-op), all caught.
- Docs: the `match` section of the Python guide (chains and the synthetic name).
- Checks: ruff format and lint clean, pyright 0 errors, 1,879 passed, 40 xfailed.
