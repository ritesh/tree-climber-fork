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
