"""
Tests for structured call sites (`CFGNodeMetadata.call_sites`), for Python, C and Java.

A call site says what was called (name, whole callee expression, receiver), with which
arguments (text, variables used, keyword, `*`/`**`), where the result goes when the call
is the whole right-hand side of an assignment (`assigned_to`), and which enclosing call
the result feeds (`feeds`). `function_calls` is derived from the sites.
"""

from collections import Counter
from pathlib import Path
from typing import List

import pytest

from tree_climber.ast_utils import dfs, parse_source_to_ast
from tree_climber.cfg.builder import CFGBuilder
from tree_climber.cfg.call_sites import preorder
from tree_climber.cfg.cfg_types import CallSite, CFGNode
from tree_climber.cfg.languages.c import CCFGVisitor
from tree_climber.cfg.languages.java import JavaCFGVisitor
from tree_climber.cfg.languages import python_calls
from tree_climber.cfg.languages import python_bindings
from tree_climber.cfg.languages.python_bindings import collect_bindings
from tree_climber.cfg.visitor import NodeFacts
from tree_climber.language_registry import create_visitor

ROOT = Path(__file__).parent


def sites_of(language: str, source: str, statement: str) -> List[CallSite]:
    """Call sites of the node whose source text starts with `statement`."""
    builder = CFGBuilder(language)
    builder.setup_parser()
    cfg = builder.build_cfg(source)
    matches = [n for n in cfg.nodes.values() if n.source_text.startswith(statement)]
    assert len(matches) == 1, f"{len(matches)} nodes start with {statement!r}"
    return matches[0].metadata.call_sites


def py(statement: str, setup: str = "") -> List[CallSite]:
    """Call sites of a Python statement (the last line of `setup + statement`)."""
    return sites_of("python", f"{setup}{statement}\n", statement)


def c(statement: str) -> List[CallSite]:
    return sites_of("c", f"void f() {{ int x, y, a, b; {statement} }}", statement)


def java(statement: str) -> List[CallSite]:
    source = f"class A {{ void f() {{ int x = 0, y = 0, a = 0, b = 0; {statement} }} }}"
    return sites_of("java", source, statement)


def header_of(statement: str) -> str:
    """How the node for a statement's first line starts: compound statements drop the colon."""
    return statement.split("\n")[0].removesuffix(":")


def feed(site: CallSite):
    assert site.feeds is not None
    return (site.feeds.call, site.feeds.role, site.feeds.position)


def shape(site: CallSite):
    return (
        site.callee,
        site.receiver,
        [(a.text, a.keyword, a.kind) for a in site.arguments],
        site.assigned_to,
    )


class TestPythonCallee:
    def test_a_plain_call(self):
        (site,) = py("f(x)")

        assert (site.callee, site.callee_text, site.receiver) == ("f", "f", None)

    def test_a_method_call_has_a_receiver_and_the_attribute_as_its_name(self):
        (site,) = py("obj.run(x)")

        assert (site.callee, site.callee_text, site.receiver) == (
            "run",
            "obj.run",
            "obj",
        )

    def test_a_dotted_receiver_is_kept_whole(self):
        (site,) = py("os.path.join(a, b)")

        assert (site.callee, site.callee_text, site.receiver) == (
            "join",
            "os.path.join",
            "os.path",
        )

    def test_a_call_without_a_usable_name_is_still_a_site(self):
        outer, inner = py("f()(x)")

        assert (outer.callee, outer.callee_text) == (None, "f()")
        assert (inner.callee, inner.callee_text) == ("f", "f")
        assert inner.feeds is not None
        assert feed(inner)[:2] == (0, "callee")

    def test_a_subscripted_callee_has_no_name(self):
        (site,) = py("handlers[kind](x)")

        assert (site.callee, site.callee_text, site.receiver) == (
            None,
            "handlers[kind]",
            None,
        )

    def test_a_call_with_no_arguments(self):
        (site,) = py("f()")

        assert site.arguments == []


