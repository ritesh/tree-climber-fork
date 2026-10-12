# Link calls to functions defined later (2026-10-12)

Tracks GitHub issue #24 (TODO.md: "Handle forward declarations of function calls").

## Problem

`CFGVisitor.create_node` linked a call to the functions already registered in `context.function_definitions` at the moment the calling node was created. A call to a function defined later in the file got no `function_call` or `function_return` edge:

```python
def main():
    helper()        # not linked

def helper(): ...
```

The linking code is shared, so C, Java, and Python all behaved this way. Reading it also showed two more defects:

- It stopped after the first matching definition (`break`), so a statement calling two user functions (`a() + b()`) was linked to only one of them.
- The return edge's exit node was found by *name*, which is ambiguous when a name is defined more than once (overloads).

## Design

Move linking to `postprocess_cfg`, which runs after the whole tree is visited and every function is registered (`_link_function_calls`):

- For each node, link every distinct called name to every function of that name. A name defined more than once (Java overloads) is linked to all of them, since a call cannot be resolved to an overload here.
- Pair each function's entry with its exit by position in `cfg.entry_node_ids` / `cfg.exit_node_ids`. Every visitor appends a function's entry and then its exit, so the lists are aligned; each function therefore returns from its own exit.
- `create_node` now only records metadata (calls, definitions, uses).

## Behavior changes

- Forward calls are linked (the issue).
- A statement calling several user functions is linked to all of them.
- Overloads are all linked, each returning from its own exit.
- Name-based limits remain: `obj.run()` records `run` and can link to an unrelated function named `run` (as before).

## Tests

`test/test_function_call_linking.py`: forward, backward, two callees, mutual recursion, self recursion, and undefined callees for C, Java, and Python; plus Java overloads with a check that each return edge comes from the callee's own exit.

## Results

Executive summary: calls link regardless of definition order, in all three languages. CI-equivalent checks pass locally (`ruff format --check`, `ruff check`, `pyright`, `pytest`: 335 passed, 20 xfailed; was 316). No existing test changed, and the 20 strict xfails still fail as expected.

- 19 new tests. Run against the old linking code, 10 fail (forward calls, two callees, mutual recursion, overloads); the other 9 are regression cases that pass either way. Mutation-checked with 5 deliberate bugs, each applied and each caught.
