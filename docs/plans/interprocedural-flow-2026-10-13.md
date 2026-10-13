# Interprocedural data flow (2026-10-13)

Tracks issue #46 (supersedes #42), part of the graph-queries and taint-tracking epic (#44). Builds on structured call sites (#45).

## Problem
`RoundRobinSolver` deliberately does not propagate across `function_call` / `function_return` edges, so a callee's locals cannot overwrite the caller's. The flip side is that nothing flows *between* functions: a tainted argument never reaches the callee's parameter, a tainted return value never reaches the caller, and closure reads, `global` and `nonlocal` writes are unconnected.

## Design
A layer on top of the existing solver, not a change to it. A new function `analyze_interprocedural(cfg)` (`dataflow/interprocedural.py`) returns an `InterproceduralResult` with three kinds of edges. Intraprocedural flow is still the existing def-use chains; these edges connect those islands.

```
ArgumentFlow      call (CallRef: node, site index), argument index (-1 = the receiver),
                  callee entry node, parameter name
ReturnFlow        callee return node  ->  call (CallRef)
FreeVariableFlow  variable, definition node, use node, scope ("closure" | "global")
```
Why call sites and not variables as endpoints: `sink(read())` has no variable between the callee's return and the sink's argument. A consumer (the taint analysis) treats a call site's result as tainted when any `ReturnFlow` into it is, and propagates it to the call's `assigned_to` variables, to the enclosing call's argument (`feeds`), or to the node's definitions.

### Resolving calls
Calls are still resolved by name (documented since #5): a call site's `callee` is matched against the names functions were registered under (`context.function_definitions`: the plain name, `__init__` under its class name). A call with several candidates flows to all of them.

### Arguments to parameters (all languages)
Each ENTRY node gets `metadata.function`, a `FunctionInfo`: its call name, its `ParameterInfo` list (name, kind `positional` / `keyword_only` / `var_positional` / `var_keyword`, has-default), whether it binds a receiver, and scope information (below). Binding follows Python's rules, over-approximating where needed:
- positional arguments go to the positional parameters in order; extras go to `*args`, or are dropped;
- keyword arguments go to the parameter of that name, or to `**kwargs`;
- a `*args` argument flows to all remaining positional parameters and `*args`; a `**kwargs` argument to all remaining named parameters and `**kwargs`;
- a method called through a receiver (`obj.m(x)`) binds the receiver to `self` and shifts the positional arguments by one; a constructor call (`C(x)`, resolved to `C.__init__`) shifts by one without binding `self`; static methods and plain functions never shift;
- C and Java: positional, in order. Java has no explicit `this` parameter, so the receiver binds nothing.

### Return values to callers
Every `return` node of a callee flows to every call site that resolves to it. Constructor calls are skipped (the result is the new object, not a return value).

### Free variables, `global` and `nonlocal` (Python, C)
Each function knows which names are *local* (Python: parameters plus names strongly bound in its body, attribute and subscript writes excluded; C: parameters plus declared names), which it declares `global`, and which `nonlocal`, and its lexically enclosing function (class bodies are not scopes). A name used in a function but not local resolves outward: through `nonlocal` and enclosing functions, else to the global scope. Definitions of a variable in a scope, including writes from nested functions that declare it `global` / `nonlocal` (in C, any write to a name not declared locally), flow to every use that resolves to that scope in a different function. This is flow-insensitive (all definitions reach all uses) and supersedes #42.
Java fields are not modeled as nodes, so Java gets argument and return flow only.

### Not changed
The solver; existing def-use results; `/parse` output (the analysis is a library function; exposure belongs to #50).

## Tests
`test/test_interprocedural.py`: binding rules one by one (positional, keyword, defaults, `*args`, `**kwargs`, keyword-only, methods, constructors, static methods), return flows, name collisions (several callees), recursion, closures at one and two levels, `nonlocal`, `global`, C globals, and that callee locals do not leak into the caller. Both cases missed by the prototype in #44 (`run(x)` into `eval(cmd)`, `x = read()` into `eval(x)`) end to end, using the def-use chains.

## Results

Executive summary: `analyze_interprocedural(cfg)` returns argument, return and free-variable flows between the existing def-use islands for Python, C and Java (Java: arguments and returns only). The solver, the def-use chains and `/parse` output are unchanged; every ENTRY node gains `metadata.function` (a `FunctionInfo`). `ruff format --check`, `ruff check`, `pyright` and `pytest` pass (1,018 passed, 20 strict xfails; the suite also includes the other merged work). #42 is superseded.

- **Tests**: `test/test_interprocedural.py` (72) covers the binding rules one by one, return flows, name collisions, recursion, closures at one and two levels, `nonlocal`, `global`, class bodies not being scopes, C globals and locals, Java varargs, serialization, and a taint-propagation harness that follows both cases missed by the prototype in #44 (`run(x)` into `eval(cmd)`, `x = read()` into `eval(x)`) end to end using the def-use chains. Parameter and scope extraction are tested through the `FunctionInfo` on ENTRY nodes, not by unit tests on `python_bindings.py` directly.
- **Mutation-checked** with 47 deliberate bugs across `interprocedural.py`, `python_bindings.py`, `python.py`, `c.py` and `java.py`. In the first full run six survived and one pattern no longer applied; the survivors were scope-resolution and exclusion bugs (`global` / `nonlocal` handling) and the `*args` position bookkeeping. Tests were added and the code was restructured (`after_star`, locals excluding declared names), so three of those mutants no longer exist in that form. The rest, and replacement mutants for the removed ones (own `global` ignored, `after_star` dropped, plain functions binding a receiver), were re-run against the final tests and all fail them. Not re-run: the full 47 against the final code in one pass.
- **Real code**: on the installed Python 3.12 standard library (1,081 files, 0 errors) the analysis finds 56,771 argument flows, 28,941 return flows and 37,102 free-variable flows in 0.7 s of analysis time in total (largest file 25 ms).
- **Found while testing**: C's `...` was counted as a local name (now only positional parameters are); a quadratic cost in nested-call argument uses is the fix from #45, reused here.

### Limitations
- Calls resolve by name, so a name shared by several functions gives edges to all of them, and calls through `f()(x)`, `handlers[k](x)`, function pointers and decorators that rewrap functions are not followed.
- Free-variable flow is flow-insensitive: all definitions in a scope reach all uses in other functions, ignoring execution order. `global` / `nonlocal` writes over-approximate in the same way.
- Java free variables (fields) are not modeled; `FunctionInfo.locals` is None there and no free-variable flows are produced. Java `new Foo(x)` is still not a call site.
- Constructor calls get argument flows to `__init__` but no return flow.
- The analysis is a library function; exposing it through `/parse` or the CLI is part of #50, and joining it with the query API (#47 / PR #60) is a follow-up that maps these flows onto `DataFlowEdge`.
