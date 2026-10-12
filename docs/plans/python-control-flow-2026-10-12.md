# Python control flow (2026-10-12)

Tracks GitHub issue #7, part of the Python support epic (#1). Builds on the visitor skeleton (#5) and def/use extraction (#6).

## Scope

- `if_statement` with `elif_clause` chains and `else_clause`
- `while_statement` and `for_statement` (including `async for`)
- `break_statement`, `continue_statement`
- Loop `else` clauses
- Conditional expressions (`a if b else c`)

## Conventions reused from C and Java

A `CONDITION` node for `if`/`elif`, a `LOOP_HEADER` node for loops, edges labeled `true`/`false`, an explicit `EXIT` join node ("EXIT: if stmt", "EXIT: while loop", "EXIT: for loop") that the base post-processing splices out while keeping edge labels, and the context's break/continue targets (`push_loop_context`).

## Design

**if / elif / else.** Each clause gets a CONDITION node (the `elif` condition is its own node), chained by `false` edges: `cond1 -true-> block1`, `cond1 -false-> cond2`, ..., and the last `false` edge goes to the `else` block, or straight to the join when there is no `else`. All branch exits go to the join.

**while.** LOOP_HEADER on the condition; body exits and `continue` go back to the header; `true` goes to the body.

**for.** One LOOP_HEADER node, text `for <target> in <iterable>`, `ast_node` = the iterable (so calls in it are found and the highlight is the iterable). It defines the loop target(s) and uses the iterable. `true` = another item, `false` = exhausted. The target is defined each time the header runs, which is conservative on exhaustion.

**Loop else.** The `else` block runs when the loop ends without `break`:
- the header's `false` edge goes to the `else` block (or the loop exit if none);
- the `else` block's exits go to the loop exit;
- `break` goes to the loop exit, skipping `else`;
- `else` is visited after the loop context is popped, so a `break` or `continue` inside it targets the enclosing loop.

**break / continue outside a loop.** Python rejects this at compile time. C asserts; for an editor that analyzes half-typed code, the visitor instead creates a BREAK/CONTINUE node with no outgoing edge and does not raise.

**Conditional expressions** stay inside their statement's node. They contain no statements, so no control-flow structure is lost; the "else" substring bug that used to delete such nodes was fixed in #3.

**Header def/use.** `if`/`while` conditions use the existing extractor (walrus works). A new `collect_for_header_bindings` in `python_bindings.py` applies the target rules to `left` and the use rules to `right` only; the existing `for_statement` handling remains for statements still aggregated into one node (e.g. inside a `try` until #8).

## Fix included: nested `def` was spliced into the enclosing flow

Found while probing: `visit_function_definition` is also reached for a `def` inside a block, so `def f(): def g(): pass; x = 1` chained `f`'s entry -> ENTRY `g` -> ... -> `x = 1`. Control-flow bodies make nested definitions common, so this PR makes only the module visit the function visitor directly; a `def` anywhere else becomes one opaque statement until #10 gives nested functions their own graph.

## Tests

`test/python_cfg/test_python_control_flow.py`: edges and labels for each construct and each loop-else case, nested loops (innermost target; `break` in an `else` targets the outer loop), `continue`, return inside loops, break/continue outside a loop, header def/use chains through the solver (loop-carried dependencies now exist, so the `a++` convention from #2 applies), and the nested-`def` fix. The skeleton's unsupported-statement test moves to constructs still unsupported.

## Out of scope

`try`/`with` (#8), `match` (#9), nested functions/classes/lambdas (#10), comprehensions (#11).

## Results

Executive summary: Python CFGs now model `if`/`elif`/`else`, `while`, `for`/`async for`, loop `else`, `break`, and `continue`. CI-equivalent checks pass: `ruff format --check`, `ruff check`, `pyright`, `pytest` (284 passed, 20 strict xfails; was 257 passed with #6).

- Handlers in `python.py` follow the C conventions (CONDITION / LOOP_HEADER nodes, `true`/`false` labels, EXIT join nodes spliced out by post-processing). `collect_for_header_bindings` in `python_bindings.py` gives a `for` header its own definitions (targets) and uses (iterable).
- Loop `else` is wired as designed, including the subtle case: it is visited after the loop context is popped, so `break`/`continue` in an `else` target the enclosing loop. Covered for both `for` and `while`.
- Fix to #5's behavior: a `def` nested in a function or inside a conditional/loop body was spliced into the enclosing flow. Only the module now visits function bodies; any other `def` is one statement until #10.
- `break`/`continue` outside a loop yield a node with no outgoing edge instead of raising (C asserts).
- `test/python_cfg/test_python_control_flow.py` (36 tests): edge sets for each construct and loop-else case, nested loops, returns inside loops, jumps outside loops, the nested-`def` fix, and loop-carried def-use chains through the solver. The skeleton's unsupported-statement test now uses `with`, `class`, and `try`. `def_use_chains` moved to the shared helpers.
- Mutation-checked: 17 deliberate bugs (loop-context handling for `else`, `break`/`continue` targets, missing back edges, `elif` chaining, `else` labels and routing, nested-`def` splicing, `for` header definitions, `break` outside a loop asserting) in both loop kinds. The first run left one survivor (`break` in a `while` loop's `else` was untested; only `for ... else` was). I added that test and the mutation is now caught. Four of my first-pass mutations silently failed to apply because ruff had re-wrapped the code; I discarded those results and redid them.
- Verified visually with the CLI on a function using `for`/`if`/`elif`/`continue`/`break`/`else`/`while`.

### Behavior to know
- A conditional expression (`a if b else c`) stays inside its statement's node; it contains no statements, so no control-flow structure is lost.
- `while True:` is treated like any other loop: the header keeps a `false` edge. C and Java do the same.
- The `for` header node highlights the iterable (its `ast_node`); there is no AST node spanning `for target in iterable`.
- `try`/`finally` interplay with `break`/`continue`/`return` arrives with #8.
