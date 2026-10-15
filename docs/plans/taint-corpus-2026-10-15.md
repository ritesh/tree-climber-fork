# Taint test corpus with known flows (#51), 2026-10-15

## Problem
The taint engine is tested case by case in `test/taint/`. There is no corpus of programs with the expected findings written next to the code: one place that says, for each language, what is found, what must not be, and what is a known limitation, and that grows with each bug report.

## Plan
- `test/taint/corpus/{python,c,java}/`: small programs, each with a header saying what it covers (CLAUDE.md), annotated in the style of semgrep's rule tests. The comment goes on the line before the sink call:
  - `ruleid: <rule>`: a finding of that rule on the next line is expected;
  - `ok: <rule>`: no finding of that rule there;
  - `todoruleid: <rule> -- <reason>`: a real flow the analysis misses (a known false negative), a strict xfail;
  - `todook: <rule> -- <reason>`: a finding that is wrong (a known false positive), a strict xfail.
  A header line `taint-options: field_sensitive implicit_flows` turns options on for one file. The rules are the built-in ones (`builtin_rules(language)`), so the corpus also checks them.
- `test/taint/test_taint_corpus.py`: one test per annotation (so known limitations are strict xfails and turn into failures when fixed), plus one per file checking that every finding is annotated, so a new false positive cannot slip in unnoticed.
- Cases: first the #44 prototype's (flows through assignments, loops, `try`, `with`, subscripts, reassignment kills, and the two it missed: calls and `eval(escape(x))`), then per language: true positives (direct, assignments, loops, branches, calls, returns, containers), true negatives (reassignment, sanitizers, constants, parameterized queries), and the limitations the guides document. The cases are written here, not copied: semgrep-rules' licence restricts reuse, so the categories of semgrep-rules and CodeQL's CWE tests guide what is covered without copying code.
- `test/taint/corpus/README.md`: the annotation format only (#51 asks for a minimal README).

## Results
Executive summary: `test/taint/corpus/` holds 13 annotated programs (8 Python, 3 C, 2 Java) with 127 annotations: 76 expected findings, 30 places that must stay clean, and 21 known limitations as strict xfails (12 missed flows, 9 wrong findings), each with its reason. `test/taint/test_taint_corpus.py` checks every annotation, that every finding is annotated, and that annotations are well formed (a known rule id; a reason exactly on `todo` annotations). Writing the corpus found two gaps no guide lists, filed as #75 (values added by a method call such as `append` are lost) and #76 (names a `match` pattern binds do not take the subject's taint).

| Language | Files | ruleid | ok | todoruleid | todook |
|---|---|---|---|---|---|
| Python | 8 | 56 | 18 | 5 | 7 |
| C | 3 | 11 | 7 | 4 | 1 |
| Java | 2 | 9 | 5 | 3 | 1 |

- Python: `assignments.py` and `control_flow.py` (the #44 prototype's cases), `calls.py` (the flows it missed, and `eval(escape(x))`), `containers.py` and `field_sensitive.py`, `sources_and_sinks.py` (every built-in source and sink, query parameters), `implicit_flows.py`, `limitations.py`. C: `command.c`, `format.c`, `limitations.c`. Java: `Search.java` (SQL), `Command.java` (commands and the #32 limitations).
- One expectation I wrote first was wrong, and the analysis was right: a `raise` before `command = input()` means the `except` block never sees input, so that case is `ok`.
- Also found: with `field_sensitive`, a constant written over a tainted field is still a weak update (`todook`), and a tuple assignment taints every name it defines unless a call is assigned to it alone (`todook`); both match what the guides say.
- Harness check: an expected finding marked `ok`, a missing annotation, a `todo` whose case now passes, a `todo` without a reason, a reason on a `ruleid`, a misspelt rule and a finding of another rule each fail the tests (7 of 7).
- The corpus is excluded from ruff and pyright (its programs use undefined names on purpose), as the other fixture files are.
- Checks: ruff format and lint clean, pyright 0 errors, 1,833 passed, 41 xfailed (21 of them the corpus's known limitations).
