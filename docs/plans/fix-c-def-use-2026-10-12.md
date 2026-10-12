# Fix C def/use extraction (2026-10-12)

Tracks GitHub issue #22.

## Problem

`CCFGVisitor.get_definitions` took the first *direct* `identifier` child of an `assignment_expression` or `init_declarator`, and `get_uses` skipped identifiers by parent type. That is wrong far beyond the cases in the issue. Measured on `master`:

| Statement | definitions (before) | uses (before) |
|---|---|---|
| `int *q = p;` | `p` (the source!) | `q`, `p` |
| `a[0] = x;`, `s.f = x;`, `p->g = x;`, `*p = x;` | `x` (the value written!) | |
| `int x;` | | `x` |
| `int a[n];` | | `a`, `n` |
| entry of `f(int *p)` | `p` | `p` |

## Design

- **Declarators.** Read the `declarator` field and unwrap `*p`, `a[n]`, `(*fp)(int)` to the declared identifier (`_declared_identifier`). A parenthesized declarator has no field name for its content, so it is unwrapped by position (`_wrapped_declarator`). A declared name is never a use (`_is_declared_name`); array sizes and initializers still are.
- **Assignment targets** are read from the `left` field (`_written_variable`), with the same weak-update rule the Python extractor uses:
  - `x = ...` defines `x`.
  - `s.f = ...` and `a[i] = ...` define *and use* the root variable, because the reaching-definitions framework only has strong updates.
  - `p->f = ...` and `*p = ...` change the pointee, not `p`, so they define nothing and use `p`.
  Increments (`a[i]++`) use the same rule.
- **Parameters** on the function entry use the same declarator unwrapping, which also fixes `int **pp` and `char *q[]` parameters being dropped.
- `int x;` defines nothing (declared, not initialized), as before.

## Not changed

No alias analysis: `*p = v` does not flow into whatever `p` points at.

## Tests

`test/c_cfg/test_c_bindings.py`: table-driven definitions and uses for declarations, name assignment, weak updates, pointer writes, parameters, and end-to-end def-use chains through the solver.

## Results

Executive summary: C definitions and uses are correct for declarators and assignment targets. CI-equivalent checks pass locally (`ruff format --check`, `ruff check`, `pyright`, `pytest`: 349 passed, 20 xfailed; was 316). No existing test depended on the old behavior.

- 33 new tests. Mutation-checked with 8 deliberate bugs (including each of the original defects reintroduced), each applied and each caught.
- The bug was broader than the issue as filed: any non-identifier assignment target defined the right-hand side, and any pointer initializer defined its source. Issue #22 is updated by this PR's description.
