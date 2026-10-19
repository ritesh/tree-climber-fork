# Java field and array writes (#32), 2026-10-19

## Problem
In Java, an assignment defines a variable only when its left side is a plain name. So `o.f = x;` and `arr[0] = x;` define nothing, and a later read of `arr` has no def-use edge from the write. C and Python treat these writes as weak updates: the root variable is defined and also used, so earlier definitions keep flowing through the write.

## Plan
- `JavaCFGVisitor._written_variable(target)`, like C's: walk down through `array_access` (its `array`) and `field_access` (its `object`) to the root.
  - A plain name at the root is the written variable.
  - Anything else writes no variable: `this.f`, `super.f`, `get().f`.
- Use it for the left side of an `assignment_expression` and for the operand of an `update_expression` (`arr[i]++`, `o.n++`).
- The root is already a use, because it is the object of a field access or the array of an array access. So no change to `get_uses`.

## Tests
- Bindings: `o.f = x`, `o.a.b = x`, `arr[0] = x`, `m[i][j] = x`, `arr[i] += x`, `arr[i]++`, `++o.n`, `this.f = x`, `this.a[0] = x`, `get().f = x`.
- Def-use chains: a parameter flows through `arr[0] = x;` to a later `return arr;`, and so does the write itself. A new definition `arr = other;` still kills the parameter's definition.
- Taint: a source written into `arr[0]` reaches a sink that reads `arr`.

## Docs
- The Java limitations in `docs/plans/extending-languages.md`, the README and the cross-language note.

## Results
Executive summary: a Java write into a field or element of a named variable is now a weak update of that variable, as in C and Python. `o.f = x` and `arr[i] = x` define `o` and `arr`, so the write reaches later reads. A write whose target does not start with a name (`this.f`, `super.f`, `get().f`) still defines nothing, as #32 proposed.

- **`JavaCFGVisitor._written_variable`** walks `array_access` and `field_access` down to the root. It is used for assignments, `++`/`--` (`arr[i]++`, `++o.n`), and `assigned_to`, so `arr[0] = f();` records that `arr` receives the call's result, as C does.
- **Taint:** the corpus case `argv[0] = request.getParameter("cmd"); exec(argv)` is now found (it was a `todoruleid`). With `field_sensitive`, `o.a` and `argv[0]` are told apart from `o.b` and `argv[1]`. `this.pending = ...; exec(this.pending)` is still missed; its annotation now gives that reason.
- **Tests:**
  - 14 binding cases: nested fields and elements, compound assignment, `++`, chained assignment, and the `this`/`super`/call roots;
  - def-use chains through an element write and a field write, and a plain assignment replacing the value;
  - `assigned_to` for `a[0] = f()`, `o.f = f()` and `this.f = f()`;
  - a field-sensitive taint test for Java fields and elements.
- **Mutation check:** 8 mutants of the change, all caught.
- **Docs:** the Java limitations in the language guide, the README, the taint guide and the Python guide now say only writes through `this` (and other roots that are not names) are lost.
- **Checks:** ruff format and lint are clean, pyright reports 0 errors, and the suite gives 2,130 passed, 38 xfailed.
