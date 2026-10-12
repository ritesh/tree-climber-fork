"""
Test suite for the Python CFG implementation.

Covers straight-line code and function definitions. Statements the visitor has
no handler for yet are checked only for keeping the flow connected.
"""

from pathlib import Path
from typing import Set

import pytest
from cfg_helpers import (
    build_cfg,
    edges,
    entry_names,
    node_by_text,
    reachable_from,
)

from tree_climber.ast_utils import parse_source_to_ast
from tree_climber.cfg.languages.python import PythonCFGVisitor
from tree_climber.cfg.visitor import CFG

FIXTURE = Path(__file__).parent / "basic_constructs.py"


class TestModuleFlow:
    """Top-level statements run between a <module> ENTRY/EXIT pair."""

    def test_straight_line_module(self):
        cfg = build_cfg("x = 1\ny = 2\n")

        assert edges(cfg) == {
            ("ENTRY:<module>", "x = 1", None),
            ("x = 1", "y = 2", None),
            ("y = 2", "EXIT:<module>", None),
        }

    @pytest.mark.parametrize("code", ["", "# only a comment\n"])
    def test_empty_module_still_has_a_flow(self, code):
        cfg = build_cfg(code)

        assert edges(cfg) == {("ENTRY:<module>", "EXIT:<module>", None)}

    def test_module_with_only_functions_has_no_module_flow(self):
        cfg = build_cfg("def f():\n    pass\n\ndef g():\n    pass\n")

        assert entry_names(cfg) == ["f", "g"]
        assert not any(node.source_text == "<module>" for node in cfg.nodes.values())

    def test_defining_a_function_does_not_run_it(self):
        cfg = build_cfg("a = 1\ndef f():\n    pass\nb = 2\n")

        assert ("a = 1", "b = 2", None) in edges(cfg)
        module_entry = cfg.entry_node_ids[0]
        assert node_by_text(cfg, "ENTRY:f").id not in reachable_from(cfg, module_entry)

    def test_docstring_import_and_comments(self):
        cfg = build_cfg('"""doc"""\n# comment\nimport os\nx = os\n')

        assert edges(cfg) == {
            ("ENTRY:<module>", '"""doc"""', None),
            ('"""doc"""', "import os", None),
            ("import os", "x = os", None),
            ("x = os", "EXIT:<module>", None),
        }


class TestFunctions:
    def test_simple_function(self):
        cfg = build_cfg("def f():\n    pass\n")

        assert edges(cfg) == {
            ("ENTRY:f", "pass", None),
            ("pass", "EXIT:f", None),
        }
        assert cfg.function_name == "f"
        assert len(cfg.entry_node_ids) == 1
        assert len(cfg.exit_node_ids) == 1

    def test_async_function(self):
        cfg = build_cfg("async def f(x):\n    return x\n")

        assert edges(cfg) == {
            ("ENTRY:f", "return x", None),
            ("return x", "EXIT:f", None),
        }

    @pytest.mark.parametrize(
        "signature, expected",
        [
            ("()", []),
            ("(a, b)", ["a", "b"]),
            ("(a, b=1)", ["a", "b"]),
            ("(a: int, b: str = 'x')", ["a", "b"]),
            ("(*args, **kwargs)", ["args", "kwargs"]),
            ("(*args: int, **kwargs: int)", ["args", "kwargs"]),
            ("(a, /, b, *, c)", ["a", "b", "c"]),
            ("(*, key=None)", ["key"]),
        ],
    )
    def test_parameters_are_recorded_as_definitions_on_entry(self, signature, expected):
        cfg = build_cfg(f"def f{signature}:\n    pass\n")

        entry = cfg.nodes[cfg.entry_node_ids[0]]
        assert entry.metadata.variable_definitions == expected

    def test_return_jumps_to_exit_and_leaves_following_code_unreachable(self):
        cfg = build_cfg("def f(x):\n    return x\n    y = 1\n")

        assert ("return x", "EXIT:f", None) in edges(cfg)
        assert ("return x", "y = 1", None) not in edges(cfg)
        assert node_by_text(cfg, "y = 1").predecessors == set()

    def test_docstring_comment_and_pass(self):
        cfg = build_cfg('def f():\n    """doc"""\n    # comment\n    pass\n')

        assert edges(cfg) == {
            ("ENTRY:f", '"""doc"""', None),
            ('"""doc"""', "pass", None),
            ("pass", "EXIT:f", None),
        }

    def test_functions_are_separate_subgraphs(self):
        cfg = build_cfg("def f():\n    pass\n\ndef g():\n    pass\n")

        f_entry = node_by_text(cfg, "ENTRY:f")
        g_entry = node_by_text(cfg, "ENTRY:g")
        f_reach = reachable_from(cfg, f_entry.id)
        assert node_by_text(cfg, "EXIT:f").id in f_reach
        assert g_entry.id not in f_reach

    def test_calls_in_default_values_do_not_link_the_entry(self):
        cfg = build_cfg("def g():\n    pass\n\ndef f(x=g()):\n    pass\n")

        assert not any(
            source == "ENTRY:f" and edge_label == "function_call"
            for source, _, edge_label in edges(cfg)
        )