class TestPythonArguments:
    def test_positional_arguments_keep_their_text_and_uses(self):
        (site,) = py("f(a, b + 1, 'lit')")

        assert [(a.text, a.uses, a.kind) for a in site.arguments] == [
            ("a", ["a"], "positional"),
            ("b + 1", ["b"], "positional"),
            ("'lit'", [], "positional"),
        ]

    def test_keyword_arguments(self):
        (site,) = py("f(a, key=value, other=g)")

        assert [(a.text, a.keyword, a.kind, a.uses) for a in site.arguments] == [
            ("a", None, "positional", ["a"]),
            ("value", "key", "keyword", ["value"]),
            ("g", "other", "keyword", ["g"]),
        ]

    def test_star_and_double_star_arguments(self):
        (site,) = py("f(*args, **kwargs)")

        assert [(a.text, a.kind, a.uses) for a in site.arguments] == [
            ("args", "star", ["args"]),
            ("kwargs", "double_star", ["kwargs"]),
        ]

    def test_a_generator_argument_is_one_argument(self):
        (site,) = py("f(x for x in items)")

        assert [(a.text, a.uses) for a in site.arguments] == [
            ("(x for x in items)", ["items"])
        ]

    def test_comprehension_variables_are_not_uses_of_the_argument(self):
        (site,) = py("f([n * k for n in items])")

        assert site.arguments[0].uses == ["k", "items"]

    def test_a_lambda_argument_does_not_use_its_parameter(self):
        (site, _) = py("sorted(xs, key=lambda v: g(v))")

        assert site.arguments[1].uses == ["g"]

    def test_comments_between_arguments_are_skipped(self):
        (site,) = py("f(a,  # first\n    b)")

        assert [a.text for a in site.arguments] == ["a", "b"]

    def test_a_trailing_comma(self):
        (site,) = py("f(a, b,)")

        assert [a.text for a in site.arguments] == ["a", "b"]


class TestPythonAssignedTo:
    @pytest.mark.parametrize(
        "statement, names",
        [
            ("x = f()", ["x"]),
            ("x: int = f()", ["x"]),
            ("a, b = f()", ["a", "b"]),
            ("a, (b, *c) = f()", ["a", "b", "c"]),
            ("x = y = f()", ["x", "y"]),
            ("x = y = z = f()", ["x", "y", "z"]),
            ("x += f()", ["x"]),
            ("x = (f())", ["x"]),
            ("x = await f()", ["x"]),
            ("with f() as h:\n    pass", ["h"]),
            ("with f() as (p, q):\n    pass", ["p", "q"]),
            ("(x := f())", ["x"]),
            ("y = (x := f())", ["y", "x"]),
            ("obj.attr = f()", ["obj"]),
            ("table[key] = f()", ["table"]),
        ],
    )
    def test_the_call_is_the_whole_right_hand_side(self, statement, names):
        sites = sites_of("python", f"{statement}\n", header_of(statement))

        assert sites[0].assigned_to == names

    @pytest.mark.parametrize(
        "statement",
        [
            "f()",
            "x = 1 + f()",
            "x = [f()]",
            "x = f() if c else d",
            "x, y = f(), g()",
            "x = (f(), 1)",
            "x = not f()",
            "x = g(f())",
            "for x in f():\n    pass",
            "return_value = [x for x in f()]",
        ],
    )
    def test_a_call_that_is_only_part_of_the_value_is_not_assigned(self, statement):
        sites = sites_of("python", f"{statement}\n", header_of(statement))

        assert sites[0].callee == "f" or sites[0].callee == "g"
        assert all(site.assigned_to == [] for site in sites if site.callee == "f")

    def test_a_returned_call_is_not_assigned(self):
        (site,) = sites_of("python", "def g():\n    return f()\n", "return f()")

        assert site.assigned_to == []

    def test_the_names_are_the_ones_the_node_defines(self):
        builder = CFGBuilder("python")
        builder.setup_parser()
        cfg = builder.build_cfg("a, (b, *c) = f()\nobj.x = g()\n")

        for node in cfg.nodes.values():
            if node.metadata.call_sites:
                assert node.metadata.call_sites[0].assigned_to == [
                    d for d in node.metadata.variable_definitions
                ]


