# C: a comment right after a label (#58), 2026-10-15

## Problem
`visit_labeled_statement` takes the first child that is not the label or `:` as the labeled statement. A comment can be that child; visiting it gives no result, and the builder crashes (`'NoneType' object has no attribute 'entry_node_id'`). `test/c_cfg/real_world_patterns.c` and CPython's `Lib/test/clinic.test.c` both fail this way, so the fixture is skipped by the test that builds every fixture.

## Plan
- Pick the first named child that is neither the label nor a comment.
- Tests: a line comment and a block comment between a label and its statement (the label leads to the statement, the goto to the label), consecutive labels, a label at the end of a block (C23; tree-sitter recovers with an empty statement), and stop skipping `real_world_patterns.c` in the fixture-wide test.

## Results
Executive summary: the labeled statement is now the first named child that is not the label or a comment. `real_world_patterns.c` and CPython's `clinic.test.c` build, and the fixture-wide call-site test no longer skips `real_world_patterns.c`.
- New tests in `test/c_cfg/test_c_cfg.py`: a line comment, a block comment and both between a label and its statement (the label leads to the `return`), consecutive labels, and a label at the end of a block. Without the fix, the three comment cases and the fixture-wide test fail; the other two passed before and guard the behavior.
- Checks: ruff format and lint clean, pyright 0 errors, 1,705 passed, 20 xfailed.
