# Taint analysis (#48), 2026-10-13

Part of #44. Builds on structured call sites (#45), interprocedural flow (#46) and the query API (#47).

## Problem
The query-layer tracker (`test/query/test_query_taint.py`) is statement-level: a statement's uses all flow into all its definitions, and a sanitizer is a node to avoid. So `eval(escape(x))` is flagged (the node is both sanitizer and sink), `cmd = "ls " + escape(name)` is flagged, and a tainted second argument cannot be told from a first. #48 asks for call-site-level sanitizers, argument positions for sinks, sources beyond call names, a rule format, findings as data, and flow across calls.

## Part 1: what each argument reads outside nested calls
To decide whether `escape(x)` protects `x`, the analysis must know that `x` is read only inside the call. `CallArgument.uses` includes the uses of nested calls (and Python de-duplicates them, so they cannot be subtracted). New metadata, additive, defaulting to None (= unknown, treat every use as direct):
- `CallArgument.direct_uses`: what the argument reads outside any call inside it (`x + escape(y)` reads `x` directly).
- `CallSite.receiver_uses`: what the receiver reads outside calls (`a` in `a.b().c()`; nothing for `escape(x).strip()`).
- `CFGNodeMetadata.direct_uses`: what the node reads outside every call (`y = x + escape(z)` reads `x`).

Python: the uses collector with every call node pre-cached as reading nothing. C and Java: their uses lists count every occurrence, so direct uses are the subtree's uses minus the uses of the outermost calls under it. Python nodes whose uses are special-cased (definitions, `for` headers, `case` patterns) set it accordingly or leave it None. Not added to `to_dict()` (an existing test pins the argument dict; exposure belongs to #50).