class TestPythonNesting:
    def test_an_inner_call_feeds_its_argument_position(self):
        outer, g, h = py("f(1 + g(x), h(i))")

        assert feed(g) == (0, "argument", 0)
        assert feed(h) == (0, "argument", 1)
        assert outer.feeds is None

    def test_a_call_in_a_receiver_feeds_the_receiver(self):
        outer, inner = py("a.b(c).d(e)")

        assert (outer.callee, outer.receiver) == ("d", "a.b(c)")
        assert (inner.callee, inner.receiver) == ("b", "a")
        assert feed(inner) == (
            0,
            "receiver",
            None,
        )

    def test_a_long_chain_links_each_call_to_the_next(self):
        sites = py("request.args.get('q').strip().lower()")

        assert [s.callee for s in sites] == ["lower", "strip", "get"]
        assert [feed(s)[:2] if s.feeds else None for s in sites] == [
            None,
            (0, "receiver"),
            (1, "receiver"),
        ]

    def test_the_link_goes_to_the_nearest_enclosing_call(self):
        sites = py("f(g(h(x)))")

        assert [s.callee for s in sites] == ["f", "g", "h"]
        assert [feed(s)[0] if s.feeds else None for s in sites] == [None, 0, 1]

    def test_a_keyword_argument_counts_as_its_position(self):
        _, inner = py("f(a, key=g(x))")

        assert feed(inner) == (
            0,
            "argument",
            1,
        )

    def test_a_call_inside_a_lambda_does_not_feed_the_argument(self):
        _, inner = py("sorted(xs, key=lambda v: g(v))")

        assert inner.callee == "g"
        assert inner.feeds is None

    def test_a_call_in_a_comprehension_argument_feeds_that_argument(self):
        _, inner = py("f([g(i) for i in xs])")

        assert feed(inner) == (
            0,
            "argument",
            0,
        )

    def test_sibling_calls_do_not_feed_each_other(self):
        first, second = py("f(a) + g(b)")

        assert first.feeds is None and second.feeds is None

    def test_the_result_target_of_an_inner_call_is_empty(self):
        outer, inner = py("x = f(g(y))")

        assert outer.assigned_to == ["x"]
        assert inner.assigned_to == []


class TestPythonDefinitionTimeCalls:
    def test_decorators_are_sites_on_the_definition_statement(self):
        sites = sites_of(
            "python",
            "@cache\n@a.b\n@route('/x')\ndef g(x=default()):\n    inside()\n",
            "@cache",
        )

        assert [(s.callee, s.callee_text, s.receiver) for s in sites] == [
            ("route", "route", None),
            ("default", "default", None),
            ("cache", "cache", None),
            ("b", "a.b", "a"),
        ]

    def test_a_bare_decorator_has_no_explicit_arguments(self):
        sites = sites_of("python", "@cache\ndef g():\n    pass\n", "@cache")

        assert sites[0].arguments == []

    def test_a_function_body_is_not_part_of_the_definition_statement(self):
        sites = sites_of(
            "python",
            "def f():\n    def g(x):\n        inside(x)\n        other()\n",
            "def g",
        )

        assert sites == []

    def test_class_body_calls_belong_to_the_class_statement(self):
        sites = sites_of(
            "python",
            "class A(base()):\n    x = make()\n    def m(self):\n        n()\n",
            "class A",
        )

        assert [s.callee for s in sites] == ["base", "make"]
        assert sites[1].assigned_to == ["x"]


class TestArgumentUsesAreTheSameWithTheCache:
    """Reusing the uses of nested calls must not change any argument's uses."""

    @pytest.mark.parametrize(
        "statement",
        [
            "f(g(a), h(b, c=k(d)))",
            "f(*g(a), **h(b))",
            "f([g(n) for n in xs], n)",
            "f(lambda v: g(v, w), g(v))",
            "f({k: g(k, v) for k, v in d.items()}, k)",
            "f(a.b(c).d(e), (y := g(z)))",
            "f(g(a if h(b) else k(c)))",
            "f(g(f(g(f(x)))))",
        ],
    )
    def test_cached_and_uncached_uses_agree(self, statement):
        tree = parse_source_to_ast(statement + "\n", "python")
        sites = python_calls.call_sites(tree.root_node)
        calls = list(python_calls.call_nodes(tree.root_node))
        for site, call in zip(sites, calls):
            for argument, node in zip(
                site.arguments, python_calls._argument_nodes(call)
            ):
                expression = node
                if node.type == "keyword_argument":
                    expression = node.child_by_field_name("value")
                elif node.type in ("list_splat", "dictionary_splat"):
                    expression = node.named_children[0]
                assert expression is not None
                assert argument.uses == collect_bindings(expression).uses, argument.text

    def test_nested_calls_are_walked_once_not_once_per_enclosing_call(
        self, monkeypatch
    ):
        visits = []
        original = python_bindings._Collector.visit

        def counting(self, node, local):
            visits.append(node.id)
            return original(self, node, local)

        monkeypatch.setattr(python_bindings._Collector, "visit", counting)
        depth = 200

        py("x = " + "f(a, " * depth + "0" + ")" * depth, setup="")

        assert len(visits) < 40 * depth

    def test_a_comprehension_variable_inside_a_nested_call_stays_local(self):
        outer, inner = py("f([g(n) for n in xs], n)")

        assert outer.arguments[0].uses == ["g", "xs"]
        assert outer.arguments[1].uses == ["n"]
        assert inner.arguments[0].uses == ["n"]


