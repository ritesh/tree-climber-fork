"""
Tests for Python definitions: nested functions, classes and methods, decorators,
and lambdas.

Every function and method is its own ENTRY/EXIT subgraph. Where it is defined, the
enclosing flow gets one statement with the header as its text, which binds the name
and runs what is evaluated at definition time.
"""

import pytest
from cfg_helpers import (
    build_cfg,
    def_use_chains,
    edges,
    entry_names,
    node_by_text,
)

from tree_climber.cfg.cfg_types import NodeType

ENTRY = "ENTRY:<module>"
EXIT = "EXIT:<module>"
CALL = "function_call"
RETURN = "function_return"


def call_edges(cfg):
    return {(s, t) for s, t, label in edges(cfg) if label == CALL}


class TestNestedFunctions:
    def test_depth_is_unlimited_and_entries_follow_source_order(self):
        cfg = build_cfg(
            "def f():\n"
            "    def g():\n"
            "        def h():\n"
            "            return 1\n"
            "        return h\n"
            "    return g\n"
        )

        assert entry_names(cfg) == ["f", "g", "h"]
        assert len(cfg.exit_node_ids) == 3

    def test_the_definition_is_a_statement_that_binds_the_name(self):
        code = "def f():\n    def g():\n        return 1\n    return g()\n"

        assert def_use_chains(code, "g") == {"def g()": ["return g()"]}

    def test_defaults_and_annotations_run_at_definition_time(self):
        cfg = build_cfg(
            "def f(base):\n"
            "    def g(x=default(base), *, y: Alias = None) -> Ret:\n"
            "        return x\n"
            "    return g\n"
        )

        definition = node_by_text(
            cfg, "def g(x=default(base), *, y: Alias = None) -> Ret"
        )
        assert definition.metadata.function_calls == ["default"]
        assert definition.metadata.variable_definitions == ["g"]
        assert definition.metadata.variable_uses == ["default", "base", "Alias", "Ret"]

    def test_the_header_is_the_text_and_the_name_is_highlighted(self):
        cfg = build_cfg("def f():\n    def g(a):\n        return a\n")

        definition = node_by_text(cfg, "def g(a)")
        assert definition.ast_node is not None
        assert definition.ast_node.type == "identifier"
        assert definition.ast_node.text == b"g"

    def test_a_call_links_to_the_nested_function(self):
        cfg = build_cfg("def f():\n    def g():\n        return 1\n    return g()\n")

        assert call_edges(cfg) == {("return g()", "ENTRY:g")}
        assert ("EXIT:g", "return g()", RETURN) in edges(cfg)

    def test_a_return_in_a_nested_function_leaves_only_that_function(self):
        cfg = build_cfg(
            "def f():\n    def g():\n        return 1\n    x = 2\n    return x\n"
        )

        found = edges(cfg)
        assert ("return 1", "EXIT:g", None) in found
        assert ("x = 2", "return x", None) in found
        assert ("return x", "EXIT:f", None) in found

    def test_a_nested_function_does_not_inherit_the_enclosing_try(self):
        cfg = build_cfg(
            "def f():\n"
            "    try:\n"
            "        def g():\n"
            "            return risky()\n"
            "        x = 1\n"
            "    except E:\n"
            "        h()\n"
            "    finally:\n"
            "        done()\n"
        )

        found = edges(cfg)
        assert ("return risky()", "EXIT:g", None) in found
        assert not any(
            source in ("ENTRY:g", "return risky()")
            and target not in ("return risky()", "EXIT:g")
            for source, target, _ in found
        )

    def test_a_nested_function_in_a_loop_is_not_part_of_the_loop(self):
        cfg = build_cfg(
            "def f(xs):\n"
            "    for x in xs:\n"
            "        def g():\n"
            "            return x\n"
            "    return 0\n"
        )

        found = edges(cfg)
        assert ("for x in xs", "def g()", "true") in found
        assert ("def g()", "for x in xs", None) in found
        assert ("return x", "EXIT:g", None) in found

    @pytest.mark.parametrize("keyword", ["break", "continue"])
    def test_a_jump_in_a_nested_function_cannot_leave_it(self, keyword):
        cfg = build_cfg(f"for x in xs:\n    def g():\n        {keyword}\n    y = 1\n")

        assert not any(source == keyword for source, _, _ in edges(cfg))

    def test_a_def_in_a_conditional_keeps_its_branch(self):
        cfg = build_cfg("if a:\n    def g():\n        pass\nz = 1\n")

        found = edges(cfg)
        assert ("a", "def g()", "true") in found
        assert ("a", "z = 1", "false") in found
        assert ("def g()", "z = 1", None) in found

    def test_async_def_is_a_function_too(self):
        cfg = build_cfg(
            "def f():\n    async def g():\n        return 1\n    return g\n"
        )

        assert entry_names(cfg) == ["f", "g"]
        assert node_by_text(cfg, "async def g()").node_type == NodeType.STATEMENT


