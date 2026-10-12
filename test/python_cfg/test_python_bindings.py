"""
Tests for Python variable definitions and uses (get_definitions / get_uses).

Each case is a statement and the names it should define and use. Lists are
compared sorted because order is not part of the contract.
"""

import pytest
from cfg_helpers import build_cfg, node_by_text

from tree_climber.ast_utils import parse_source_to_ast
from tree_climber.cfg.languages.python import PythonCFGVisitor


def bindings_of(source: str):
    """Definitions and uses of the first statement in `source`."""
    root = parse_source_to_ast(source, "python").root_node
    statement = next(c for c in root.children if c.is_named and c.type != "comment")
    visitor = PythonCFGVisitor()
    return (
        sorted(visitor.get_definitions(statement)),
        sorted(visitor.get_uses(statement)),
    )


def check(source: str, definitions, uses):
    actual_defs, actual_uses = bindings_of(source)
    assert actual_defs == sorted(definitions), f"definitions of {source!r}"
    assert actual_uses == sorted(uses), f"uses of {source!r}"


@pytest.mark.parametrize(
    "source, definitions, uses",
    [
        ("x = 1", ["x"], []),
        ("x = y", ["x"], ["y"]),
        ("x = x + 1", ["x"], ["x"]),
        ("a = b = c", ["a", "b"], ["c"]),
        ("x: int = 3", ["x"], ["int"]),
        ("x: int", [], ["int"]),
        ("self.x: int", [], ["self", "int"]),
        ("a, b = b, a", ["a", "b"], ["a", "b"]),
        ("a, (b, *c) = f()", ["a", "b", "c"], ["f"]),
        ("[a, b] = pair", ["a", "b"], ["pair"]),
        ("x = [a, b][i]", ["x"], ["a", "b", "i"]),
    ],
)
def test_assignment(source, definitions, uses):
    check(source, definitions, uses)


@pytest.mark.parametrize(
    "source, definitions, uses",
    [
        ("x += 1", ["x"], ["x"]),
        ("x += y", ["x"], ["x", "y"]),
        ("a[i] += 1", ["a"], ["a", "i"]),
        ("self.count += 1", ["self"], ["self"]),
    ],
)
def test_augmented_assignment_defines_and_uses(source, definitions, uses):
    check(source, definitions, uses)


@pytest.mark.parametrize(
    "source, definitions, uses",
    [
        ("(n := f(x))", ["n"], ["f", "x"]),
        ("if (n := f(x)) > 1:\n    pass", ["n"], ["f", "x"]),
    ],
)
def test_walrus(source, definitions, uses):
    check(source, definitions, uses)


@pytest.mark.parametrize(
    "source, definitions, uses",
    [
        ("self.x = v", ["self"], ["self", "v"]),
        ("a[i] = v", ["a"], ["a", "i", "v"]),
        ("a.b.c = v", ["a"], ["a", "v"]),
        ("a[i].b = v", ["a"], ["a", "i", "v"]),
        ("a[i, j] = v", ["a"], ["a", "i", "j", "v"]),
        ("f().x = v", [], ["f", "v"]),
    ],
)
def test_attribute_and_subscript_targets_are_weak_updates(source, definitions, uses):
    check(source, definitions, uses)


@pytest.mark.parametrize(
    "source, definitions, uses",
    [
        ("obj.attr", [], ["obj"]),
        ("foo(x, key=y)", [], ["foo", "x", "y"]),
        ("obj.method(arg)", [], ["obj", "arg"]),
        ("pkg.mod.fn(a)", [], ["pkg", "a"]),
        ("f(*args, **kwargs)", [], ["f", "args", "kwargs"]),
        ('print(f"{x:{w}} {y!r}")', [], ["print", "x", "w", "y"]),
        ("return a + b", [], ["a", "b"]),
        ("assert x, msg", [], ["x", "msg"]),
        ("pass", [], []),
        ("x = None", ["x"], []),
    ],
)
def test_uses(source, definitions, uses):
    check(source, definitions, uses)


