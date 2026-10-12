"""
Python CFG test fixture: module-level code and plain functions.

Contents:
- a module docstring and an import
- helper(): parameters of every kind, a docstring, a comment, and a return
- noop(): a function whose body is only `pass`
- main(): calls helper() and print(), then returns
- top-level code that calls main() and print()

Expected shape: one `<module>` ENTRY/EXIT pair holding the docstring, the import,
and the two top-level statements in order, plus a separate ENTRY/EXIT subgraph per
function. The top-level `main()` call and the `helper(1)` call inside main() are
linked to their function entries with function_call edges, and the function exits
link back with function_return edges.
"""

import os


def helper(a, b=2, *args, c: int = 3, **kwargs):
    """Add the first two arguments."""
    # A comment between statements
    total = a + b + c
    return total


def noop():
    pass


def main():
    value = helper(1)
    print(os.path.join("a", "b"), value)
    return value


result = main()
print(result)
