"""
Tests for C variable definitions and uses (get_definitions / get_uses).

Each case is a statement and the names it should define and use. Lists are
compared sorted because order is not part of the contract.

Writes through `.` and `[]` are weak updates of the root variable (it is both
defined and used). Writes through `->` and `*p` change the pointee, not the
pointer, so they define nothing.
"""

import pytest

from tree_climber.ast_utils import parse_source_to_ast
from tree_climber.cfg.builder import CFGBuilder
from tree_climber.cfg.languages.c import CCFGVisitor
from tree_climber.dataflow.analyses.def_use import DefUseSolver
from tree_climber.dataflow.analyses.reaching_definitions import (
    ReachingDefinitionsProblem,
)
from tree_climber.dataflow.solver import RoundRobinSolver


def bindings_of(statement: str):
    root = parse_source_to_ast(f"void f() {{ {statement} }}", "c").root_node
    body = root.children[0].child_by_field_name("body")
    assert body is not None
    node = body.named_children[0]
    visitor = CCFGVisitor()
    return sorted(visitor.get_definitions(node)), sorted(visitor.get_uses(node))


def check(statement: str, definitions, uses):
    actual_definitions, actual_uses = bindings_of(statement)
    assert actual_definitions == sorted(definitions), f"definitions of {statement!r}"
    assert actual_uses == sorted(uses), f"uses of {statement!r}"


@pytest.mark.parametrize(
    "statement, definitions, uses",
    [
        ("int x;", [], []),
        ("int a[n];", [], ["n"]),
        ("int y = x;", ["y"], ["x"]),
        ("int *p = &x;", ["p"], ["x"]),
        ("int *q = p;", ["q"], ["p"]),
        ("int **pp = &p;", ["pp"], ["p"]),
        ("int a[3] = {x, y};", ["a"], ["x", "y"]),
        ("int (*fp)(int) = g;", ["fp"], ["g"]),
    ],
)
def test_declarations_define_the_declared_name_and_use_the_initializer(
    statement, definitions, uses
):
    check(statement, definitions, uses)


@pytest.mark.parametrize(
    "statement, definitions, uses",
    [
        ("x = 1;", ["x"], []),
        ("x = y;", ["x"], ["y"]),
        ("a = b = c;", ["a", "b"], ["c"]),
        ("x += y;", ["x"], ["x", "y"]),
        ("x++;", ["x"], ["x"]),
    ],
)
def test_assignment_to_a_name(statement, definitions, uses):
    check(statement, definitions, uses)


@pytest.mark.parametrize(
    "statement, definitions, uses",
    [
        ("a[0] = x;", ["a"], ["a", "x"]),
        ("a[i][j] = v;", ["a"], ["a", "i", "j", "v"]),
        ("s.f = x;", ["s"], ["s", "x"]),
        ("s.inner.f = x;", ["s"], ["s", "x"]),
        ("a[i].f = v;", ["a"], ["a", "i", "v"]),
        ("a[i] += 1;", ["a"], ["a", "i"]),
        ("a[i]++;", ["a"], ["a", "i"]),
    ],
)
def test_writes_through_subscripts_and_members_are_weak_updates(
    statement, definitions, uses
):
    check(statement, definitions, uses)


@pytest.mark.parametrize(
    "statement, definitions, uses",
    [
        ("p->f = x;", [], ["p", "x"]),
        ("*p = x;", [], ["p", "x"]),
        ("p->arr[0] = x;", [], ["p", "x"]),
        ("arr[i]->f = x;", [], ["arr", "i", "x"]),
        ("p->n++;", [], ["p"]),
    ],
)
def test_writes_through_a_pointer_do_not_define_the_pointer(
    statement, definitions, uses
):
    check(statement, definitions, uses)


@pytest.mark.parametrize(
    "signature, parameters",
    [
        ("int a, int b", ["a", "b"]),
        ("int *p", ["p"]),
        ("int **pp", ["pp"]),
        ("char *q[]", ["q"]),
        ("int (*fp)(int)", ["fp"]),
    ],
)
def test_parameters_are_defined_on_entry_and_are_not_uses(signature, parameters):
    builder = CFGBuilder("c")
    builder.setup_parser()
    cfg = builder.build_cfg(f"int f({signature}) {{ return 0; }}")

    entry = cfg.nodes[cfg.entry_node_ids[0]]
    assert entry.metadata.variable_definitions == parameters
    assert entry.metadata.variable_uses == []


def def_use_chains(code: str, variable: str):
    builder = CFGBuilder("c")
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
    def test_pointer_initializer_defines_the_pointer_and_not_its_source(self):
        code = "int g(int *p) { int *q = p; return *q; }"

        assert def_use_chains(code, "p") == {"g": ["int *q = p;"]}
        assert def_use_chains(code, "q") == {"int *q = p;": ["return *q;"]}

    def test_array_element_write_does_not_redefine_the_value_written(self):
        code = "int f(int n, int m) { int a[4]; a[0] = n; n = m; return a[0] + n; }"

        assert def_use_chains(code, "n") == {
            "f": ["a[0] = n;"],
            "n = m;": ["return a[0] + n;"],
        }
        assert def_use_chains(code, "a") == {"a[0] = n;": ["return a[0] + n;"]}

    def test_member_write_keeps_the_earlier_definition_flowing(self):
        code = "int h(struct S s, int x) { s.f = x; return s.g; }"

        assert def_use_chains(code, "s") == {
            "h": ["s.f = x;"],
            "s.f = x;": ["return s.g;"],
        }