class TestSpans:
    def test_the_span_is_the_whole_call_expression(self):
        source = "x = obj.f(1, g(2))\n"
        outer, inner = sites_of("python", source, "x = obj")

        assert source[outer.start_byte : outer.end_byte] == "obj.f(1, g(2))"
        assert source[inner.start_byte : inner.end_byte] == "g(2)"

    def test_points_are_row_and_column(self):
        outer, inner = sites_of("python", "y = 1\nx = f(\n    g(2))\n", "x = f")

        assert (outer.start_point, outer.end_point) == ((1, 4), (2, 9))
        assert (inner.start_point, inner.end_point) == ((2, 4), (2, 8))

    def test_spans_use_bytes_not_characters(self):
        source = "s = 'é'; x = f(1)\n"
        (site,) = sites_of("python", source, "x = f(1)")

        assert source.encode()[site.start_byte : site.end_byte] == b"f(1)"


class TestFunctionCallsAreDerivedFromSites:
    def test_names_match_in_order_and_unnamed_calls_are_left_out(self):
        builder = CFGBuilder("python")
        builder.setup_parser()
        cfg = builder.build_cfg("x = a.b(c.d(e()), f)(g())\nh()\n")

        node = next(n for n in cfg.nodes.values() if n.source_text.startswith("x ="))
        sites = node.metadata.call_sites
        assert [s.callee for s in sites] == [None, "b", "d", "e", "g"]
        assert node.metadata.function_calls == ["b", "d", "e", "g"]

    def test_every_node_in_the_fixtures_agrees(self):
        for language, pattern in (
            ("python", "python_cfg/*.py"),
            ("c", "c_cfg/*.c"),
            ("java", "java_cfg/*.java"),
        ):
            for path in sorted(ROOT.glob(pattern)):
                builder = CFGBuilder(language)
                builder.setup_parser()
                cfg = builder.build_cfg(path.read_text())
                for node in cfg.nodes.values():
                    assert_consistent(node, path.name)


def assert_consistent(node: CFGNode, where: str) -> None:
    metadata = node.metadata
    named = [s.callee for s in metadata.call_sites if s.callee is not None]
    assert metadata.function_calls == named, (where, node.source_text)
    for index, site in enumerate(metadata.call_sites):
        if site.feeds is not None:
            assert 0 <= site.feeds.call < len(metadata.call_sites)
            assert site.feeds.call != index
            enclosing = metadata.call_sites[site.feeds.call]
            assert enclosing.start_byte <= site.start_byte
            assert site.end_byte <= enclosing.end_byte
        for argument in site.arguments:
            if argument.direct_uses is not None:
                assert set(argument.direct_uses) <= set(argument.uses)
    if metadata.direct_uses is not None:
        assert set(metadata.direct_uses) <= set(metadata.variable_uses), (
            where,
            node.source_text,
        )
        if not metadata.call_sites:
            assert set(metadata.direct_uses) == set(metadata.variable_uses)


class TestSerialization:
    def test_to_dict_carries_the_sites(self):
        builder = CFGBuilder("python")
        builder.setup_parser()
        cfg = builder.build_cfg("x = f(1, k=y)\n")

        node = next(n for n in cfg.nodes.values() if n.source_text == "x = f(1, k=y)")
        (site,) = node.to_dict()["metadata"]["call_sites"]
        assert site["callee"] == "f"
        assert site["assigned_to"] == ["x"]
        assert site["arguments"][1] == {
            "text": "y",
            "uses": ["y"],
            "keyword": "k",
            "kind": "keyword",
        }
        assert site["feeds"] is None
        assert (site["start_byte"], site["end_byte"]) == (4, 13)

    def test_existing_metadata_keys_are_unchanged(self):
        builder = CFGBuilder("python")
        builder.setup_parser()
        cfg = builder.build_cfg("x = f(y)\n")

        node = next(n for n in cfg.nodes.values() if n.source_text == "x = f(y)")
        metadata = node.to_dict()["metadata"]
        assert metadata["function_calls"] == ["f"]
        assert metadata["variable_definitions"] == ["x"]
        assert metadata["variable_uses"] == ["f", "y"]

    def test_a_node_with_a_nested_feed_serializes(self):
        builder = CFGBuilder("python")
        builder.setup_parser()
        cfg = builder.build_cfg("f(g(x))\n")

        node = next(n for n in cfg.nodes.values() if n.source_text == "f(g(x))")
        inner = node.to_dict()["metadata"]["call_sites"][1]
        assert inner["feeds"] == {"call": 0, "role": "argument", "position": 0}


