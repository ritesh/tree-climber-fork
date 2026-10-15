# C builder crashes on real-world code (#64), 2026-10-15

## Problem
On 1,509 C files (CPython 3.12.7's C sources and the 696 `.c` files in the dev container), the C CFG builder fails on 151 (with #58 fixed):
- 115: `for` loops with an empty clause (`for (;;)`, `for (; i < n;)`): `visit_for_statement` requires `initializer`, `condition` and `update`.
- 33: definitions whose signature is written by macros. `ENCODER(gb2312) {`, K&R `main(c) {`, and `PyThread_exit_thread(void)` with its return type on a macro line all parse as type `NAME` with a parenthesized declarator; `f PARAMS {` parses as a bare identifier. There is no function declarator, so the builder raises.
- 3: `break` or `return` with no enclosing loop, switch or function, all in code tree-sitter recovered from an error (a `TRANS(name)(...)` signature splits a function, so a `case` and its `break` end up outside the `switch`).

Separately, preprocessor conditionals inside a function are visited as a plain sequence (the generic visitor): both `#if` and `#else` branches run one after the other, so a definition in `#else` kills the one in `#if`, and the `#ifdef` name becomes a statement node.

## Plan
- `for`: each clause optional. No initializer: start at the header. No condition: a loop header with the text `(no condition)` that keeps its `false` edge, as `while (1)` does. No update: `continue` and the end of the body go back to the header.
- Macro signatures: when there is no function declarator, a type identifier followed by a parenthesized declarator is the function name and its parameter (`main(c)`, `ENCODER(x)`; `(void)` is no parameter); a bare identifier is the name with no parameters.
- `break`, `continue` and `return` with no target: a node of the same type that falls through to the next statement, instead of an assertion. This only happens in error-recovered code.
- Preprocessor conditionals inside a function (`#if`, `#ifdef`, `#ifndef`, with `#elif`/`#else`): a branch. A `CONDITION` node with the directive's text and no AST (it reads no variables), a `true` edge to the first group, a `false` edge to the `#elif`/`#else` (or past the block when there is none). Outside functions the current behavior stays.
- Stress: add CPython's C sources (`Modules`, `Objects`, `Python`, `Parser`) at the same pin to the weekly workflow, with `--language c`.

## Tests
Each fix in `test/c_cfg/test_c_cfg.py`: every combination of missing `for` clauses (edges, `continue` target, `break`), the macro signature shapes (name, parameters, call linking), a `break`/`return` in recovered code, and preprocessor branches (`#ifdef`/`#else`, `#if`/`#elif`/`#else`, no `#else`, nested, a `case` inside `#if` in a `switch`, a definition in each branch reaching a later use, top-level conditionals around functions unchanged).
