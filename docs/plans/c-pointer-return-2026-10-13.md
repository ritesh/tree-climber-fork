# C functions that return a pointer (#62), 2026-10-13

## Problem
`CVisitor.visit_function_definition` reads the function name and parameter list from the definition's `declarator` directly. That is a `function_declarator` only when the return type is not a pointer: for `int *f()` it is a `pointer_declarator` wrapping the `function_declarator`, so the `parameters` lookup raises and the whole file fails to build. A function returning a function pointer, `int (*g(int x))(int)`, is worse: the outer `function_declarator` is the returned type's, with parameters `(int)`, and its name would be `(*g(int x))`.

## Plan
Find the function's own declarator: walk from the definition's declarator through `pointer_declarator`, `parenthesized_declarator`, `function_declarator` (the existing `DECLARATOR_WRAPPERS`) and `attributed_declarator`, and take the innermost `function_declarator`. The name is the identifier inside its declarator, through parentheses and attributes (`int (f)(int a)` and `int f [[nodiscard]] (void)` were named `(f)` and `f [[nodiscard]]` on master, so calls to them did not link). No function declarator raises `ValueError`, as before.

## Tests
`int *f`, `int **f`, `const char *const f(void)`, `int (*g(int x))(int)`: the CFG builds, the function has the right name and parameters, calls to it link, and interprocedural argument flows reach its parameters. Pointer-returning functions added to a C fixture so the existing per-fixture checks cover them.

## Results

Executive summary: C functions that return pointers, function pointers, or have a parenthesized or attributed name now build, with the right name and parameters, so calls to them link and interprocedural flows reach them. `ruff format --check`, `ruff check`, `pyright`, `pytest` pass.

- **Tests**: 7 declarator shapes in `test_c_cfg.py` (name, parameters, registered definition), a definition without a function declarator raising, call linking, interprocedural arguments and returns in `test_interprocedural.py`, and pointer-returning functions in `edge_cases.c`, which the per-fixture call-site check builds. All 11 fail on master: the pointer shapes crash, the parenthesized and attributed names build with the wrong names, and the error case raised a different error.
- **Mutation-checked**: 6 deliberate bugs (outermost declarator instead of innermost, no unwrapping, attributes not unwrapped or the wrong child taken, no error, name taken as text): all fail tests. A first version (stop at the first function declarator named by an identifier) broke `int (f)(...)` and `int f [[attr]] (...)`, which built on master; the innermost rule replaced it.
- **Real code**: on the 251 C files in the container (vendored C in Python packages, bison skeletons, X11 sources), 213 build instead of 150, with 2017 functions instead of 782. The other failures were already on master and are filed as #64 (`for (;;)`, preprocessor conditionals around `case` labels, macro-named functions).
