# Python `match` statement (2026-10-12)

Tracks GitHub issue #9, part of the Python support epic (#1). Builds on control flow (#7) and exceptions (#8).

## Scope

`match_statement` with `case_clause`s: literal, capture, wildcard, sequence, mapping, class, value (`Color.RED`), `|` (union), and `as` patterns, and `if` guards.

## Design

The shape follows the `if`/`elif` chain, not C's `switch`: Python has no fall-through and no `break`, and exactly one case runs, or none.

- **Head.** A `SWITCH_HEAD` node `match <subject>` evaluates the subject once (it uses the subject's names and may raise).
- **Case test.** One `CONDITION` node per clause, `case <pattern>`. `true` enters the body, `false` tries the next case. It uses the classes and dotted values the pattern reads (`Point`, `Color` in `Color.RED`). It cannot raise (like except-clause headers, this avoids doubling every edge into the chain).
- **Captures.** Names a pattern binds (`[a, *rest]`, `{"k": v, **kw}`, `Point(x=px)`, `as pt`) are defined by a `capture a, rest` statement node on the `true` edge, only when the pattern captures anything. Defining them on the test node itself would kill earlier definitions on the no-match path (`x = 0; match s: case [x]: ...; print(x)` must still see `x = 0`).
- **Guard.** An `if <cond>` `CONDITION` node after the capture. Its `false` edge tries the next case; the captured names stay bound, as in Python.
- **No match.** When no case is irrefutable, the last `false` edge goes to the statement after the match. Irrefutable patterns are `_`, a bare name, a parenthesized one, or an `as`/`|` pattern containing one; with a guard a case is never irrefutable. An irrefutable case has no `false` edge.
- **Jumps.** `break`/`continue` in a case body target the enclosing loop (the match pushes no loop context); `return` and exceptions behave as in any block.

Pattern bindings live in `python_bindings.py` (`collect_pattern_bindings`, `is_irrefutable_pattern`). The grammar bundled here (tree-sitter-python ~0.20.4) parses `(name)` as a one-element `tuple_pattern`, so a tuple pattern without a comma is treated as a group.

## Tests

`test/python_cfg/test_python_match.py`: edge sets for each shape above, the `x = 0` no-match case as a def-use chain, guards, captures per pattern kind, irrefutable detection, `break`/`continue`/`return` in cases, a match in a `try`, and half-typed input. The unsupported-statement test no longer includes `match`.

## Out of scope

Classes, nested functions, lambdas, decorators (#10); comprehensions (#11). Exceptions raised by the pattern test itself (for example a class pattern's attribute lookup) are not modeled.

## Results

Executive summary: Python CFGs now model `match`/`case`. `ruff format --check`, `ruff check`, `pyright`, `pytest` pass (524 passed, 20 strict xfails; was 463 + 3 on master).

- `visit_match_statement` in `python.py` implements the design above; `collect_pattern_bindings` and `is_irrefutable_pattern` are in `python_bindings.py`.
- Design change made while testing: the first draft defined captured names on the case test node. That kills earlier definitions on the no-match path, so `x = 0; match s: case [x]: ...; print(x)` lost its `x = 0 => print(x)` chain. Captures now live on a `capture` node on the `true` edge, and a test covers exactly this case.
- `test/python_cfg/test_python_match.py` (61 tests): edge sets for each shape, guards, captures, jumps, exceptions, half-typed code, and per-pattern-kind bindings and irrefutability. The unsupported-statement test no longer includes `match` (its node count drops from 7 to 6).
- Mutation-checked with 27 deliberate bugs across `python.py` and `python_bindings.py`. The first run left survivors: case tests and capture nodes were not checked for exception edges (the edge leaves the head, not the case node, so my first assertion looked in the wrong place), `_` handling, and a dict-key branch. I fixed the tests; two survivors were dead code (the grammar parses `_` as an anonymous token, never an identifier, so the `!= "_"` checks could not trigger), which I removed. One mutation remains equivalent: skipping the attribute name of a keyword pattern, since the identifier case is not handled anywhere.
- Fuzzed with all 508 prefixes of a program mixing `match`, guards, `try`/`finally`, `with`, loops, and `break`/`continue`/`return`: no crashes.
- Python guide and README updated: `match` moves from opaque to modeled, with a new exercise.

### Behavior to know
- An irrefutable case has no `false` edge, and any case after it has no predecessor (Python rejects that code, and it appears only while typing).
- The test node for a case never raises (like except-clause headers). A guard and the subject do.
- A pattern that fails after binding some names (`case [a, 2]` against `[1, 3]`) is treated as binding nothing; `a` is not defined on that path. Python itself leaves it bound.
- The grammar parses `(name)` as a one-element tuple pattern; a tuple pattern without a comma is treated as a group.
