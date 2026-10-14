# Field/container sensitivity and control dependence (#49), 2026-10-14

Part of #44. Both refinements are options, off by default, with tests that show the precision change.

## Control dependence
**Problem.** Branching on tainted data (`if x == "a": cmd = "safe"`) is invisible: slices miss the condition that decides whether a statement runs, and the taint analysis misses implicit flows.

**Plan.** New `tree_climber.dataflow.control_dependence`:
- Per function (nodes reachable from its ENTRY without call/return edges), compute immediate post-dominators on the reversed CFG rooted at the function's EXIT (Cooper-Harvey-Kennedy).
- For each edge X->S (call/return edges excluded): walk from S up the post-dominator tree to ipdom(X), exclusive; each node on the way is control dependent on X through that edge's label (`true`, `false`, a `case` value, `exception`, or `flow`).
- A node that cannot reach EXIT (an infinite loop with no way out) has no post-dominator; the walk from it marks only the nodes on its way, which over-approximates dependence there.
- This is generic over the CFG, so Python `match`, `try`/`finally`, loop `else`, and C/Java `switch` are handled by their edges.

Query API:
- `CodeGraph.control_dependences(node)` gives the branch nodes and edge labels a node depends on; `control_dependents(node)` the reverse.
- `forward_slice` / `backward_slice` take `control=True`, which adds control dependence to the slice (a backward slice gets the conditions that decide whether its nodes run, and their data; a forward slice gets what runs or not depending on a node in it).

Taint: `implicit_flows=True`. When a predicate node (condition, loop header, switch head) reads a tainted value, the definitions and returns of the nodes control dependent on it are tainted (edge kind `control` in the path), transitively through nested branches. Exception edges are not treated as implicit flows (a statement that may raise would otherwise taint everything after a `try`).

## Field and container sensitivity
**Problem.** `d["k"] = tainted` and `obj.f = tainted` are weak updates on the root name, so every later use of `d` or `obj` is tainted, including `d["other"]` and `self.name`. In the standard library run this was the largest source of false positives (`self.debug = ...` taints all of `self`).

**Decision.** Keep the reaching-definitions framework on whole names (it has strong updates on names only, and changing it would change every existing def-use result). Field sensitivity lives in the taint analysis, as a tag on tainted values: a taint is either on the whole value or on one first-level field or constant key (`.f`, `[k]`; depth 1).
- A write `v.f = e` / `v[K] = e` with a constant key taints field `f` / `K` of `v` when `e` is tainted, and keeps `v`'s earlier tags (a weak update). A write with a non-constant key taints the whole value.
- A read `v.f` / `v[K]` is tainted when `v` is tainted as a whole or on that field. A bare read of `v` (passing it, copying it) is tainted when any field is, and what it produces is tainted as a whole, except that a bare variable passed as an argument or receiver to a function defined in the file carries its tags into the parameter (so `self` keeps only its tainted fields inside methods).
- Reads are collected per statement, not per argument: if a statement reads `d["a"]` in one argument and `d["b"]` in another, both are taken as reading `a` and `b`.
- Field accesses are found in the AST: Python `attribute` / `subscript`, C `field_expression` / `subscript_expression`, Java `field_access` / `array_access`; keys are constant when they are string or number literals.

Option: `field_sensitive=True` on `analyze` / `analyze_source`.

## Tests
Control dependence on if/else, nested ifs, while, for with `else` and `break`, `match`, `try`/`finally`, C and Java `switch` with fall-through, `do`/`while`, early return, and loops that never exit; slices with and without `control`; implicit flows on and off. Field sensitivity on and off: dict keys, attributes, writes then other reads, non-constant keys, copies, weak updates keeping tags, `self` into methods, C structs and Java fields. The standard library with the example rules, before and after each option. Mutation-checked.