class TestC:
    def test_a_plain_call(self):
        (site,) = c("x = f(a, 2);")

        assert shape(site) == (
            "f",
            None,
            [("a", None, "positional"), ("2", None, "positional")],
            ["x"],
        )
        assert site.arguments[0].uses == ["a"]

    def test_a_member_call_through_a_pointer_has_a_receiver_and_no_name(self):
        (site,) = c("x = s->cb(1, y);")

        assert (site.callee, site.callee_text, site.receiver) == (None, "s->cb", "s")
        assert site.arguments[1].uses == ["y"]

    def test_a_call_through_a_function_pointer_has_no_name(self):
        (site,) = c("(*fp)(2);")

        assert (site.callee, site.callee_text, site.receiver) == (None, "(*fp)", None)

    @pytest.mark.parametrize(
        "statement, names",
        [
            ("x = f();", ["x"]),
            ("int z = f();", ["z"]),
            ("int *p = f();", ["p"]),
            ("a = b = f();", ["a", "b"]),
            ("x += f();", ["x"]),
            ("x = (int)f();", ["x"]),
            ("x = (f());", ["x"]),
            ("a[0] = f();", ["a"]),
        ],
    )
    def test_assigned_to(self, statement, names):
        assert c(statement)[0].assigned_to == names

    @pytest.mark.parametrize(
        "statement", ["f();", "x = 1 + f();", "x = g(f());", "x = y ? f() : 0;"]
    )
    def test_a_call_that_is_part_of_a_larger_value_is_not_assigned(self, statement):
        sites = c(statement)

        assert all(s.assigned_to == [] for s in sites if s.callee == "f")

    def test_nested_calls(self):
        outer, g, h = c("x = f(g(a), 1 + h(b));")

        assert feed(g) == (0, "argument", 0)
        assert feed(h) == (0, "argument", 1)
        assert outer.assigned_to == ["x"]

    def test_comments_between_arguments_are_skipped(self):
        (site,) = c("x = f(1 /* one */, 2 // two\n);")

        assert [a.text for a in site.arguments] == ["1", "2"]

    def test_a_call_in_the_function_expression_feeds_the_callee(self):
        outer, inner = c("f()(a);")

        assert (outer.callee, outer.callee_text) == (None, "f()")
        assert feed(inner)[:2] == (0, "callee")

    def test_a_call_in_a_receiver(self):
        outer, inner = c("x = g()->cb(1);")

        assert (outer.callee, outer.receiver) == (None, "g()")
        assert feed(inner)[:2] == (0, "receiver")

    def test_span(self):
        source = "void f() { int x; x = g(1); }"
        (site,) = sites_of("c", source, "x = g(1);")

        assert source[site.start_byte : site.end_byte] == "g(1)"


