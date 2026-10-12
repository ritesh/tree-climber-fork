# Python def/use extraction (2026-10-12)

Tracks GitHub issue #6, part of the Python support epic (#1). Stacked on the visitor skeleton (#5).

## Scope

`get_definitions` / `get_uses` for `PythonCFGVisitor`, implemented as a pure function of an AST subtree in `src/tree_climber/cfg/languages/python_bindings.py`. Python has no declarations, so definitions come from binding constructs and uses from names read in expression position.

The extractor must work on any subtree, because later issues (#7-#11) create CFG nodes for pieces of compound statements, and until then a compound statement is one opaque node whose whole subtree is aggregated.

## Rules

Definitions:
- `assignment` (also chained `a = b = 1`; annotated `x: int = 3`; a bare annotation `x: int` defines nothing)
- tuple/list/star unpacking targets, nested: `a, (b, *c) = f()`
- `augmented_assignment` (`x += 1` defines and uses `x`)
- walrus `named_expression`
- `for` targets, `with ... as target`, `except ... as name`
- `import` / `from ... import` (alias if present; `import a.b` binds `a`; `import *` binds nothing known)
- `def` and `class` names

Uses: identifiers read in expression position, including callees, decorators, default values, annotations, and f-string interpolations. Not uses: attribute names (`obj.attr` uses `obj` only), keyword-argument names, parameter names, the name of a `def`/`class`, names inside `import` statements, and `global`/`nonlocal` declarations.

## Decisions

1. **Attribute and subscript targets are weak updates.** `self.x = 1` and `a[i] = v` define *and use* the root name (`self`, `a`), and use any index expressions. The reaching-definitions framework only has strong updates (a definition kills earlier definitions of the name); modeling the write as use + def keeps the chain from earlier definitions of `a` to later uses of `a` flowing through the writing node. Targets whose root is not a name (`f().x = 1`) define nothing.
2. **Callees count as uses.** The issue text, like C and Java, excluded the function name in a call. In Python functions are ordinary values, so `callback(x)` where `callback` is a parameter or local is a real data dependency. A callee with no reaching definition (module functions, builtins) produces no def-use edge, so the cost is only a slightly longer `uses` list.
3. **`del` is a use, not a kill.** The issue said "kill", but the framework has no kill-only fact. Modeling `del x` as a definition would make later reads of `x` link to the `del`. Treating it as a use leaves earlier definitions reaching later nodes, a safe over-approximation (reading after `del` is an error anyway).
4. **`global` / `nonlocal` produce nothing.** The analysis is intraprocedural, so a declaration changes no reaching-definition fact; the only risk is counting the declared names as uses, which is excluded.
5. **Scope boundaries.**
   - `def`/`class` define their name and use defaults, annotations, decorators, and bases; their bodies are skipped (own CFG in #10).
   - `lambda` is evaluated inline: body uses count, minus the lambda's parameters; defaults count.
   - Comprehensions and generator expressions: names bound by their own `for` clauses are local, so they are neither definitions nor uses in the enclosing scope. The first iterable is evaluated in the enclosing scope. This overlaps the def/use half of #11, which can then focus on CFG shape.
6. Names are de-duplicated, in first-seen order.

## Deferred

Match-statement capture patterns are definitions (#9); until then identifiers inside `case` patterns are counted as uses.

## Tests

`test/python_cfg/test_python_bindings.py`: table-driven (source -> definitions, uses) covering each rule above, and each decision. `test/python_cfg/test_python_dfg.py`: end-to-end def-use chains through the reaching-definitions solver for straight-line code, parameters, unpacking, augmented assignment, weak updates, and callback parameters. The API test gains a DFG assertion for Python.

## Results

Executive summary: Python CFG nodes now carry definitions and uses, so def-use chains and the DFG views work for Python. CI-equivalent checks pass: `ruff format --check`, `ruff check`, `pyright`, `pytest` (257 passed, 20 strict xfails unchanged; was 182 passed with #5).

- `python_bindings.py` implements the rules and decisions above; `PythonCFGVisitor.get_definitions`/`get_uses` delegate to it, and the parameter-name helpers moved there.
- `test_python_bindings.py` (67 cases) and `test_python_dfg.py` (8 end-to-end chain tests). The API test now asserts DFG edges for Python.
- Mutation-checked: ten deliberate bugs in the extractor (attribute names counted as uses, no base definition on attribute writes, leaking comprehension variables, first iterable in the wrong scope, wrong name bound by `import a.b`, visiting `def` bodies, keyword names as uses, `nonlocal` names as uses, augmented assignment not reading, a function's own name as a use on its entry node) each fail at least one test.
- One defect found by the tests while writing them: a bare annotation `x: int` initially defined `x`. It only declares the name, so it now defines nothing; `self.x: int` still uses `self`.
- Verified visually with the CLI (`--draw_cfg --draw_dfg`) on the fixture: parameters flow from the function entry, `total` and `value` link to their uses, and nothing links across functions (the analysis is intraprocedural). The DFG-only view draws entry nodes as grey nodes labelled by id; C does the same.

### Known gaps
- Match-statement capture patterns are not definitions yet (#9); identifiers in `case` patterns count as uses until then.
- Compound statements are single nodes until #7-#9, so their definitions and uses are aggregated over the whole statement.
- `del` is not a kill (no kill-only fact in the framework); an assignment such as `a.b = 1` is a weak update modeled as use + def of `a`.
- Decorator and `global`/`nonlocal` effects beyond the above are out of scope.
