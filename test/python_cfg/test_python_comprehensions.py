"""
Tests for Python comprehensions and generator expressions.

They hold no statements, so each stays inside the statement that contains it. What
matters is the data flow: the loop variables are local to the comprehension, only the
first iterable is evaluated in the enclosing scope, and a walrus binds outside.
"""

import pytest
from cfg_helpers import build_cfg, def_use_chains, edges, entry_names, node_by_text

from tree_climber.ast_utils import parse_source_to_ast
from tree_climber.cfg.languages.python import PythonCFGVisitor


def statement_of(source: str):
    root = parse_source_to_ast(source, "python").root_node
    return next(c for c in root.children if c.is_named and c.type != "comment")


def definitions_and_uses(source: str):
    visitor = PythonCFGVisitor()
    statement = statement_of(source)
    return (
        sorted(visitor.get_definitions(statement)),
        sorted(visitor.get_uses(statement)),
    )


@pytest.mark.parametrize(
    "source, definitions, uses",
    [
        ("a = [x * 2 for x in xs]", ["a"], ["xs"]),
        ("a = {x for x in xs}", ["a"], ["xs"]),
        ("a = {k: v for k, v in d}", ["a"], ["d"]),
        ("a = {k: f(v) for k, v in d.items()}", ["a"], ["d", "f"]),
        ("a = (x for x in xs)", ["a"], ["xs"]),
        ("a = sum(x for x in xs)", ["a"], ["sum", "xs"]),
        ("a = [x for x in xs if x > lo]", ["a"], ["lo", "xs"]),
        ("a = [x for x in xs if x if y]", ["a"], ["xs", "y"]),
        ("a = [(i, j) for i in xs for j in ys]", ["a"], ["xs", "ys"]),
        ("a = [x for x in xs for y in x]", ["a"], ["xs"]),
        ("a = [x for x, in xs]", ["a"], ["xs"]),
        ("a = [x for (x, (y, *z)) in xs]", ["a"], ["xs"]),
        ("a = [x.attr for x in xs]", ["a"], ["xs"]),
        ("a = [x[i] for x in xs for i in idx]", ["a"], ["idx", "xs"]),
        ("a = [[y for y in row] for row in rows]", ["a"], ["rows"]),
        ("a = [x + n for x in xs]", ["a"], ["n", "xs"]),
    ],
)
def test_loop_variables_are_local(source, definitions, uses):
    assert definitions_and_uses(source) == (definitions, uses)


class TestScopes:
    def test_the_first_iterable_is_evaluated_in_the_enclosing_scope(self):
        assert definitions_and_uses("a = [x for x in x]") == (["a"], ["x"])

    def test_later_iterables_see_the_loop_variables(self):
        assert definitions_and_uses("a = [y for x in xs for y in x]") == (["a"], ["xs"])

    def test_an_outer_variable_of_the_same_name_is_not_used(self):
        code = "x = 1\na = [x for x in xs]\nprint(x)\n"

        assert def_use_chains(code, "x") == {"x = 1": ["print(x)"]}

    def test_the_loop_variable_is_not_defined_outside(self):
        code = "x = 1\na = [x for x in xs]\n"

        assert def_use_chains(code, "x") == {}

    def test_a_walrus_binds_in_the_enclosing_scope(self):
        assert definitions_and_uses("a = [y := f(x) for x in xs]") == (
            ["a", "y"],
            ["f", "xs"],
        )

    def test_a_walrus_in_a_condition_binds_in_the_enclosing_scope(self):
        assert definitions_and_uses("a = [x for x in xs if (n := f(x))]") == (
            ["a", "n"],
            ["f", "xs"],
        )

    def test_a_walrus_value_can_be_used_afterwards(self):
        code = "def f(xs):\n    a = [y := g(x) for x in xs]\n    return y\n"

        assert def_use_chains(code, "y") == {
            "a = [y := g(x) for x in xs]": ["return y"]
        }

    def test_a_lambda_in_a_comprehension_keeps_the_loop_variable_local(self):
        assert definitions_and_uses("a = [lambda: x for x in xs]") == (["a"], ["xs"])


