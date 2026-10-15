# C builder crashes on real-world code (#64), 2026-10-15

## Problem
On 1,509 C files (CPython 3.12.7's C sources and the 696 `.c` files in the dev container), the C CFG builder fails on 151 (with #58 fixed):
- 115: `for` loops with an empty clause (`for (;;)`, `for (; i < n;)`): `visit_for_statement` requires `initializer`, `condition` and `update`.
- 33: definitions whose signature is written by macros. `ENCODER(gb2312) {`, K&R `main(c) {`, and `PyThread_exit_thread(void)` with its return type on a macro line all parse as type `NAME` with a parenthesized declarator; `f PARAMS {` parses as a bare identifier. There is no function declarator, so the builder raises.
- 3: `break` or `return` with no enclosing loop, switch or function, all in code tree-sitter recovered from an error (a `TRANS(name)(...)` signature splits a function, so a `case` and its `break` end up outside the `switch`; a file that does not parse as a whole has an `ERROR` root, which the generic visitor walks statement by statement, outside any function).

Two more problems showed up on the same files:
- `visit_translation_unit` only visits function definitions that are direct children of the file, so every function inside a top-level `#if`/`#ifdef` group is silently skipped.
- Goto labels are kept for the whole file, so `goto fail;` in one function jumps to the `fail:` label of an earlier one (SWIG's generated code has one in every function). With an `ERROR` root, the generic visitor also chains the functions one after another (each function's exit leads into the next entry), so data flows between functions and reaching definitions need a pass per function (`graphviz_wrap.c`: 98 s).

Separately, preprocessor conditionals inside a function are visited as a plain sequence (the generic visitor): both `#if` and `#else` branches run one after the other, so a definition in `#else` kills the one in `#if`, and the `#ifdef` name becomes a statement node.

## Plan
- `for`: each clause optional. No initializer: start at the header. No condition: a loop header with the text `(no condition)` that keeps its `false` edge, as `while (1)` does. No update: `continue` and the end of the body go back to the header.
- Macro signatures: when there is no function declarator, a type identifier followed by a parenthesized declarator is the function name and its parameter (`main(c)`, `ENCODER(x)`; `(void)` is no parameter); a bare identifier is the name with no parameters.
- `break` and `continue` with no target: a node of the same type that falls through to the next statement, instead of an assertion (C rejects them, but tree-sitter parses them, and error recovery produces them).
- An `ERROR` root is built like a translation unit: its functions one by one, never chained, and loose statements outside functions are not built (as in a translation unit). Functions are also found inside top-level preprocessor groups and nested `ERROR` nodes.
- Goto labels belong to the function they are in.
- Preprocessor conditionals inside a function (`#if`, `#ifdef`, `#ifndef`, with `#elif`/`#else`): a branch. A `CONDITION` node with the directive's text and no AST (it reads no variables), a `true` edge to the first group, a `false` edge to the `#elif`/`#else` (or past the block when there is none). Outside functions the current behavior stays.
- Stress: add CPython's C sources (`Modules`, `Objects`, `Python`, `Parser`) at the same pin to the weekly workflow, with `--language c`.

## Tests
Each fix in `test/c_cfg/test_c_cfg.py`: every combination of missing `for` clauses (edges, `continue` target, `break`), the macro signature shapes (name, parameters, call linking), a `break`/`return` in recovered code, and preprocessor branches (`#ifdef`/`#else`, `#if`/`#elif`/`#else`, no `#else`, nested, a `case` inside `#if` in a `switch`, a definition in each branch reaching a later use, top-level conditionals around functions unchanged).

## Results
Executive summary: the C builder now builds all 1,509 C files of the corpus (CPython 3.12.7's `Modules`, `Objects`, `Parser`, `Python`, `Include` and the 696 `.c` files in the dev container) through every stage, where 151 crashed before. It also builds functions it used to skip (inside top-level `#if` groups, and in files that do not parse as a whole), keeps goto labels in their function, and treats preprocessor conditionals in a function as branches. The weekly `Stress` workflow gains a `cpython-c` job.

| | Before | After |
|---|---|---|
| Files that build (cfg) | 1,358 of 1,509 | 1,509 |
| All stages, 120 s per file | not measured (crashes) | 1,509, 65 s wall on 3 workers |
| Data flow, whole corpus | 1,417 s with 11 timeouts (after the crash fixes, before the label and `ERROR` fixes) | 28 s |
| `graphviz_wrap.c` (SWIG) | 98 s | 1.2 s |

- The last two fixes came from the timeouts, not from crashes: SWIG code has a `fail:` label in every function, so every `goto fail;` jumped to the first function's label; and in a file with an `ERROR` root, the generic visitor chained the 185 functions one after another. Either way data flowed between functions, and reaching definitions needed one pass per function.
- `return` outside a function: with an `ERROR` root built as a translation unit, a `return` is only ever visited inside a function, so the assertion stays as it was.
- Graphs of the existing C fixtures are identical before and after (node ids, types, text, edges and labels), checked by building every `.c` file under `test/`.
- Tests: 34 new cases in `test/c_cfg/test_c_cfg.py` (`TestRealWorldCode` and the macro-signature cases).
- Mutation check of the change: 23 mutations, 5 survived at first. They were the `(void)` parameter, the `type_identifier` check, an empty first preprocessor group, restoring the labels after a nested function, and functions inside a nested `ERROR`. Each got a test (the `(void)` shape needs `_Py_NO_RETURN`, as in CPython), and all 23 are now caught.
- Checks: ruff format and lint clean, pyright 0 errors, 1,739 passed, 20 xfailed.
