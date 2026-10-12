# Python comprehensions, generators, `yield` and async/await (2026-10-12)

Tracks GitHub issue #11, part of the Python support epic (#1). Probing the code first showed that most of this already works, because the visitor treats expressions as part of their statement. This issue therefore records the decisions, pins the behavior with tests, and fixes the one visible gap.

## Decisions

1. **Comprehensions and generator expressions stay inside their statement** (the issue's "single node with correct def/use", not a desugared loop). They contain no statements, so a desugared loop would invent nodes that do not exist in the source and would show a `for` header where the editor has no line for it. The def/use side was already right and is now covered by tests:
   - the loop variables are local: not defined in the enclosing scope, and not uses of an outer variable of the same name;
   - only the first iterable is evaluated in the enclosing scope (`[x for x in x]` uses the outer `x`; `[x for x in xs for y in x]` uses only `xs`);
   - a walrus inside a comprehension binds in the enclosing scope (`[y := f(x) for x in xs]` defines `y`);
   - calls inside count as calls of the statement.
2. **`yield`, `yield from`, `await` are ordinary statements** that do not end the function. They use their operands and, as `x = yield y`, define `x`; they may raise, so an enclosing `try` gets an exception edge from before them (the state `gen.throw()` would raise from). A function containing `yield` is still one ENTRY/EXIT subgraph; the call edge from a caller goes to its entry even though calling a generator or coroutine function only creates the object and the body runs when it is iterated or awaited. That is the same name-based approximation used for every call.
3. **`async` variants share the sync handlers.** `async def`, `async for` and `async with` were already routed to the same visitor methods; the header text carries `async`. The one change: the implicit exit node of `async with` is named `__aexit__`.
4. **Taint-readiness (see epic #44).** Call extraction keeps the rules it already had, now pinned by tests, so structured call sites (#45) can reuse them: calls in comprehensions, generator arguments, lambdas, decorators and defaults count as calls of the statement that contains them, and a name bound by a comprehension is never reported as a use of an enclosing variable, so a taint flow `a = [f(x) for x in tainted]` goes from `tainted` to `a` and does not pick up an unrelated outer `x`.

## Out of scope

Modeling the suspension itself (resume edges, `send`/`throw` flow), generator return values, and `await` ordering between tasks.

## Tests

`test/python_cfg/test_python_comprehensions.py` and `test/python_cfg/test_python_generators_async.py`.

## Results

Executive summary: the issue turned out to be mostly decisions and tests. The visitor already treated comprehensions, `yield`, and `await` as parts of their statements with correct data flow, and routed `async def`/`async for`/`async with` to the sync handlers. This change pins that behavior, records why it is the right model, and renames the `async with` exit node. `ruff format --check`, `ruff check`, `pyright`, `pytest` pass (661 passed, 20 strict xfails; was 577).

- Code: one change in `python.py`, the exit node of `async with` is `__aexit__`; the module docstring states the decision.
- Tests: `test_python_comprehensions.py` (45) and `test_python_generators_async.py` (34), plus one in `test_python_exceptions.py`. They cover every comprehension kind, scoping (first iterable, nested comprehensions, shadowing, walrus, lambdas), calls and linking, comprehensions in headers and `try`, `yield`/`yield from`/`await` bindings and flow, generators in loops and `with`, `async for` with `else` and `break`, `async with`, and half-typed input.
- Mutation-checked with 11 deliberate bugs (first-iterable scoping, loop-variable locality, walrus binding, each comprehension kind, non-clause children, `__aexit__` naming). All caught on the first run.
- Fuzzed with all 489 prefixes of a program mixing async comprehensions, `async with`/`async for`, generators with `try`/`finally`, `yield from`, and walrus: no crashes.
- The Python guide and README are updated: the "still opaque" statement for comprehensions and generators is gone, and the guide has a worked example.

### Behavior to know
- Calling a generator or coroutine function creates an object; its body runs later. The call edge still goes to the function's entry (name-based approximation, as for every call).
- `yield` is not a resume edge: the flow after `got = yield n` is the next statement, as if the generator were resumed immediately.
- One label per edge applies to the `__aexit__` node too: when `async with` ends the function, the edge to the function exit shows `exception`.