## Part 2: `tree_climber.taint`
- **Rules** (`rules.py`): `Rule(id, description, sources, sinks, sanitizers, languages)`, in a `RuleSet`, from Python, a dict or JSON (YAML when PyYAML is installed; it is not a dependency).
  - Sources: `Source(call=pattern)` (the call's result), `Source(parameter=name or index, function=pattern)`, `Source(attribute="request.args")` (an attribute access, matched in the text).
  - Sinks: `Sink(call=pattern, arguments=[0, "sql"])`: positional indexes and keyword names; None means every argument.
  - Sanitizers: `Sanitizer(call=pattern)`: the call's result is clean.
  - A call pattern is a glob matched against the callee name (`system`) or the whole callee expression (`os.system`, `*.execute`).
- **Engine** (`engine.py`): a worklist over tainted values, one run per source occurrence so each finding has one source.
  - Inside a node, call results are computed innermost first: a source call is tainted, a sanitizer is clean, a call to a function defined in the file is tainted when one of its returns is (context-insensitive), and any other call passes taint from its arguments and receiver through. An argument is tainted by a tainted direct use or a tainted nested call that is the argument.
  - A variable a call is assigned to (`x = f(...)`) takes the call's taint; other definitions take the statement's (a tainted direct use or a tainted top-level call). A weak update (`d[k] = ...`, `x += ...`) keeps the variable's earlier taint. A `return` takes the statement's taint.
  - Between nodes: def-use chains (so reassignment kills), and #46's argument, return and free-variable flows.
  - A sink is reported when a watched argument is tainted.
- **Findings** (`Finding`): rule id, source node, sink node, sink call, argument, and a `Path` (the query API's type) with the edge kind (`def_use`, `argument`, `return`, `free_variable`) and variable of each step. `to_dict()` for JSON.
- **Built-in rule sets** (`builtin_rules(language)`), marked as examples: command injection, code injection (`eval`/`exec`), SQL string building, for Python, C and Java.

## Soundness, stated
Over-approximates: unknown calls pass taint through; containers and objects are whole (`d["k"] = tainted` taints `d`); free variables are flow-insensitive; calls are resolved by name and context-insensitively. Under-approximates: aliasing (two names for one object), output parameters (`fgets(buf, ...)` does not taint `buf`), dynamic features, implicit flows through branches (#49), calls through function pointers or `getattr`. Attribute sources are matched as text.

## Tests
The #44 prototype cases (all of `test_query_taint.CASES`), including `eval(escape(x))` (no finding) and the flow across a call (found); argument positions and keywords; sanitizer placement (`"ls " + escape(x)`, `escape(x) + x`, `x = escape(x)`); parameter, attribute and call sources; weak updates; flows through returns, closures, methods; C and Java; rule loading and validation; built-in rule sets on small vulnerable/safe programs; finding paths and JSON. Mutation-checked.

## Results

Executive summary: `tree_climber.taint` finds flows from sources to sinks at the level of call sites, across calls, for Python, C and Java, with rules in Python, dicts or JSON and example rule sets. Every #44 prototype case behaves as #48 asks: `eval(escape(x))` is no longer flagged, and the flows across calls (`argument_to_callee`, `return_value` in the fixture, and `not_across_calls`) are found. `ruff format --check`, `ruff check`, `pyright`, `pytest` pass (1485 passed, 20 strict xfails).

- **Metadata**: `CallArgument.direct_uses`, `CallSite.receiver_uses`, `CFGNodeMetadata.direct_uses` for all three languages (17 tests in `test_call_sites.py`, plus an invariant in the per-fixture check: direct uses are a subset of uses, and equal them when a node has no calls). On the standard library (207k nodes, 110k arguments) the invariant holds everywhere; building is about 25% slower (18 s to 22 s for the whole library).
- **Tests**: `test/taint/test_taint_engine.py` (65) and `test_taint_rules.py` (21): every prototype case and the fixture, sanitizer placement, weak updates, argument positions and keywords, nested calls, receivers, the three source kinds (attributes in strings, comments, writes, wildcards, repeated texts), flows into and out of functions, sanitizing functions, closures, globals, objects, one origin per run, C and Java, findings and JSON, rule matching, validation, loading and round trips, the built-in rules on vulnerable and safe programs in each language, and the guide's examples.
- **Mutation-checked** with 65 deliberate bugs across the engine, the rules, the built-in rules and the metadata. The first runs left 12 alive; 9 were real gaps and were killed by new tests (a source call outside its origin, unknown uses counting as direct, nested call positions, assignment versus statement taint, the receiver as a sink argument, attribute subtraction, the wildcard, star arguments, nested calls two levels deep in C and Java). 3 are equivalent: the RETURN check (only return nodes have return flows), the module-entry check (removed: a module has no parameters), and keeping the first or the last finding value (a value's path is fixed when it is first marked).
- **Standard library** with the Python example rules: 1,081 files, no errors, 36 s of analysis (at most 0.6 s for one file), 45 findings. Looking at them, they are real flows of command-line arguments, environment variables and `input()` into `exec`, `eval`, `os.system` and `subprocess` (IDLE, pydoc, timeit, runpy, webbrowser), plus false positives from objects and containers being whole values (`self.debug = ...` taints `self`) and from context-insensitive returns. Two kinds of false positives found this way were fixed: attribute sources inside string literals and comments, and statements that write to the attribute (`sys.argv[0] = x`, which taints the whole `sys` module as a weak update). Call patterns now match the whole callee only (`eval` no longer matches `self.tk.eval`).

### Behavior to know
- The built-in rules are examples: `subprocess.*` without a shell is flagged although only argument injection is possible; C output parameters (`snprintf(cmd, ...)`) are not followed, so the C example misses `system(cmd)` after `snprintf`.
- A module-level `def` without decorators is not a statement in the module's flow (by the CFG's design), so its default values do not carry taint.
- Findings are per source occurrence, sink call and argument; the path is the first one found, not necessarily the shortest.
- The new metadata is not in `to_dict()` / `/parse`; that belongs with #50.
