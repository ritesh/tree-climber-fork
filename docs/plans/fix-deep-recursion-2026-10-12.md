# Deeply nested expressions crash the analysis (2026-10-12)

Found by running the analysis over CPython's `Lib/test` (1,314 files): `test_traceback.py` contains an 800-target chained assignment (`a1 = a2 = ... = a800 = None`) and raised `RecursionError`. Tracked in the issue filed with this change.

## Probe
Generated programs with 1,500-deep expressions, run through the builder and dataflow, `/parse`, and every CLI draw option:

| Program | Python | C | Java |
|---|---|---|---|
| chained assignment, `1 + 1 + ...`, `f(f(...))`, `.m().m()...`, `.a.a...`, `a and b and ...`, `'a' + 'b' + ...` | builder and every entry point fail | builder ok | builder ok |
| any of the above | `/parse` fails | `/parse` fails | `/parse` fails |
| any of the above | CLI fails for all draw options | `--draw-ast` and `--draw-cpg` fail | `--draw-ast` and `--draw-cpg` fail |

tree-sitter nests a chain like `a = b = c` or `x + y + z` one level per operator, and these places walk the tree with Python recursion (default limit 1,000 frames):
1. `python_bindings._Collector` (definitions and uses): handlers call `visit`, which calls handlers, about three frames per level.
2. `ast_utils.ast_node_to_dict`, and `dataclasses.asdict` on its result, in `/parse`.
3. The CLI's AST drawings: `add_ast` (AST view), `add_ast_subtree` (subtree CPG layout), `add_ast_into` (bigraph CPG layout).
4. `ast_utils.find_nodes_containing_position` (same shape; not on any path today, fixed for consistency).

## Approach
No recursion limit changes: raising it moves the cliff and can overflow the C stack.
- The collector keeps its handler structure but becomes a trampoline: each handler is a generator that yields the sub-walks it needs (a node to visit, or another generator such as `target`), and a driver runs them with an explicit stack. Sub-walks finish before the handler continues, exactly as with recursion, so definitions and uses come out in the same order.
- `ast_node_to_dict` builds bottom-up with an explicit stack, and `/parse` uses a new iterative `ast_to_json` that produces the same dictionary `asdict` did.
- One iterative `iter_ast_edges(root, named_only)` helper in `ast_utils` yields (parent, child) pairs in the order the recursive drawers added them; the three drawers use it.

## Tests
`test/test_deep_nesting.py`: every shape above, for each language, through the builder and dataflow, `/parse`, and each CLI draw option; the 800-target chain from CPython; and the new helpers against the recursive output on ordinary code (same dictionary, same edge order). The existing binding tests check that definitions and uses are unchanged.

## Results

Executive summary: no walk over the AST recurses on the Python stack any more, so expressions of any depth go through the builder, dataflow, `/parse` and every CLI drawing for all three languages. `ruff format --check`, `ruff check`, `pyright`, `pytest` pass (828 passed, 20 strict xfails; was 727).

- `python_bindings._Collector` is a trampoline as planned. Checked against the old recursive collector on every statement, `for` header and `case` clause in the installed 3.12 standard library and CPython `Lib/test`: 685,710 inputs, identical definitions and uses, in the same order (the one input the old code crashed on was skipped).
- `ast_node_to_dict`, `ASTNode` and `ProgramPoint` had one caller (`/parse`, through the recursive `asdict`), so they are replaced by `ast_to_json`, which builds the same dictionaries directly. Checked equal to the old output on 62 files, and to a recursive reference in the tests.
- `iter_ast_edges` replaces the three recursive drawers. The AST drawing's Graphviz source is identical to before (after renumbering tree-sitter node ids, which differ per run). The CPG drawings are equal as multisets of labelled nodes, edges and clusters: their text order differs between two runs of the *same* code, before and after this change, so text comparison is not meaningful for them.
- `find_nodes_containing_position` is iterative too (no caller today); checked against the old version.
- `test/test_deep_nesting.py` (101 tests): 12 deep programs (8 Python, 2 C, 2 Java, all deeper than the recursion limit) through the builder and dataflow, `/parse`, and five CLI drawing modes with Graphviz's layout stubbed; exact results for the Python ones (all 1,500+ chained targets defined, all operands used, all nested calls recorded); the 800-target chain from `test_traceback.py`; and the helpers against recursive references on ordinary code.
- Mutation-checked with 7 deliberate bugs (recursion put back into the collector, `ast_to_json` and `iter_ast_edges`; child order reversed; breadth-first edge order; `named_only` ignored; containing-node order reversed). Six fail tests; putting recursion back into `ast_to_json` made the run hang (the walk became exponential), and I killed it after 26 minutes rather than seeing it fail.
- CPython `Lib/test`: 1,314 of 1,314 files now pass (117 s, against 112 s before; the trampoline costs little).

### Behavior to know
- The analysis no longer crashes on deep expressions, but Graphviz's own layout of a very deep AST is slow: drawing the AST of a 1,200-term sum took 50 s. That is outside our code.
- The test file adds about 20 s to the suite, mostly C and Java programs with 1,500 declared variables going through dataflow.