class TestJava:
    def test_a_plain_call(self):
        (site,) = java("x = f(a, 2);")

        assert shape(site) == (
            "f",
            None,
            [("a", None, "positional"), ("2", None, "positional")],
            ["x"],
        )
        assert site.arguments[0].uses == ["a"]

    def test_a_method_call_has_a_receiver(self):
        (site,) = java("x = obj.run(a);")

        assert (site.callee, site.callee_text, site.receiver) == (
            "run",
            "obj.run",
            "obj",
        )

    def test_this_is_a_receiver(self):
        (site,) = java("this.run(a);")

        assert (site.callee, site.callee_text, site.receiver) == (
            "run",
            "this.run",
            "this",
        )

    @pytest.mark.parametrize(
        "statement, names",
        [
            ("x = f();", ["x"]),
            ("int z = f();", ["z"]),
            ("a = b = f();", ["a", "b"]),
            ("x = (int) f();", ["x"]),
            ("x = (f());", ["x"]),
            ("a[0] = f();", ["a"]),
            ("o.f = f();", ["o"]),
            ("this.f = f();", []),
        ],
    )
    def test_assigned_to(self, statement, names):
        assert java(statement)[0].assigned_to == names

    @pytest.mark.parametrize(
        "statement", ["f();", "x = 1 + f();", "x = g(f());", "x = y > 0 ? f() : 0;"]
    )
    def test_a_call_that_is_part_of_a_larger_value_is_not_assigned(self, statement):
        sites = java(statement)

        assert all(s.assigned_to == [] for s in sites if s.callee == "f")

    def test_a_chained_call_feeds_the_receiver_and_arguments(self):
        outer, b, g = java("x = a.b(c, d).e(g());")

        assert [s.callee for s in (outer, b, g)] == ["e", "b", "g"]
        assert feed(b)[:2] == (0, "receiver")
        assert feed(g) == (0, "argument", 0)
        assert outer.callee_text == "a.b(c, d).e"
        assert outer.assigned_to == ["x"]

    def test_a_call_inside_a_lambda_does_not_feed_the_argument(self):
        _, inner = java("this.run(() -> k(2));")

        assert inner.callee == "k"
        assert inner.feeds is None

    def test_comments_between_arguments_are_skipped(self):
        (site,) = java("x = f(1 /* one */, 2 // two\n);")

        assert [a.text for a in site.arguments] == ["1", "2"]

    def test_object_creation_is_not_a_call_site_yet(self):
        assert java("Object o = new Object(a);") == []

    def test_span(self):
        source = "class A { void f() { int x = 0; x = g(1); } }"
        (site,) = sites_of("java", source, "x = g(1);")

        assert source[site.start_byte : site.end_byte] == "g(1)"


def language_visitor(language: str):
    return create_visitor(language)


class TestMutatingCalls:
    """A call to a mutating method is a weak update of its receiver's root name
    (#75): the statement defines it, and already reads it."""

    @pytest.mark.parametrize(
        "method", sorted(language_visitor("python").MUTATING_METHODS)
    )
    def test_python_mutating_methods_define_their_receiver(self, method):
        node = node_of("python", f"items.{method}(x)\n", "items.")

        assert node.metadata.variable_definitions == ["items"]
        assert "items" in node.metadata.variable_uses

    @pytest.mark.parametrize(
        "method", sorted(language_visitor("java").MUTATING_METHODS)
    )
    def test_java_mutating_methods_define_their_receiver(self, method):
        source = f"class A {{ void f(Obj items, int x) {{ items.{method}(x); }} }}"
        node = node_of("java", source, "items.")

        assert node.metadata.variable_definitions == ["items"]

    @pytest.mark.parametrize(
        "language, source, statement",
        [
            ("python", "items.count(x)\n", "items."),
            ("python", "os.system(x)\n", "os."),
            ("python", "logger.info(x)\n", "logger."),
            ("python", "append(x)\n", "append"),
            ("python", "get().append(x)\n", "get"),
            ("java", "class A { void f() { System.out.println(x); } }", "System"),
            ("java", "class A { void f() { this.items.add(x); } }", "this"),
            ("java", "class A { void f() { map.get(k).put(a, b); } }", "map"),
            ("c", "void f() { add(x); }", "add"),
        ],
    )
    def test_other_calls_define_nothing(self, language, source, statement):
        assert node_of(language, source, statement).metadata.variable_definitions == []

    @pytest.mark.parametrize(
        "statement, root",
        [
            ("self.items.append(x)", "self"),
            ('d["k"].append(x)', "d"),
            ("sb.append(a).append(b)", "sb"),
            ("y = items.pop() or items.append(x)", "items"),
        ],
    )
    def test_the_root_name_of_the_receiver_is_defined(self, statement, root):
        node = node_of("python", f"{statement}\n", statement.split("(")[0][:4])

        assert root in node.metadata.variable_definitions

    def test_a_name_the_statement_already_defines_is_listed_once(self):
        node = node_of("python", 'd["a"] = d.setdefault("k", [])\n', "d[")

        assert node.metadata.variable_definitions == ["d"]

    def test_the_earlier_definition_flows_through(self):
        from python_cfg.cfg_helpers import def_use_chains

        code = "items = []\nitems.append(x)\nprint(items)\n"

        assert def_use_chains(code, "items") == {
            "items = []": ["items.append(x)"],
            "items.append(x)": ["print(items)"],
        }

    def test_a_mutated_global_reaches_other_functions(self):
        from tree_climber.dataflow.interprocedural import analyze_interprocedural

        builder = CFGBuilder("python")
        builder.setup_parser()
        cfg = builder.build_cfg(
            "registry = []\n"
            "def add(x):\n    registry.append(x)\n"
            "def show():\n    print(registry)\n"
        )
        flows = {
            (cfg.nodes[f.definition].source_text, cfg.nodes[f.use].source_text)
            for f in analyze_interprocedural(cfg).free_variable_flows
            if f.variable == "registry"
        }

        assert ("registry.append(x)", "print(registry)") in flows


