# Python classes, nested functions, lambdas and decorators (2026-10-12)

Tracks GitHub issue #10, part of the Python support epic (#1). Builds on #5-#9.

## Decisions

1. **Every function is its own subgraph, at any depth.** A nested `def` gets an ENTRY/EXIT pair like a module-level function. Until now only the module-level ones did, and anything deeper was one opaque statement.
2. **Where it is defined, the enclosing flow gets one statement** with the header as its text (`def inner(a, b=1)`, `class A(Base)`, decorators included). It defines the name and uses what is evaluated at definition time: decorators, default values, annotations, base classes. Its `ast_node` is the name, so the editor highlights the header and not the whole body.
   - Exception: a plain module-level `def` stays out of the module flow, as since #5, so a file of only `def`s still has no `<module>` graph. Decorated module-level functions and classes do appear, because they run code when defined.
3. **Classes.** The `class` statement is one node in the enclosing flow. Its calls include the bases and the class body's own statements (which run at definition time) but not its methods' bodies. Names bound in the class body are class attributes, not variables of the enclosing scope, so they are not defined (`x = 0; class A: x = 1; print(x)` still depends on `x = 0`). The body's own control flow is not modeled. Each method is a subgraph, displayed as `Class.method` (`Outer.Inner.method` for nested classes).
4. **Calls to methods stay name-based.** A method is reached by its plain name, so `self.step()`, `obj.step()` and `step()` all link to every function or method named `step`, in any class. Resolving by class needs type information the analysis does not have; the issue's "record the method name so call edges can resolve" is met. `__init__` is reached by the class name instead (`Account(...)` runs `Account.__init__`), and not by `__init__`, so `super().__init__()` is not linked to every constructor in the file.
5. **Decorators are calls.** `@cache` and `@functools.cache` call `cache`; `@route("/x")` calls `route` (and its result is called, which is not modeled). They are recorded on the definition statement, so a decorator defined in the file is linked with call/return edges.
6. **Lambdas stay inline.** A lambda is an expression with no statements, so there is no control flow to build: its calls count as calls of the statement that contains it, and its parameters are not uses. This matches Java (lambdas are processed inside the containing method). No code change; documented and tested.
7. **Isolation.** While a function body is built, the surrounding `try` regions, `finally` frames and loops are hidden, so nothing in a nested function raises into, returns through, or breaks out of the code that only defines it.
8. **Closures, `nonlocal`, `global`.** Dataflow in this framework is intraprocedural: reaching definitions deliberately do not cross `function_call`/`function_return` edges (so a callee's locals cannot kill the caller's). A nested function's read of an enclosing local, or a `global`/`nonlocal` write, is therefore not connected to the other scope's definition. This is a framework limitation shared with C globals; it is filed as a follow-up rather than fixed here.

## Changes

- `python.py`: `visit_function_definition`, `visit_class_definition`, `visit_decorated_definition` share `_visit_definition`; `_visit_methods` builds method subgraphs; `_visit_function` takes a qualifier and runs in `_function_scope`; `_decorator_calls`.
- Tests: `test/python_cfg/test_python_definitions.py`; the control-flow, calls and unsupported-statement tests that encoded the old opaque behavior are updated (`TestUnsupportedStatements` becomes `TestDefinitionsInTheModuleFlow`: nothing is unsupported any more).

## Out of scope

Comprehensions and generators (#11). Interprocedural/closure dataflow (follow-up issue).

## Results

Executive summary: nested functions, classes with their methods, and decorated definitions now have real graphs; lambdas stay inline by decision. `ruff format --check`, `ruff check`, `pyright`, `pytest` pass (577 passed, 20 strict xfails; was 524 on the `match` branch this is built on).

- Everything is in `python.py` as designed above. The visible changes: a nested `def`/`class` statement now reads `def g(a)` / `class A(Base)` (header only, with decorator lines when present) instead of the whole source; methods are `Class.method` entries; `Account(...)` links to `Account.__init__`; decorators are calls.
- Tests: `test/python_cfg/test_python_definitions.py` (53 tests). Five existing tests encoded the old opaque behavior and were rewritten: the nested-`def` pair in the control-flow tests, three call tests (the method body's call now links from inside the method, and the class node itself must not link), and `TestUnsupportedStatements` became `TestDefinitionsInTheModuleFlow`.
- Mutation-checked with 23 deliberate bugs (isolation of regions, finally frames and loops; header text and highlight; definitions, uses and calls; decorator calls; method discovery, qualification, nesting and decoration; constructor and plain-name registration; flow result). The first run left three survivors: nothing tested a `break`/`continue` inside a nested function inside a loop, nothing tested a nested class's constructor, and one check (`type == "call"` in the decorator scan) was redundant, so I removed it. All are now caught.
- Fuzzed with all 695 prefixes of a program using every new construct together (decorators, defaults, nested functions with `finally`, a class with `match`, `with`, an async method, a lambda): no crashes. Rendered with the CLI (`--draw-cfg`) and checked.
- The Python guide and README are updated, including the new "closures" limitation.

### Behavior to know
- Calls stay name-based: `self.step()` links to every method named `step` in the file, in any class. The framework has no type information to do better.
- Closure reads and `global`/`nonlocal` writes are not connected across scopes, because dataflow deliberately does not cross call edges. Filed as a follow-up.
- A class body is one statement: its calls count, its names are not tracked, and control flow inside a class body is not modeled.
- A plain module-level `def` still has no statement in the module flow, as since #5; decorated ones and classes do.