class TestClasses:
    def test_a_class_is_one_statement_with_the_header_as_its_text(self):
        cfg = build_cfg("x = 1\nclass A(Base, metaclass=Meta):\n    y = 2\nz = 3\n")

        assert edges(cfg) == {
            (ENTRY, "x = 1", None),
            ("x = 1", "class A(Base, metaclass=Meta)", None),
            ("class A(Base, metaclass=Meta)", "z = 3", None),
            ("z = 3", EXIT, None),
        }

    def test_the_class_name_is_defined_and_bases_are_used(self):
        cfg = build_cfg("class A(Base, metaclass=Meta):\n    pass\n")

        node = node_by_text(cfg, "class A(Base, metaclass=Meta)")
        assert node.metadata.variable_definitions == ["A"]
        assert node.metadata.variable_uses == ["Base", "Meta"]

    def test_class_body_names_do_not_leak_into_the_enclosing_scope(self):
        code = "x = 0\nclass A:\n    x = 1\nprint(x)\n"

        assert def_use_chains(code, "x") == {"x = 0": ["print(x)"]}

    def test_calls_in_bases_and_the_body_run_when_the_class_is_defined(self):
        cfg = build_cfg("class A(base()):\n    x = compute()\n")

        assert node_by_text(cfg, "class A(base())").metadata.function_calls == [
            "base",
            "compute",
        ]

    def test_each_method_is_a_subgraph_named_after_its_class(self):
        cfg = build_cfg(
            "class A:\n"
            "    def m(self):\n"
            "        return 1\n"
            "    async def n(self):\n"
            "        return 2\n"
            "    class Inner:\n"
            "        def p(self):\n"
            "            return 3\n"
        )

        assert entry_names(cfg) == ["<module>", "A.m", "A.n", "A.Inner.p"]
        assert ("ENTRY:A.m", "return 1", None) in edges(cfg)
        assert ("return 1", "EXIT:A.m", None) in edges(cfg)

    def test_methods_declare_their_parameters(self):
        cfg = build_cfg("class A:\n    def m(self, a, b=1):\n        return a\n")

        entry = node_by_text(cfg, "ENTRY:A.m")
        assert entry.metadata.variable_definitions == ["self", "a", "b"]

    def test_decorated_methods_are_subgraphs_too(self):
        cfg = build_cfg(
            "class A:\n"
            "    @property\n"
            "    def p(self):\n"
            "        return 1\n"
            "    @staticmethod\n"
            "    def s():\n"
            "        return 2\n"
        )

        assert entry_names(cfg) == ["<module>", "A.p", "A.s"]

    def test_methods_are_not_part_of_the_module_flow(self):
        cfg = build_cfg("class A:\n    def m(self):\n        return 1\nx = 2\n")

        assert edges(cfg) >= {
            (ENTRY, "class A", None),
            ("class A", "x = 2", None),
        }
        assert not any(
            source == "class A" and target.startswith("ENTRY:A")
            for source, target, _ in edges(cfg)
        )

    def test_a_class_without_methods_is_just_a_statement(self):
        cfg = build_cfg("class A:\n    pass\n")

        assert entry_names(cfg) == ["<module>"]

    def test_a_class_inside_a_function(self):
        cfg = build_cfg(
            "def f():\n    class A:\n        def m(self):\n            return 1\n    return A\n"
        )

        assert entry_names(cfg) == ["f", "A.m"]
        assert ("ENTRY:f", "class A", None) in edges(cfg)
        assert ("class A", "return A", None) in edges(cfg)

    def test_a_method_can_define_nested_functions(self):
        cfg = build_cfg(
            "class A:\n"
            "    def m(self):\n"
            "        def inner():\n"
            "            return 1\n"
            "        return inner()\n"
        )

        assert entry_names(cfg) == ["<module>", "A.m", "inner"]
        assert call_edges(cfg) == {("return inner()", "ENTRY:inner")}


class TestMethodCalls:
    def test_self_calls_link_to_the_method(self):
        cfg = build_cfg(
            "class A:\n"
            "    def run(self):\n"
            "        return self.step()\n"
            "    def step(self):\n"
            "        return 1\n"
        )

        assert call_edges(cfg) == {("return self.step()", "ENTRY:A.step")}
        assert ("EXIT:A.step", "return self.step()", RETURN) in edges(cfg)

    def test_calls_are_resolved_by_name_across_classes(self):
        cfg = build_cfg(
            "class A:\n"
            "    def run(self):\n"
            "        return self.step()\n"
            "    def step(self):\n"
            "        return 1\n"
            "class B:\n"
            "    def step(self):\n"
            "        return 2\n"
        )

        assert call_edges(cfg) == {
            ("return self.step()", "ENTRY:A.step"),
            ("return self.step()", "ENTRY:B.step"),
        }

    def test_calling_the_class_runs_its_constructor(self):
        cfg = build_cfg("class A:\n    def __init__(self):\n        pass\nobj = A()\n")

        assert call_edges(cfg) == {("obj = A()", "ENTRY:A.__init__")}
        assert ("EXIT:A.__init__", "obj = A()", RETURN) in edges(cfg)

    def test_a_nested_class_constructor_is_reached_by_the_inner_name(self):
        cfg = build_cfg(
            "class A:\n"
            "    class B:\n"
            "        def __init__(self):\n"
            "            pass\n"
            "obj = B()\n"
        )

        assert call_edges(cfg) == {("obj = B()", "ENTRY:A.B.__init__")}

    def test_super_init_is_not_linked_to_every_constructor(self):
        cfg = build_cfg(
            "class A:\n"
            "    def __init__(self):\n"
            "        pass\n"
            "class B(A):\n"
            "    def __init__(self):\n"
            "        super().__init__()\n"
        )

        assert call_edges(cfg) == set()

    def test_a_class_without_init_has_nothing_to_link(self):
        cfg = build_cfg("class A:\n    pass\nobj = A()\n")

        assert call_edges(cfg) == set()