def node_of(language: str, source: str, statement: str) -> CFGNode:
    builder = CFGBuilder(language)
    builder.setup_parser()
    cfg = builder.build_cfg(source)
    (node,) = [n for n in cfg.nodes.values() if n.source_text.startswith(statement)]
    return node


def direct(language: str, statement: str):
    """(the node's direct uses, each site's (receiver uses, arguments' direct uses))."""
    if language == "python":
        source = f"{statement}\n"
    elif language == "c":
        source = f"void f() {{ int x, y, z, d; {statement} }}"
    else:
        source = f"class A {{ void f() {{ int x = 0, y = 0, z = 0; {statement} }} }}"
    node = node_of(language, source, statement)
    return node.metadata.direct_uses, [
        (site.receiver_uses, [a.direct_uses for a in site.arguments])
        for site in node.metadata.call_sites
    ]


class TestDirectUses:
    @pytest.mark.parametrize("language", ["c", "java", "python"])
    def test_a_use_inside_a_call_is_not_direct(self, language):
        end = "" if language == "python" else ";"
        node_direct, sites = direct(language, f"y = x + escape(z){end}")

        assert node_direct == ["x"]
        assert sites == [(None, [["z"]])]

    @pytest.mark.parametrize("language", ["c", "java", "python"])
    def test_an_argument_that_is_a_call_reads_nothing_directly(self, language):
        end = "" if language == "python" else ";"
        node_direct, sites = direct(language, f"eval(escape(x)){end}")

        assert node_direct == []
        assert sites == [(None, [[]]), (None, [["x"]])]

    @pytest.mark.parametrize("language", ["c", "java", "python"])
    def test_a_variable_inside_and_outside_a_call_is_direct(self, language):
        end = "" if language == "python" else ";"
        _, sites = direct(language, f"eval(x + escape(x)){end}")

        assert sites[0] == (None, [["x"]])

    @pytest.mark.parametrize("language", ["c", "java"])
    def test_occurrences_two_calls_deep_are_not_direct(self, language):
        _, sites = direct(language, "eval(x + f(g(x)));")

        assert sites[0] == (None, [["x"]])
        assert direct(language, "eval(f(g(x)));")[1][0] == (None, [[]])

    def test_receivers(self):
        assert direct("python", "t = escape(x).strip()")[1][0] == ([], [])
        assert direct("python", "t = x.strip(y)")[1] == [(["x"], [["y"]])]
        assert direct("java", "x.run(y).go(z);")[1] == [([], [["z"]]), (["x"], [["y"]])]
        assert direct("c", "d->cb(x).g(y);")[1] == [([], [["y"]]), (["d"], [["x"]])]

    def test_python_keyword_and_star_arguments(self):
        _, sites = direct("python", "f(*xs, k=escape(y) + z, **kw)")

        assert sites[0] == (None, [["xs"], ["z"], ["kw"]])

    def test_python_weak_updates_read_the_root_directly(self):
        assert direct("python", 'd["k"] = escape(x)')[0] == ["d"]
        assert direct("python", "x += escape(w)")[0] == ["x"]
        assert direct("python", "x = escape(x)")[0] == []

    def test_python_for_headers(self):
        source = "for a in escape(x):\n    pass\nfor d[i] in g(x):\n    pass\n"
        assert node_of("python", source, "for a in").metadata.direct_uses == []
        assert node_of("python", source, "for d[i]").metadata.direct_uses == ["i", "d"]

    def test_python_definitions_are_not_known(self):
        node = node_of("python", "@deco(x)\ndef f(a=g(y)):\n    pass\n", "@deco")

        assert node.metadata.direct_uses is None

    def test_python_case_patterns_have_no_calls(self):
        source = (
            "match v:\n    case Color.RED:\n        pass\n    case [a]:\n        pass\n"
        )
        case = node_of("python", source, "case Color.RED")
        capture = node_of("python", source, "capture a")

        assert case.metadata.direct_uses == case.metadata.variable_uses == ["Color"]
        assert capture.metadata.direct_uses == capture.metadata.variable_uses == ["v"]


