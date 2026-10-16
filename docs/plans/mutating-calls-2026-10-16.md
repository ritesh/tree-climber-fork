# Values added by a method call (#75), 2026-10-16

## Problem
A method call never defines its receiver, so what `items.append(x)` or `sb.append(x)` puts into an object is lost to def-use chains, slices and taint: a later read of `items` reaches the definition before the call.

## Plan
- A call to a mutating method is a weak update of its receiver, like a subscript or attribute write: the statement defines the receiver's root name, and it already reads it (the receiver is a use), so the earlier definition flows through.
- Which methods: a list per language, on the visitor (`MUTATING_METHODS`), so `os.system(x)` or `logger.info(x)` does not redefine `os` or `logger`:
  - Python: `append`, `extend`, `insert`, `add`, `update`, `setdefault`, `appendleft`, `extendleft`;
  - Java: `add`, `addAll`, `addFirst`, `addLast`, `put`, `putAll`, `putIfAbsent`, `append`, `insert`, `set`, `push`, `offer`, `offerFirst`, `offerLast`;
  - C: none (no methods).
- The root is the leading name of the receiver when the receiver reads it outside any call: `items` in `items.append`, `self` in `self.items.append`, `d` in `d["k"].append`; not `get().append` or the outer call of `sb.append(a).append(b)` (the inner one defines `sb`).
- Done once, in `CFGVisitor.create_node`, so every visitor and every consumer (def-use, slices, queries, taint) sees it. The taint engine needs no change: a definition takes the statement's taint, which includes the receiver's earlier taint through the unknown call.
- Docs: the weak-update paragraph and the approximations in the Python guide. Corpus: the two `todoruleid` cases (#75) become `ruleid`.

## Tests
Python and Java: each listed method defines the receiver; other methods and plain calls do not; attribute and subscript receivers define their root; a call receiver does not; chained calls; the earlier definition still flows through; a mutation in one function reaches a use of a global in another (free-variable flow); taint through `append`, `extend`, `update`, `add` and Java `StringBuilder.append`/`List.add`.

## Results
Executive summary: a call to a mutating method now defines its receiver's root name, a weak update like `d["k"] = v`. `CFGVisitor.create_node` adds the definition for every language, from a per-visitor `MUTATING_METHODS` list (8 Python methods, 14 Java ones, none for C). Def-use chains, slices, free-variable flows and taint all see it; the taint engine is unchanged. The two #75 corpus cases are now expected findings, and 8 cases were added.
- Corpus: `extend`, `update`, `add` on an attribute, taint kept across a clean `append`, an unlisted method (`count`, `ok`), a global mutated in one function and read in another, Java `List.add` and a clean `StringBuilder`. A receiver returned by a call (`table.get(...).append(...)`) is a new `todoruleid`: only a receiver read by name is updated.
- Tests: 38 in `TestMutatingCalls` (`test_call_sites.py`): every listed method in Python and Java, calls that must not define anything (including C), root names through attributes, subscripts and chains, a name listed once, the def-use chain through the call, and a free-variable flow; one Java chain test updated (`list.add(x)` now defines `list`).
- Mutation check: 6 mutations; one survived at first (the duplicate check) and got a test; all caught.
- CPython `Lib` stress run: 1,790 files, no failures, data flow and taint times unchanged.
- Checks: ruff format and lint clean, pyright 0 errors, 1,920 passed, 40 xfailed.
