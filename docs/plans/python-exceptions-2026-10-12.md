# Python exceptions and context managers (2026-10-12)

Tracks GitHub issue #8, part of the Python support epic (#1). Builds on control flow (#7).

## Scope

`try` / `except` / `except*` / `else` / `finally`, `raise`, `with` / `async with`, and routing `return` / `break` / `continue` through `finally`.

## Decisions (approved before implementation)

1. **Exception edges leave from the state *before* a statement.** Python runs a handler from the point where the exception was raised, and the raising statement never completed:
   ```python
   x = 0
   try:
       x = int(s)  # may raise
   except ValueError:
       print(x)  # must see x = 0
   ```
   An edge from the statement node itself carries the state *after* it (`x = int(s)`, with `x = 0` killed), which is wrong here. So for each statement N in a protected region, edges run from N's predecessors to the handler, labeled `exception`. Statements that cannot raise (`pass`, `break`, `continue`, `global`, `nonlocal`) get none; everything else may raise. An explicit `raise` is an edge from the `raise` node itself (it defines nothing, so its state equals its input state).
2. **`finally` is one shared block, not one copy per path.** Duplicating it would create several CFG nodes for one AST node, which TODO.md says to avoid. Normal flow, handled exceptions, unhandled exceptions, `return`, `break`, and `continue` all enter it; its exit continues to each pending target. This includes some infeasible combinations; the continuation edges are only added when a path of that kind exists (normal flow, an exception, or a pending jump).
3. **`with` is an implicit `try/finally` with one `__exit__` node.** It runs on normal completion, on exceptions, and on `return`/`break`/`continue`. Exception suppression (`__exit__` returning true) is not modeled.
4. **Uncaught exceptions** go to the function's EXIT with label `exception` (to the module EXIT at module level).
5. **Handler dispatch is a chain**, like `if`/`elif`: one `CONDITION` header per handler (`except ValueError as e`), `true` into the handler body, `false` to the next header. The header uses the type expression and defines the `as` name. The last header's `false` edge propagates outward. Only a bare `except:` is treated as catch-all (it has no header and no propagation edge). `except*` is modeled like `except`.
6. No new `NodeType` members and no frontend changes: headers reuse `CONDITION`; exceptional edges are labeled `exception`.

## Design

**Protected regions.** A region records the nodes created while it is innermost. When it closes, its target is resolved and edges are added: from each recorded `raise`-like source, and from the predecessors of each may-raise node. Regions are: a `try` body (target: the first handler header, or the finally entry if there are no handlers); the handlers and `else` of a `try` that has a `finally` (target: the finally entry); a `with` body (target: its `__exit__` node). Handler bodies of a `try` with no `finally` belong to the enclosing region, so their exceptions propagate outward, as they should.

**Late-bound targets via marker nodes.** The `try` entry, the `try` join, and the finally entry are created up front as ENTRY/EXIT nodes that post-processing splices out, so jumps and exceptions can be wired before the finally body is visited, and no marker is visible in the graph. The try entry is also what makes the first body statement's incoming state well defined, so the edge appears to leave the statement before the `try`.

**Jump routing.** `return`/`break`/`continue` find the finally frames they cross: all frames of the current function for `return`; only frames created inside the current innermost loop for `break`/`continue`. They are chained innermost to outermost; each frame's exit connects to the next hop with the jump kind as the edge label.

**Edge labels.** A single edge carries one label. When two kinds of edge would share a source and target (for example a finally exit that both returns and re-raises to the same function exit), the first one added is kept.

## Tests

`test/python_cfg/test_python_exceptions.py`: edge sets for each construct; the `x = int(s)` case above, both as edges and as a def-use chain; partial progress through a body; `else`/`finally` flow; return/break/continue through one and two `finally` blocks; breaks that must not cross an enclosing `finally`; `raise` caught, uncaught, and propagating through nested `try`; `with` including `return` inside it and the `as` binding; `async with`; `except*`; bare `except`. The skeleton's unsupported-statement test moves to constructs that are still unsupported.

## Out of scope

`match` (#9), nested functions/classes (#10), comprehensions (#11).

## Results

Executive summary: Python CFGs now model `try`/`except`/`except*`/`else`/`finally`, `raise`, and `with`/`async with`, with `return`/`break`/`continue` routed through `finally`, following the decisions above. CI-equivalent checks pass: `ruff format --check`, `ruff check`, `pyright`, `pytest` (316 passed, 20 strict xfails; was 284 passed with #7).

- All of it is in `python.py`: protected regions (`_Region`), shared finally frames (`_Finally`), `visit_try_statement`, `visit_with_statement`, `visit_raise_statement`, and `_jump`, which `return`/`break`/`continue` now use.
- The key case works as designed: in `x = 0; try: x = int(s) except ValueError: print(x)` the handler is reached from the state before `x = int(s)`, so `print(x)` depends on `x = 0` only (tested both as edges and as a def-use chain).
- `test/python_cfg/test_python_exceptions.py`: 32 tests with expected graphs written as edge sets from Python's semantics. The skeleton's unsupported-statement test now uses `class`, `match`, and a decorated function, which are the constructs that are still opaque.
- Mutation-checked with 14 deliberate bugs (exception edges leaving from the statement, no re-raise from finally, `break` crossing finally blocks outside its loop, jumps ignoring finally, finally always falling through, lost unmatched-exception propagation, handler headers that may raise, `with` not registering a frame, `raise` treated as an ordinary statement, edges overwritten instead of kept, lost jump labels, `else` bypassing the body, a bare `except` with a propagation edge, a shared finally region without a finally). Each applied and each fails at least one test.
- Fuzzed with every one of the 545 prefixes of a program that uses all the new constructs (half-typed code is the common case in the editor): no crashes.
- Verified visually with the CLI on a function using `with`, two handlers, `else`, `finally`, and a `return` in a handler.

### Behavior to know
- **One label per edge.** When two kinds of edge would share a source and target, the first one added is kept. Notably, a finally exit that both returns and re-raises to the same function exit shows only `return`.
- **Marker nodes are invisible.** The `try` entry, join, and finally entry are spliced out by post-processing; that is why the exception edge into the first handler appears to leave the statement before the `try`.
- **`finally` is path-insensitive.** Its exit continues to every pending target and, if an exception can reach it, re-raises; it does not remember which kind of path entered it.
- **`with` suppression is not modeled.** A context manager whose `__exit__` swallows the exception does not get an edge to the code after the `with`.
- Handler headers and `__exit__` are treated as non-raising, to avoid doubling every edge into the handler chain.
- Exceptions escaping a function go to its EXIT. Callers' return edges therefore also appear on exception paths (the analysis is intraprocedural).
