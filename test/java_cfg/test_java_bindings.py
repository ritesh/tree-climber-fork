"""
Tests for Java variable definitions and uses (get_definitions / get_uses).

Each case is a statement and the names it should define and use. Lists are
compared sorted because order is not part of the contract.

The receiver of a method call or field access (`list` in `list.add(x)`, `o` in
`o.field`) is a use; the method or field name is not. Class names used as
receivers (`System`, `Math`) are reported as uses too, since a name cannot be
resolved to a type here; they have no reaching definition, so they add no edges.
"""

import pytest

from tree_climber.ast_utils import parse_source_to_ast
from tree_climber.cfg.builder import CFGBuilder
from tree_climber.cfg.languages.java import JavaCFGVisitor
from tree_climber.dataflow.analyses.def_use import DefUseSolver
from tree_climber.dataflow.analyses.reaching_definitions import (
    ReachingDefinitionsProblem,
)
from tree_climber.dataflow.solver import RoundRobinSolver


def bindings_of(statement: str):
    source = f"class A {{ void m() {{ {statement} }} }}"
    root = parse_source_to_ast(source, "java").root_node
    body = root.children[0].child_by_field_name("body")
    assert body is not None
    method = body.named_children[0]
    method_body = method.child_by_field_name("body")
    assert method_body is not None
    node = method_body.named_children[0]
    visitor = JavaCFGVisitor()
    return sorted(visitor.get_definitions(node)), sorted(visitor.get_uses(node))


@pytest.mark.parametrize(
    "statement, definitions, uses",
    [
        ("list.add(x);", [], ["list", "x"]),
        ("o.run();", [], ["o"]),
        ("int y = o.field;", ["y"], ["o"]),
        ("String s = o.name.trim();", ["s"], ["o"]),
        ("int z = o.get(x).size();", ["z"], ["o", "x"]),
        ("o.a.b.c();", [], ["o"]),
        ("sb.append(a).append(b);", [], ["sb", "a", "b"]),
        ("o.f = x;", [], ["o", "x"]),
        ("this.f = x;", [], ["x"]),
        ("System.out.println(y);", [], ["System", "y"]),
        ("Math.max(a, b);", [], ["Math", "a", "b"]),
    ],
)
def test_receivers_are_uses(statement, definitions, uses):
    actual_definitions, actual_uses = bindings_of(statement)
    assert actual_definitions == sorted(definitions), f"definitions of {statement!r}"
    assert actual_uses == sorted(uses), f"uses of {statement!r}"


@pytest.mark.parametrize(
    "statement, definitions, uses",
    [
        ("foo(x);", [], ["x"]),
        ("int y = x;", ["y"], ["x"]),
        ("y = x + 1;", ["y"], ["x"]),
        ("y += x;", ["y"], ["x", "y"]),
        ("y++;", ["y"], ["y"]),
    ],
)
def test_method_names_and_plain_statements_are_unchanged(statement, definitions, uses):
    actual_definitions, actual_uses = bindings_of(statement)
    assert actual_definitions == sorted(definitions), f"definitions of {statement!r}"
    assert actual_uses == sorted(uses), f"uses of {statement!r}"


def def_use_chains(code: str, variable: str):
    builder = CFGBuilder("java")
    builder.setup_parser()
    cfg = builder.build_cfg(code)
    reaching = RoundRobinSolver().solve(cfg, ReachingDefinitionsProblem())
    result = DefUseSolver().solve(cfg, reaching)
    return {
        cfg.nodes[chain.definition].source_text.strip(): sorted(
            cfg.nodes[use].source_text.strip() for use in chain.uses
        )
        for chain in result.chains.get(variable, [])
    }


class TestDefUseChains:
    CODE = (
        "class A { int f(java.util.List<Integer> list, int x) {"
        " list.add(x); return list.size(); } }"
    )

    def test_parameter_flows_to_calls_made_on_it(self):
        assert def_use_chains(self.CODE, "list") == {
            "f": ["list.add(x);", "return list.size();"]
        }

    def test_argument_still_flows(self):
        assert def_use_chains(self.CODE, "x") == {"f": ["list.add(x);"]}

    def test_object_flows_into_a_field_read(self):
        code = "class A { int f(Obj o) { int y = o.field; return y; } }"

        assert def_use_chains(code, "o") == {"f": ["int y = o.field;"]}
        assert def_use_chains(code, "y") == {"int y = o.field;": ["return y;"]}
