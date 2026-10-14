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

## Results

Executive summary: control dependence is computed from post-dominators for Python, C and Java, exposed in the query API (`control_dependences`, `control_dependents`, `control=True` on both slices) and used by the taint analysis's `implicit_flows` option; `field_sensitive` tracks first-level fields and constant keys in the taint analysis. Both options are off by default, and every existing result is unchanged. `ruff format --check`, `ruff check`, `pyright`, `pytest` pass (1587 passed, 20 strict xfails).

- **Tests**:
  - `test/test_control_dependence.py` (14): if/else and nesting, early return, while, for/else/break, `match`, `try`/`finally`, a loop that never exits, recursion, calls, C `switch` with fall-through, `do`/`while`, Java `switch` and `for`.
  - `test/query/test_query_control.py` (15): dependences and dependents in all three languages, slices with and without `control`, transitivity through nested branches and through a condition's own data.
  - `test/taint/test_taint_precision.py` (35), each option off and on: implicit flows through if, nested ifs, loops, `match` (including a later case), returns, C `switch` and Java `if`, and what they must not do (code after the branch, exceptions, sink arguments). Field sensitivity on keys, attributes, quote styles, non-constant keys, copies, whole taint, kept tags, deeper writes, `self` into methods, bare arguments, C structs, Java reads, and both options together.
  - `test/taint/test_taint_fields.py` (27): the access extractor on each statement form in each language.
  - The guide's examples are pinned in `test_query_guide.py` and `test_taint_precision.py`.
- **Mutation-checked**:
  - Over the run, 61 deliberate bugs across `control_dependence.py`, the query slices, the engine options and `fields.py`.
  - The first run applied 54: 34 were caught and 20 survived. The 3 that did not apply were rewritten, and all 3 are caught.
  - Of the 20 survivors, new tests catch 12. Two pointed at code that does nothing (a redundant reachability check, a sort of lists already in order), which was removed. Two were in the `match` case chain, replaced by seeding only the first case, since later cases depend on the earlier ones' `false` edges. Four are equivalent.
  - The replacement got its own 3 mutants plus one for the bare compound read: two are caught, one exposed a dead guard (removed), and one is equivalent.
  - On the final code, 5 mutants are equivalent: dropping the same-function check on successors (only call edges leave a function), the exit's own post-dominator, allowing several exits (a function has one), skipping single-successor nodes (an optimization), and seeding a C/Java switch head (it branches itself, so control dependence already covers it). Every other mutant is caught.
- **Standard library** with the Python example rules (1,081 files, no errors in any configuration):
  - default: 45 findings in 43.6 s;
  - `field_sensitive`: 42 findings in 43.7 s. 3 are removed and none added, including the `imaplib` chain through `self.debug`;
  - `implicit_flows`: 64 findings in 45.0 s. 19 are added and none removed, in webbrowser, doctest, mailcap, pdb, pydoc and site;
  - both: 62 findings in 45.5 s.

  The added implicit flows I read build on the existing over-approximations (a tainted write into `sys.argv` taints all of `sys` without `field_sensitive`; a method call on a module reads it whole), so they are mostly noise; implicit flows are for questions like "does the attacker decide which branch runs", not for default scans. The remaining false positives in the default run come from non-constant keys (`_browsers[name.lower()] = ...`), constructors passing taint through, and context-insensitive returns, which field sensitivity does not address.

### Behavior to know
- Control dependence is per function and intraprocedural. Inside a `try`, statements depend on their predecessor's normal edge, because the CFG sends the exception edge from the node before a statement that may raise. What follows a `finally` depends on the `finally`. The labels tell these apart from conditions.
- Implicit flows use only conditions, loop headers and switch heads, and only their non-exception edges. They taint definitions and returns, not sink arguments.
- Field sensitivity is depth 1, and reads are counted per statement, not per argument. A copy (`e = d`) or a pass-through call turns field taint into whole taint. A bare variable passed to a function defined in the file keeps its fields. A method call reads its object whole.
- Java writes into fields and arrays define nothing in the CFG (#32), so taint written there is lost with or without `field_sensitive`. C writes through a pointer (`p->f = x`) define nothing either, as before.
