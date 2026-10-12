# Python visitor skeleton (2026-10-12)

Tracks GitHub issue #5, part of the Python support epic (#1). Depends on the language registry (#4, merged).

## Scope

`src/tree_climber/cfg/languages/python.py` with `PythonCFGVisitor(CFGVisitor)` covering straight-line code and function definitions:

- `module`, `function_definition` (incl. `async def`), `block`, `expression_statement`, `pass_statement`, `return_statement`, comments.
- `get_calls` for `call` nodes.
- Registered in the language registry (`.py`, `.pyi`).
- `docs/grammars/python/node-types.json`, as for C and Java.
- Fixtures and tests under `test/python_cfg/`.

Everything else in the grammar (`if`, loops, `try`, `with`, `match`, `class`, ...) is handled by later issues (#7-#11).

## Design

**Module.** A module is a program with its own top-level flow, and each `def` is a separately callable flow, as C's translation unit holds several functions.
- Top-level statements other than `def` are chained between a `<module>` ENTRY/EXIT pair.
- That pair exists only when the module has such statements, or when the file is empty (so the CFG is never empty). A file containing only `def`s does not get an isolated two-node component.
- `def`s are visited in source order but are not part of the module chain: defining a function does not run its body. Visiting in source order matters because call edges are only linked to functions registered earlier (the same limitation as C and Java; see "Old list" in TODO.md).

**Function.** ENTRY (named after the function, `ast_node` = the parameters node, parameter names recorded as definitions as C does), a `block` body, EXIT (`source_text` = function name, which `CFGVisitor.create_node` uses to attach function-return edges). The function's exit is pushed on `context.exit_node_ids`; `return` connects to `context.exit_node_ids[-1]`, not `cfg.exit_node_ids[-1]` as C does, so nested functions (#10) resolve to the right exit.

**Parameters.** `identifier`, `default_parameter`, `typed_parameter`, `typed_default_parameter`, `list_splat_pattern` (`*args`), `dictionary_splat_pattern` (`**kwargs`). The bare `*` and `/` separators are ignored.

**Calls.** `call` whose function is an `identifier` records the name; whose function is an `attribute` records the final attribute name (`obj.method()` -> `method`, `pkg.mod.fn()` -> `fn`), the way Java does. Other callees (`f()()`, `table[k]()`) record nothing for the outer call; the inner call is still found. Known limitation shared with Java: `obj.run()` can link to a module-level `run`.

**Unsupported statements.** The base `generic_visit` flattens a compound statement into a chain of its leaf expressions, which silently invents wrong control flow. The Python visitor overrides `generic_visit` so any statement without a handler becomes a single STATEMENT node containing its full text and flows straight through. Later issues replace this per construct. `get_definitions`/`get_uses` return empty lists until #6, except that function parameters are recorded as definitions on the ENTRY node.

## Tests

`test/python_cfg/test_python_cfg.py` with `basic_constructs.py` as a fixture (its header documents it): straight-line module, defs-only module, empty module, parameter kinds, `return` jumping to exit with unreachable code after it, docstring/comment/`pass`, call and return edges, call-name extraction for each callee shape, and an unsupported-statement test that checks the flow stays connected. The registry tests already cover Python generically once it is registered; extension cases are added.

## Out of scope

Def/use (#6), control flow (#7), exceptions/`with` (#8), `match` (#9), classes/nested functions/lambdas/decorators (#10), comprehensions/generators/async constructs (#11), frontend/README wiring (#12).

## Results

Executive summary: Python is a registered language. `PythonCFGVisitor` builds CFGs for straight-line code and function definitions, with call and return edges. CI-equivalent checks pass: `ruff format --check`, `ruff check`, `pyright`, `pytest` (182 passed, 20 strict xfails; was 137 passed).

- `src/tree_climber/cfg/languages/python.py`: module, function definition (incl. `async def`), block, return, comments, call extraction, parameter extraction. Every other statement is one opaque STATEMENT node via an overridden `generic_visit`.
- Registered in the language registry (`.py`, `.pyi`), so the CLI (`tree-climber file.py`, `--language python`) and API (`/parse`) accept Python with no further changes. Verified end to end with the CLI: AST and CFG images are produced for the fixture and read correctly.
- `docs/grammars/python/node-types.json` is the tree-sitter-python `v0.20.4` file. I checked it against the bundled grammar: node kinds and field names are identical apart from hidden supertypes, while `v0.20.2` and `v0.23.x` differ. `v0.21.0` ships the same file.
- Tests: `test/python_cfg/test_python_cfg.py` (36 tests) with `basic_constructs.py` as a fixture; registry and API tests extended for Python. Mutation-checked: dropping return-to-exit, attaching default-value calls to the entry, ignoring typed parameters, and pointing returns at the wrong exit each fail a test. One test that caught nothing was removed.
- Fixed a test from #4 that hardcoded the language list `["c", "java"]`; it now compares against the registry.

### Behavior to know
- Def/use is not implemented yet (#6): `get_definitions`/`get_uses` return empty lists, so Python DFG output is empty until then. Function parameters are the exception; they are recorded as definitions on the ENTRY node, as C does.
- Calls only link to functions defined earlier in the file (the same limitation as C and Java; see "Old list" in TODO.md). `obj.run()` records `run` and can link to a module-level `run`, as in Java.
- Graphviz renders the node text `<module>` as `module` (angle brackets dropped). The name stays `<module>` so it cannot collide with a user function named `module` when return edges are matched by exit text.
