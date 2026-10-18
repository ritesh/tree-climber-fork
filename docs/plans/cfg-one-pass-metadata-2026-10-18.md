# CFG construction: one pass for each node's metadata (#86), 2026-10-18

## Problem
CFG construction is the largest stage on ordinary code (79 s of about 170 s on CPython `Lib`). On `Lib/test/test_typing.py`, 60% of the build is `CFGVisitor.create_node` collecting metadata: `get_call_sites`, `get_definitions`, `get_uses` and `get_direct_uses` each walk the node's subtree separately. Another 24% is `_function_info`, where `declared_scope_names` runs twice per function. `get_source_text` decodes bytes 99k times. C shows the same pattern in `process_use`, `dfs` and `call_sites.preorder`.

## Approach
- Profile the three languages on the stress corpora first, so the work goes where the time is.
- Give each visitor one metadata method that returns call sites, definitions, uses and direct uses from as few walks as possible. `create_node` calls it; the four getters stay as wrappers for existing callers.
- Compute `declared_scope_names` once per function and pass it to `collect_local_names`.
- Avoid repeated decoding of node text where it is hot.
- For C, replace the repeated `dfs`/`preorder` walks with the same single pass.

## Tests
- Oracle: on every fixture and on the stress corpora, the metadata of every CFG node (calls, call sites, definitions, uses, direct uses) equals the metadata from master's path.
- The existing suite, including `test/test_call_sites.py`.

## Measure
The profile of `test_typing.py` and `unicodeobject.c`, and the stress runner's `cfg` stage on CPython `Lib` and the C sources, before and after.

## Results
Executive summary: CFG construction is 1.5× faster on CPython `Lib`, 1.6× on CPython's C sources and 2.2× on commons-lang (Java). Every CFG is unchanged: nodes, edges and all metadata hash identically to master's on all three corpora and the test files.

The `cfg` stage, summed over 4 workers, two runs each (master's code forced onto the path with `PYTHONPATH`, since the venv's editable install points at the checkout):

| Corpus | Files | master | this branch |
|---|---|---|---|
| CPython 3.12.7 `Lib` | 1,790 | 67.5 s, 70.4 s | 44.9 s, 47.4 s |
| CPython 3.12.7 `Objects`, `Modules`, `Parser`, `Python` | 612 | 28.8 s, 32.6 s | 20.3 s, 18.7 s |
| apache/commons-lang `src` | 630 | 13.7 s, 14.2 s | 6.4 s, 6.1 s |

- **One entry point.** `CFGVisitor.node_facts` returns call sites, definitions, uses and direct uses together (`NodeFacts`), and `create_node` calls it. By default it calls the four getters, so a new language needs nothing more.
- **C and Java: one walk.** `call_sites.Occurrences` walks a node's subtree once. It records each use with its preorder position and nearest enclosing call, each definition, each call, and the preorder span of every node. The uses under any argument or receiver are then a slice of the walk's, and a use is direct for a subtree when its nearest call lies outside it. The language only says which node types can be uses or definitions, so its callbacks run on few nodes. The getters are wrappers that walk only the node they are given. `uses_outside_calls` and `outermost` are gone.
- **Python: fewer walks.** The call nodes are found once and passed to `call_sites`. The bindings collector records direct uses as it goes (uses seen while it is inside none of those calls), so one walk gives definitions, uses and direct uses, instead of a walk for each. Each argument's uses and direct uses also come from one walk instead of two.
- **Python functions: one walk of the body.** The collector that finds a function's locals now records its `global` and `nonlocal` names too. `function_scope_names` replaces `collect_local_names` and `declared_scope_names`, which walked the body three times between them.
- **Passthrough.** `_passthrough_entry_exit_nodes` tested membership in the lists of function entries and exits for every node. It now uses a set. That took 0.13 s of `test_typing.py`'s 1.6 s.
- **Not done:**
  - caching decoded text: `get_source_text` is now about 6% of a Python build;
  - merging the walks of the call sites and of the bindings in Python. Argument uses are computed without the enclosing scope (a lambda's parameter is still a use of the argument), so they cannot be slices of the statement's walk. This is what is left between Python and the 2× the issue estimated.
- **Tests** (in `test/test_call_sites.py`):
  - `node_facts` equals the four getters on every CFG node of every fixture, in all three languages;
  - for C and Java, `Occurrences` built at the root gives, for every AST node of the fixtures, the uses and definitions of a separate walk of that node, and the direct uses of the old formula (all uses minus those of the outermost calls);
  - for Python, the bindings walk's direct uses equal `direct_uses` on every AST node of the fixtures;
  - `function_scope_names` gives locals, globals and nonlocals in one collector run, and ignores the declarations of nested functions and classes.
- **Mutation check:** 7 mutants (the nearest-call test, the call index, span ends, the call depth and its reset, the argument cache, the global/nonlocal split), all caught. The last one survived until the test of the nested function was added.
- **Checks:** ruff format and lint are clean, pyright reports 0 errors, and the suite gives 2,114 passed, 39 xfailed.