class TestInTheGraph:
    def test_a_comprehension_is_part_of_its_statement(self):
        cfg = build_cfg("def f(xs):\n    a = [x * 2 for x in xs]\n    return a\n")

        assert entry_names(cfg) == ["f"]
        assert edges(cfg) == {
            ("ENTRY:f", "a = [x * 2 for x in xs]", None),
            ("a = [x * 2 for x in xs]", "return a", None),
            ("return a", "EXIT:f", None),
        }

    def test_the_result_depends_on_the_iterable(self):
        code = "def f(xs):\n    a = [x * 2 for x in xs]\n    return a\n"

        assert def_use_chains(code, "xs") == {"ENTRY:f": ["a = [x * 2 for x in xs]"]}
        assert def_use_chains(code, "a") == {"a = [x * 2 for x in xs]": ["return a"]}

    @pytest.mark.parametrize(
        "statement, header, uses",
        [
            ("if any(x for x in xs):\n    pass", "any(x for x in xs)", ["any", "xs"]),
            ("while [x for x in xs]:\n    pass", "[x for x in xs]", ["xs"]),
            (
                "for y in [x for x in xs]:\n    pass",
                "for y in [x for x in xs]",
                ["xs"],
            ),
        ],
    )
    def test_a_comprehension_in_a_header_stays_in_the_header(
        self, statement, header, uses
    ):
        indented = statement.replace("\n", "\n    ")
        cfg = build_cfg(f"def f(xs):\n    {indented}\n")

        assert node_by_text(cfg, header).metadata.variable_uses == uses

    def test_a_comprehension_in_a_try_may_raise(self):
        cfg = build_cfg(
            "try:\n    a = [int(x) for x in xs]\nexcept ValueError:\n    a = []\n"
        )

        assert ("ENTRY:<module>", "except ValueError", "exception") in edges(cfg)


class TestCalls:
    @pytest.mark.parametrize(
        "source, calls",
        [
            ("a = [make(i) for i in items()]", ["make", "items"]),
            ("a = {k: f(v) for k, v in d.items()}", ["f", "items"]),
            ("a = sum(x for x in xs)", ["sum"]),
            ("a = [f(x) for x in xs if ok(x)]", ["f", "ok"]),
            ("a = [[g(y) for y in row] for row in rows]", ["g"]),
        ],
    )
    def test_calls_inside_count_as_calls_of_the_statement(self, source, calls):
        assert sorted(PythonCFGVisitor().get_calls(statement_of(source))) == sorted(
            calls
        )

    def test_a_call_inside_a_comprehension_is_linked(self):
        cfg = build_cfg("def f(v):\n    return v\n\nresult = [f(x) for x in xs]\n")

        found = edges(cfg)
        assert ("result = [f(x) for x in xs]", "ENTRY:f", "function_call") in found
        assert ("EXIT:f", "result = [f(x) for x in xs]", "function_return") in found


class TestAsyncComprehensions:
    def test_async_comprehension_variables_are_local(self):
        assert definitions_and_uses("a = [x async for x in agen()]") == (
            ["a"],
            ["agen"],
        )

    def test_await_inside_a_comprehension(self):
        assert definitions_and_uses("a = [await f(x) for x in xs]") == (
            ["a"],
            ["f", "xs"],
        )

    def test_an_async_generator_expression_argument(self):
        assert definitions_and_uses("a = await collect(x async for x in agen())") == (
            ["a"],
            ["agen", "collect"],
        )


@pytest.mark.parametrize(
    "source",
    [
        "a = [x for",
        "a = [x for x in",
        "a = [x for x in xs if",
        "a = {k: v for k,",
        "a = (x for x in",
        "a = [x async for",
    ],
)
def test_half_typed_comprehensions_still_build_a_graph(source):
    assert build_cfg(source).nodes