FIXTURES = (
    ("python", "python_cfg/*.py"),
    ("c", "c_cfg/*.c"),
    ("java", "java_cfg/*.java"),
)


def fixture_trees():
    for language, pattern in FIXTURES:
        for path in sorted(ROOT.glob(pattern)):
            yield language, path.name, parse_source_to_ast(path.read_text(), language)


def every_node(root):
    return list(preorder(root))


class TestOnePassFacts:
    """`node_facts` collects a node's metadata in fewer walks than the four getters
    it stands for; the results must be the same."""

    def test_node_facts_equal_the_getters_on_every_cfg_node(self):
        for language, name, tree in fixture_trees():
            builder = CFGBuilder(language)
            builder.setup_parser()
            cfg = builder.build_cfg(tree=tree)
            visitor = create_visitor(language)
            for node in cfg.nodes.values():
                if node.ast_node is None:
                    continue
                expected = NodeFacts(
                    call_sites=visitor.get_call_sites(node.ast_node),
                    definitions=visitor.get_definitions(node.ast_node),
                    uses=visitor.get_uses(node.ast_node),
                    direct_uses=visitor.get_direct_uses(node.ast_node),
                )
                assert visitor.node_facts(node.ast_node) == expected, (
                    name,
                    node.source_text,
                )

    @pytest.mark.parametrize("language", ["c", "java"])
    def test_occurrences_under_any_node_equal_a_walk_of_that_node(self, language):
        visitor = create_visitor(language)
        assert isinstance(visitor, (CCFGVisitor, JavaCFGVisitor))

        def reference_direct_uses(node):
            names = dfs(node, visitor._use_of)
            counts = Counter(names)
            stack = [node]
            while stack:
                current = stack.pop()
                if current.type in visitor.CALLS:
                    counts.subtract(dfs(current, visitor._use_of))
                else:
                    stack.extend(current.children)
            return [n for n in dict.fromkeys(names) if counts[n] > 0]

        for tree_language, name, tree in fixture_trees():
            if tree_language != language:
                continue
            found = visitor._occurrences(tree.root_node)
            for node in every_node(tree.root_node):
                where = (name, node.start_point, node.type)
                assert found.uses(node) == dfs(node, visitor._use_of), where
                assert found.direct_uses(node) == reference_direct_uses(node), where
            assert found.definitions == dfs(tree.root_node, visitor._definition_of)
            calls = [n for n in every_node(tree.root_node) if n.type in visitor.CALLS]
            assert found.calls == calls

    def test_python_direct_uses_from_the_bindings_walk_equal_a_separate_walk(self):
        for language, name, tree in fixture_trees():
            if language != "python":
                continue
            for node in every_node(tree.root_node):
                calls = list(python_calls.call_nodes(node))
                assert collect_bindings(node, calls).direct_uses == (
                    python_calls.direct_uses(node)
                ), (name, node.start_point, node.type)

    def test_python_scope_names_come_from_one_walk_of_the_body(self, monkeypatch):
        source = (
            "def f(a):\n"
            "    global g\n"
            "    if a:\n"
            "        nonlocal_free = 1\n"
            "        global h, g\n"
            "    def inner():\n"
            "        nonlocal a\n"
            "        global hidden\n"
            "    class C:\n"
            "        global also_hidden\n"
            "    g = h = b = 2\n"
        )
        tree = parse_source_to_ast(source, "python")
        function = tree.root_node.named_children[0]
        runs = []
        original = python_bindings._Collector.run

        def counting(self, *tasks):
            runs.append(tasks)
            return original(self, *tasks)

        monkeypatch.setattr(python_bindings._Collector, "run", counting)

        locals_, globals_, nonlocals = python_bindings.function_scope_names(function)

        assert locals_ == ["a", "nonlocal_free", "inner", "C", "b"]
        assert globals_ == ["g", "h", "g"]
        assert nonlocals == []
        assert len(runs) == 1

        inner = next(
            n
            for n in preorder(function)
            if n.type == "function_definition" and n.id != function.id
        )
        assert python_bindings.function_scope_names(inner) == ([], ["hidden"], ["a"])
