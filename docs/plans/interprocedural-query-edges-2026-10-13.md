# Interprocedural flows as query edges (2026-10-13)

Part of #48 (taint analysis), on top of #46 (interprocedural flow, PR #61) and #47 (query API, PR #60).

## Problem
`analyze_interprocedural(cfg)` describes argument, return and free-variable flows with call-site endpoints. The query API's data-flow queries take `DataFlowEdge`s (node and variable at each end) through `extra_edges=`. Nothing converts one into the other, so every caller would hand-write the mapping, as the guide's "Edges from other analyses" example does.

## Plan
`interprocedural_edges(cfg)` in `tree_climber.query.edges`, and `CodeGraph.interprocedural_edges()` (computed once per graph). Edge kinds `argument`, `return`, `free_variable` (constants next to `DEF_USE`).

- **Argument** (call node `n`, site `s`, argument `i` -> callee ENTRY, parameter `p`): one edge per variable the argument reads (`CallArgument.uses`), target `p` (a definition at the ENTRY). A nested call whose result is the argument (`f(g(x))`) adds an edge from the placeholder `<call k>` (site `k` of the same node), but only when that call's result arrives from a return edge; otherwise the argument's own uses already carry it. The receiver (argument -1) reads the variables of the node that the receiver text names (`obj` in `obj.m()`, `self` in `self.data.get(k)`), plus a nested call that is the receiver (`a.b().c()`), under the same rule.
- **Return** (return node -> call node `n`, site `s`): from `<return>` (the whole return node, since a return node defines nothing) to each variable the site is assigned to (`x = f()`: arrives at the definition of `x`), or to `<call s>` when it is not (arrives as a use, which flows into the node's definitions).
- **Free variable** (definition node, use node, variable): one edge with the same variable at both ends.

Edges are de-duplicated and in a stable order.

## Tests
Python, C and Java: an argument reaches the callee's parameter and its uses; a return reaches the assignment and what follows; a value goes in through an argument and out through a return (`y = wrap(x)`); nested calls; methods and receivers; closures and globals; the #44 prototype case that missed a flow across a call is found with the edges; and the edges agree with `analyze_interprocedural`'s counts.

## Results

Executive summary: `CodeGraph.interprocedural_edges()` (and `interprocedural_edges(cfg)`) turn the interprocedural flows into `DataFlowEdge`s, so every data-flow query crosses calls when given them. The #44 prototype case that missed a flow across a call (`x = input(); g(x)` into `system(p)`) is found. `ruff format --check`, `ruff check`, `pyright`, `pytest` pass (1382 passed, 20 strict xfails).

- **Tests**: `test/query/test_query_interprocedural.py` (19): argument and return paths in Python, C and Java; a return into an unassigned call; a nested call that returns flowing on as an argument, and only to its own argument; a nested call without a return adding no placeholder; receivers into `self` and the receiver-name rule; a constructor receiver binding nothing; closures, Python globals and C globals; in through an argument and out through a return; every flow having an edge; one edge for a repeated flow; the graph returning a copy. The guide example is pinned in `test_query_guide.py` and the #44 case in `test_query_taint.py`.
- **Mutation-checked** with 25 deliberate bugs. All fail tests except three equivalent ones: dropping `re.escape` (variable names have no regex metacharacters), a `Counter` in place of the ordered dict (also unique keys), and dropping the `role` check on nested calls (the position already tells an argument from the receiver, and a call that is the callee leaves its site without a name, so it has no argument flows). Two survivors of the first run (which call and which position a nested call feeds) and a duplicate-edges mutant were killed by the last two tests.
- **Standard library**: 1,081 files, no errors, 53,391 argument, 30,692 return and 37,102 free-variable edges in 1.6 s. Fewer argument edges than argument flows: a constant argument reads no variable, and repeated flows merge; more return edges than flows: `a, b = f()` gives one per assigned variable.
- **Found, not fixed**: a C function that returns a pointer (`int *f()`) crashes the CFG builder (#62); the C tests use `int` returns.

### Behavior to know
- The edges inherit the analysis' approximations: calls resolved by name, context-insensitive (a function returning its argument links every caller's argument to every caller's result), flow-insensitive free variables. Data-flow paths are not call/return-matched.
- Statement-level, like the rest of the query layer: an argument edge leaves every variable the argument reads, including those inside nested calls and, in Python, function names; a return without an assignment arrives at the whole call node.
- A receiver's variables are found by name in its text, so `self.data.get(k)` reads `self`; a name followed by `(` is a callee and is skipped.