class TestCalls:
    def test_call_and_return_edges_from_module_code(self):
        cfg = build_cfg("def f():\n    return 1\n\nf()\n")

        assert ("f()", "ENTRY:f", "function_call") in edges(cfg)
        assert ("EXIT:f", "f()", "function_return") in edges(cfg)

    def test_call_between_functions(self):
        cfg = build_cfg("def g():\n    pass\n\ndef f():\n    g()\n")

        assert ("g()", "ENTRY:g", "function_call") in edges(cfg)
        assert ("EXIT:g", "g()", "function_return") in edges(cfg)

    @pytest.mark.parametrize(
        "source, expected",
        [
            ("foo()", ["foo"]),
            ("obj.method()", ["method"]),
            ("pkg.mod.fn(1)", ["fn"]),
            ("a(b(1))", ["a", "b"]),
            ("f()()", ["f"]),
            ("table[0]()", []),
            ("foo(bar=baz())", ["foo", "baz"]),
            ("x = 1", []),
        ],
    )
    def test_get_calls(self, source, expected):
        tree = parse_source_to_ast(source, "python")

        assert PythonCFGVisitor().get_calls(tree.root_node) == expected


class TestUnsupportedStatements:
    """Compound statements without handlers must not break the flow."""

    def test_flow_stays_connected_through_unsupported_statements(self):
        cfg = build_cfg(
            "x = 1\n"
            "class A:\n"
            "    z = 3\n"
            "match x:\n"
            "    case 1:\n"
            "        pass\n"
            "@decorator\n"
            "def g():\n"
            "    pass\n"
            "w = 4\n"
        )

        module_entry = cfg.entry_node_ids[0]
        module_exit = cfg.exit_node_ids[0]
        reachable = reachable_from(cfg, module_entry)
        assert reachable == set(cfg.nodes)
        assert module_exit in reachable
        assert len(cfg.nodes) == 7


class TestFixtureFile:
    @pytest.fixture
    def cfg(self) -> CFG:
        return build_cfg(FIXTURE.read_text())

    def test_entries(self, cfg):
        assert entry_names(cfg) == ["<module>", "helper", "noop", "main"]

    def test_every_function_exit_is_reachable_from_its_entry(self, cfg):
        for entry_id, exit_id in zip(cfg.entry_node_ids, cfg.exit_node_ids):
            assert exit_id in reachable_from(cfg, entry_id)

    def test_every_node_is_reachable_from_some_entry(self, cfg):
        reachable: Set[int] = set()
        for entry_id in cfg.entry_node_ids:
            reachable |= reachable_from(cfg, entry_id)
        assert reachable == set(cfg.nodes)

    def test_call_edges(self, cfg):
        found = edges(cfg)
        assert ("result = main()", "ENTRY:main", "function_call") in found
        assert ("EXIT:main", "result = main()", "function_return") in found
        assert ("value = helper(1)", "ENTRY:helper", "function_call") in found
        assert ("EXIT:helper", "value = helper(1)", "function_return") in found

    def test_helper_parameters(self, cfg):
        helper_entry = node_by_text(cfg, "ENTRY:helper")

        assert helper_entry.metadata.variable_definitions == [
            "a",
            "b",
            "args",
            "c",
            "kwargs",
        ]