@pytest.mark.parametrize(
    "source, definitions, uses",
    [
        ("del a", [], ["a"]),
        ("del a[0], b", [], ["a", "b"]),
        ("del self.x", [], ["self"]),
    ],
)
def test_del_is_a_use_not_a_definition(source, definitions, uses):
    check(source, definitions, uses)


@pytest.mark.parametrize(
    "source, definitions, uses",
    [
        ("for k, v in d.items():\n    pass", ["k", "v"], ["d"]),
        (
            "for i in range(n):\n    total += i",
            ["i", "total"],
            ["i", "n", "range", "total"],
        ),
        ("with open(f) as fh:\n    pass", ["fh"], ["open", "f"]),
        ("with a as (p, q), b:\n    pass", ["p", "q"], ["a", "b"]),
        ("try:\n    pass\nexcept (A, B) as e:\n    pass", ["e"], ["A", "B"]),
        ("try:\n    pass\nexcept ValueError:\n    pass", [], ["ValueError"]),
    ],
)
def test_binding_statements(source, definitions, uses):
    check(source, definitions, uses)


@pytest.mark.parametrize(
    "source, definitions",
    [
        ("import os", ["os"]),
        ("import os.path", ["os"]),
        ("import os.path as p, sys", ["p", "sys"]),
        ("from m import a, b as c", ["a", "c"]),
        ("from . import x", ["x"]),
        ("from m import *", []),
    ],
)
def test_imports_define_and_never_use(source, definitions):
    check(source, definitions, [])


@pytest.mark.parametrize("source", ["global g, h", "nonlocal n"])
def test_global_and_nonlocal_declarations_produce_nothing(source):
    check(source, [], [])


class TestNestedScopes:
    @pytest.mark.parametrize(
        "source, definitions, uses",
        [
            ("def f(a, b=d, *args: T, **kw):\n    return a + y", ["f"], ["d", "T"]),
            ("def f(x: int = c) -> R:\n    pass", ["f"], ["int", "c", "R"]),
            ("@dec(x)\ndef f():\n    pass", ["f"], ["dec", "x"]),
            ("class A(B, metaclass=M):\n    x = y", ["A"], ["B", "M"]),
        ],
    )
    def test_def_and_class_define_their_name_and_skip_the_body(
        self, source, definitions, uses
    ):
        check(source, definitions, uses)

    @pytest.mark.parametrize(
        "source, definitions, uses",
        [
            ("f = lambda a, b=d: a + y", ["f"], ["d", "y"]),
            ("g = lambda: x", ["g"], ["x"]),
            ("lambda a: a", [], []),
        ],
    )
    def test_lambda_body_counts_minus_its_parameters(self, source, definitions, uses):
        check(source, definitions, uses)

    @pytest.mark.parametrize(
        "source, definitions, uses",
        [
            ("[i * 2 for i in xs if i > k]", [], ["xs", "k"]),
            ("{k: v for k, v in pairs}", [], ["pairs"]),
            ("{e for e in items}", [], ["items"]),
            ("(x for x in x)", [], ["x"]),
            ("[a for a in xs for b in a]", [], ["xs"]),
            ("total = sum(x * x for x in values)", ["total"], ["sum", "values"]),
            ("[[j for j in row] for row in grid]", [], ["grid"]),
            ("[y := f(x) for x in xs]", ["y"], ["f", "xs"]),
        ],
    )
    def test_comprehension_variables_stay_local(self, source, definitions, uses):
        check(source, definitions, uses)


class TestOnCfgNodes:
    def test_function_name_is_not_a_use_on_its_entry_node(self):
        cfg = build_cfg("def f(a):\n    return a\n")

        entry = node_by_text(cfg, "ENTRY:f")
        assert entry.metadata.variable_definitions == ["a"]
        assert entry.metadata.variable_uses == []

    def test_metadata_is_filled_from_the_extractor(self):
        cfg = build_cfg("def f(a):\n    b = a + 1\n    return b\n")

        statement = node_by_text(cfg, "b = a + 1")
        assert statement.metadata.variable_definitions == ["b"]
        assert statement.metadata.variable_uses == ["a"]
        assert node_by_text(cfg, "return b").metadata.variable_uses == ["b"]
