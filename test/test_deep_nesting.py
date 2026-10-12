"""
Deeply nested expressions must not hit Python's recursion limit (issue #55).

tree-sitter nests `a = b = c` and `x + y + z` one level per operator, so generated
code can be thousands of levels deep. Every program here is deeper than the
recursion limit and goes through the CFG builder and dataflow, `/parse`, and each CLI
drawing. The CLI tests stub out Graphviz's layout (`AGraph.draw`), which is slow on a
graph this deep and is not our code; they check that the graph is built.

The helpers that replaced recursive walks are also compared with recursive reference
versions on ordinary code, so their output did not change.
"""

import asyncio
import sys
from typing import Any, Dict, List

import pygraphviz as pgv
import pytest
from typer.testing import CliRunner

from tree_climber.ast_utils import (
    ast_to_json,
    find_nodes_containing_position,
    iter_ast_edges,
    parse_source_to_ast,
)
from tree_climber.cfg.builder import CFGBuilder
from tree_climber.cli.__main__ import app
from tree_climber.dataflow.analyses.def_use import DefUseSolver
from tree_climber.dataflow.analyses.reaching_definitions import (
    ReachingDefinitionsProblem,
)
from tree_climber.dataflow.solver import RoundRobinSolver
from tree_climber.viz.app import ParseRequest, parse_source_code

DEPTH = sys.getrecursionlimit() + 500
NAMES = [f"a{i}" for i in range(DEPTH)]
ONES = " + ".join("1" for _ in range(DEPTH))

PROGRAMS = {
    ("python", "chained assignment"): " = ".join(NAMES) + " = 0\n",
    ("python", "sum"): f"x = {ONES}\n",
    ("python", "nested calls"): "x = " + "f(" * DEPTH + "0" + ")" * DEPTH + "\n",
    ("python", "method chain"): "x = obj" + ".m()" * DEPTH + "\n",
    ("python", "attribute chain"): "x = obj" + ".a" * DEPTH + "\n",
    ("python", "boolean chain"): "x = " + " and ".join(NAMES) + "\n",
    ("python", "string concatenation"): "x = "
    + " + ".join(f"'{i}'" for i in range(DEPTH))
    + "\n",
    ("python", "subscript write chain"): "x" + "[0]" * DEPTH + " = 1\n",
    ("c", "chained assignment"): "int f() { int "
    + ", ".join(NAMES)
    + "; "
    + " = ".join(NAMES)
    + " = 0; return a0; }\n",
    ("c", "sum"): f"int f() {{ int x = {ONES}; return x; }}\n",
    ("java", "chained assignment"): "class A { int f() { int "
    + ", ".join(NAMES)
    + "; "
    + " = ".join(NAMES)
    + " = 0; return a0; } }\n",
    ("java", "sum"): f"class A {{ int f() {{ int x = {ONES}; return x; }} }}\n",
}
EXTENSIONS = {"python": "py", "c": "c", "java": "java"}
CASES = pytest.mark.parametrize(
    "language, source",
    [
        pytest.param(lang, src, id=f"{lang}-{name}")
        for (lang, name), src in PROGRAMS.items()
    ],
)


@CASES
def test_cfg_and_dataflow(language, source):
    builder = CFGBuilder(language)
    builder.setup_parser()
    cfg = builder.build_cfg(source)
    reaching = RoundRobinSolver().solve(cfg, ReachingDefinitionsProblem())

    DefUseSolver().solve(cfg, reaching)
    assert cfg.nodes


@CASES
def test_parse_endpoint(language, source):
    response = asyncio.run(
        parse_source_code(ParseRequest(source_code=source, language=language))
    )

    assert response.success, response.error
    assert response.ast is not None
    assert depth_of(response.ast) > DEPTH


