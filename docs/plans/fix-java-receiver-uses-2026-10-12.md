# Fix Java receiver uses (2026-10-12)

Tracks GitHub issue #23.

## Problem

`JavaCFGVisitor.get_uses` skipped every identifier whose parent was a `method_invocation` or `field_access`. That removed the method or field *name* (intended) and also the receiver object (a bug): `list.add(x)`, `o.run()`, `int y = o.field`, and `o.name.trim()` recorded no use of `list` or `o`. Parameters and locals therefore had no def-use edges to the calls and field reads made on them.

## Design

Skip only the name: the `name` field of a `method_invocation` and the `field` field of a `field_access`. The receiver (`object` field) stays a use, including as the target of a write (`o.f = x` uses `o`).

## Known noise

A class name used as a receiver (`System` in `System.out.println(y)`, `Math` in `Math.max(a, b)`) is reported as a use, because a name cannot be resolved to a type here. It has no reaching definition, so it adds no edge. Python reports builtins the same way.

## Not changed

Writes through fields and arrays (`o.f = x`, `arr[0] = x`) define nothing in Java, whereas C and Python treat them as weak updates. That is a separate enhancement, tracked on its own issue.

## Tests

`test/java_cfg/test_java_bindings.py`: table-driven definitions and uses (receivers, chains, static calls, unchanged plain statements) and end-to-end def-use chains through the solver.

## Results

Executive summary: receivers of method calls and field accesses are uses. CI-equivalent checks pass locally (`ruff format --check`, `ruff check`, `pyright`, `pytest`: 335 passed, 20 xfailed; was 316). No existing test depended on the old behavior.

- 19 new tests, mutation-checked with 4 deliberate bugs (both original skips reintroduced, and each name check removed), each applied and each caught.