class TestDecorators:
    def test_a_decorated_function_is_one_statement_with_its_decorators(self):
        cfg = build_cfg("@cache\n@retry(3)\ndef g(n):\n    return n\nx = g(1)\n")

        header = "@cache\n@retry(3)\ndef g(n)"
        assert edges(cfg) == {
            (ENTRY, header, None),
            (header, "x = g(1)", None),
            ("x = g(1)", EXIT, None),
            ("x = g(1)", "ENTRY:g", CALL),
            ("EXIT:g", "x = g(1)", RETURN),
            ("ENTRY:g", "return n", None),
            ("return n", "EXIT:g", None),
        }

    @pytest.mark.parametrize(
        "decorators, calls",
        [
            ("@cache", ["cache"]),
            ("@functools.cache", ["cache"]),
            ("@route('/x')", ["route"]),
            ("@a.b(c())", ["b", "c"]),
            ("@one\n@two", ["one", "two"]),
        ],
    )
    def test_decorators_are_calls(self, decorators, calls):
        cfg = build_cfg(f"{decorators}\ndef g():\n    pass\n")

        (definition,) = [
            node
            for node in cfg.nodes.values()
            if node.source_text.startswith(decorators)
        ]
        assert sorted(definition.metadata.function_calls) == sorted(calls)

    def test_a_decorator_defined_in_the_file_is_linked(self):
        cfg = build_cfg("def deco(f):\n    return f\n\n@deco\ndef g():\n    pass\n")

        assert call_edges(cfg) == {("@deco\ndef g()", "ENTRY:deco")}

    def test_decorator_arguments_are_uses(self):
        code = "x = 1\n@deco(x)\ndef g():\n    pass\n"

        assert def_use_chains(code, "x") == {"x = 1": ["@deco(x)\ndef g()"]}

    def test_a_decorated_class(self):
        cfg = build_cfg(
            "@register\nclass A:\n    def m(self):\n        return 1\nz = 0\n"
        )

        assert entry_names(cfg) == ["<module>", "A.m"]
        assert ("@register\nclass A", "z = 0", None) in edges(cfg)
        assert node_by_text(cfg, "@register\nclass A").metadata.function_calls == [
            "register"
        ]

    def test_a_decorated_function_defines_its_name_once(self):
        cfg = build_cfg("@deco\ndef g():\n    pass\ng()\n")

        definition = node_by_text(cfg, "@deco\ndef g()")
        assert definition.metadata.variable_definitions == ["g"]
        assert definition.metadata.variable_uses == ["deco"]

    def test_a_file_of_only_a_decorated_function_has_a_module_flow(self):
        cfg = build_cfg("@deco\ndef g():\n    pass\n")

        assert entry_names(cfg) == ["<module>", "g"]

    def test_a_plain_module_level_function_still_has_no_statement(self):
        cfg = build_cfg("def g():\n    pass\n")

        assert entry_names(cfg) == ["g"]


class TestLambdasStayInline:
    def test_a_lambda_adds_no_subgraph(self):
        cfg = build_cfg("f = lambda x: helper(x)\n")

        assert entry_names(cfg) == ["<module>"]
        node = node_by_text(cfg, "f = lambda x: helper(x)")
        assert node.metadata.function_calls == ["helper"]
        assert node.metadata.variable_definitions == ["f"]
        assert node.metadata.variable_uses == ["helper"]

    def test_a_lambda_argument_call_is_linked_from_the_statement(self):
        cfg = build_cfg(
            "def key(v):\n    return v\n\nsorted(xs, key=lambda v: key(v))\n"
        )

        assert call_edges(cfg) == {("sorted(xs, key=lambda v: key(v))", "ENTRY:key")}


class TestHalfTypedCode:
    @pytest.mark.parametrize(
        "source",
        [
            "def f(",
            "def f():\n    def g(",
            "class A(",
            "class A:\n",
            "class A:\n    def m(",
            "@deco",
            "@deco\n",
            "@deco\ndef",
            "@deco\nclass",
            "class A:\n    @property\n",
        ],
    )
    def test_incomplete_definitions_still_build_a_graph(self, source):
        cfg = build_cfg(source)

        assert cfg.nodes