@CASES
@pytest.mark.parametrize(
    "flags",
    [
        ["--draw-ast"],
        ["--draw-cfg"],
        ["--draw-dfg"],
        ["--draw-cpg"],
        ["--draw-cpg", "-L", "bigraph"],
    ],
    ids=["ast", "cfg", "dfg", "cpg", "cpg-bigraph"],
)
def test_cli_drawings(language, source, flags, tmp_path, monkeypatch):
    drawn: List[pgv.AGraph] = []
    monkeypatch.setattr(pgv.AGraph, "draw", lambda graph, *a, **k: drawn.append(graph))
    path = tmp_path / f"program.{EXTENSIONS[language]}"
    path.write_text(source)

    result = CliRunner().invoke(app, [str(path), *flags, "--output", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert len(drawn) == 1
    assert drawn[0].number_of_nodes() > 0


class TestPythonResults:
    """The deep programs give the same answers a shallow one would."""

    @staticmethod
    def statement_metadata(source: str):
        builder = CFGBuilder("python")
        builder.setup_parser()
        cfg = builder.build_cfg(source)
        (node,) = [n for n in cfg.nodes.values() if n.ast_node is not None]
        return node.metadata

    def test_every_target_of_a_chained_assignment_is_defined(self):
        metadata = self.statement_metadata(PROGRAMS[("python", "chained assignment")])

        assert metadata.variable_definitions == NAMES

    def test_every_operand_of_a_boolean_chain_is_used(self):
        metadata = self.statement_metadata(PROGRAMS[("python", "boolean chain")])

        assert metadata.variable_definitions == ["x"]
        assert metadata.variable_uses == NAMES

    def test_nested_calls_are_all_recorded(self):
        metadata = self.statement_metadata(PROGRAMS[("python", "nested calls")])

        assert metadata.function_calls == ["f"] * DEPTH
        assert metadata.variable_uses == ["f"]

    def test_a_deep_subscript_write_is_a_weak_update_of_the_root(self):
        metadata = self.statement_metadata(
            PROGRAMS[("python", "subscript write chain")]
        )

        assert metadata.variable_definitions == ["x"]
        assert metadata.variable_uses == ["x"]

    def test_the_chain_from_cpython_test_traceback(self):
        """The statement in CPython's Lib/test/test_traceback.py that found #55."""
        targets = [f"a{i}" for i in range(1, 801)]
        lines = [" = ".join(targets[i : i + 10]) for i in range(0, 800, 10)]
        source = " = \\\n    ".join(lines) + " = None\n"

        assert self.statement_metadata(source).variable_definitions == targets


# Recursive reference versions of the replaced walks, for ordinary-sized code.
def reference_json(node) -> Dict[str, Any]:
    return {
        "id": node.id,
        "node_type": node.type,
        "start_point": {"row": node.start_point[0], "column": node.start_point[1]},
        "end_point": {"row": node.end_point[0], "column": node.end_point[1]},
        "start_byte": node.start_byte,
        "end_byte": node.end_byte,
        "text": node.text.decode("utf-8") if node.text else "",
        "is_named": node.is_named,
        "children": [reference_json(child) for child in node.children],
    }


def reference_edges(node, named_only):
    for child in node.children:
        if child.is_named or not named_only:
            yield node, child
            yield from reference_edges(child, named_only)


def reference_containing(node, row, column, results):
    (start_row, start_col), (end_row, end_col) = node.start_point, node.end_point
    if (row > start_row or (row == start_row and column >= start_col)) and (
        row < end_row or (row == end_row and column <= end_col)
    ):
        results.append(node)
        for child in node.children:
            reference_containing(child, row, column, results)
    return results


ORDINARY = {
    "python": "def f(x, y=1):\n    if x > y:\n        return [i * 2 for i in x]\n    return {'k': x.y[0]}\n",
    "c": "int f(int a) { int b = a * 2; if (b > 3) { b++; } return b; }\n",
    "java": "class A { int f(int a) { for (int i = 0; i < a; i++) { a += i; } return a; } }\n",
}


@pytest.mark.parametrize("language", ORDINARY)
class TestHelpersMatchTheRecursiveVersions:
    def test_ast_to_json(self, language):
        root = parse_source_to_ast(ORDINARY[language], language).root_node

        assert ast_to_json(root) == reference_json(root)

    @pytest.mark.parametrize("named_only", [True, False])
    def test_iter_ast_edges(self, language, named_only):
        root = parse_source_to_ast(ORDINARY[language], language).root_node

        def ids(pairs):
            return [(parent.id, child.id) for parent, child in pairs]

        assert ids(iter_ast_edges(root, named_only)) == ids(
            reference_edges(root, named_only)
        )

    def test_find_nodes_containing_position(self, language):
        root = parse_source_to_ast(ORDINARY[language], language).root_node

        for row in range(root.end_point[0] + 1):
            for column in (0, 5, 12, 30):
                expected = reference_containing(root, row, column, [])
                actual = find_nodes_containing_position(root, row, column)
                assert [n.id for n in actual] == [n.id for n in expected]


def depth_of(tree: Dict[str, Any]) -> int:
    deepest = 0
    stack = [(tree, 1)]
    while stack:
        node, depth = stack.pop()
        deepest = max(deepest, depth)
        stack.extend((child, depth + 1) for child in node["children"])
    return deepest
