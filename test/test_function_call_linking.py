"""
Tests for linking calls to the functions they call, in C, Java, and Python.

Calls are linked after the whole file is visited, so a call can reach a function
defined later in the file. Each scenario runs for every language.
"""

from typing import List, Set, Tuple

import pytest

from tree_climber.cfg.builder import CFGBuilder
from tree_climber.cfg.cfg_types import NodeType
from tree_climber.cfg.visitor import CFG

LANGUAGES = ["c", "java", "python"]

SCENARIOS = {
    "forward": {
        "c": "int main() { return helper(); }\nint helper() { return 1; }\n",
        "java": "class A { int main() { return helper(); } int helper() { return 1; } }",
        "python": "def main():\n    return helper()\n\ndef helper():\n    return 1\n",
    },
    "backward": {
        "c": "int helper() { return 1; }\nint main() { return helper(); }\n",
        "java": "class A { int helper() { return 1; } int main() { return helper(); } }",
        "python": "def helper():\n    return 1\n\ndef main():\n    return helper()\n",
    },
    "two_callees": {
        "c": (
            "int a() { return 1; }\n"
            "int f() { return a() + b(); }\n"
            "int b() { return 2; }\n"
        ),
        "java": (
            "class A { int a() { return 1; } int f() { return a() + b(); }"
            " int b() { return 2; } }"
        ),
        "python": (
            "def a():\n    return 1\n\n"
            "def f():\n    return a() + b()\n\n"
            "def b():\n    return 2\n"
        ),
    },
    "mutual": {
        "c": (
            "int even(int n) { return odd(n - 1); }\n"
            "int odd(int n) { return even(n - 1); }\n"
        ),
        "java": (
            "class A { int even(int n) { return odd(n - 1); }"
            " int odd(int n) { return even(n - 1); } }"
        ),
        "python": (
            "def even(n):\n    return odd(n - 1)\n\n"
            "def odd(n):\n    return even(n - 1)\n"
        ),
    },
    "recursion": {
        "c": "int f(int n) { return f(n - 1); }\n",
        "java": "class A { int f(int n) { return f(n - 1); } }",
        "python": "def f(n):\n    return f(n - 1)\n",
    },
    "undefined": {
        "c": 'int f() { printf("x"); return 0; }\n',
        "java": 'class A { int f() { System.out.println("x"); return 0; } }',
        "python": 'def f():\n    print("x")\n    return 0\n',
    },
}


def build(language: str, scenario: str) -> CFG:
    builder = CFGBuilder(language)
    builder.setup_parser()
    return builder.build_cfg(SCENARIOS[scenario][language])


def name(cfg: CFG, node_id: int) -> str:
    node = cfg.nodes[node_id]
    if node.node_type in (NodeType.ENTRY, NodeType.EXIT):
        return f"{node.node_type.name}:{node.source_text}"
    return node.source_text.strip()


def call_edges(cfg: CFG) -> Set[Tuple[str, str, str]]:
    return {
        (name(cfg, node.id), name(cfg, successor), label)
        for node in cfg.nodes.values()
        for successor, label in node.edge_labels.items()
        if label in ("function_call", "function_return")
    }


def callers_of(edges: Set[Tuple[str, str, str]], callee: str) -> List[str]:
    return sorted(
        source
        for source, target, label in edges
        if label == "function_call" and target == f"ENTRY:{callee}"
    )


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("scenario", ["forward", "backward"])
def test_a_call_is_linked_whether_the_callee_is_defined_before_or_after(
    language, scenario
):
    edges = call_edges(build(language, scenario))

    callers = callers_of(edges, "helper")
    assert len(callers) == 1 and callers[0].startswith("return helper()")
    assert ("EXIT:helper", callers[0], "function_return") in edges


@pytest.mark.parametrize("language", LANGUAGES)
def test_one_statement_calling_two_functions_links_both(language):
    edges = call_edges(build(language, "two_callees"))

    assert len(callers_of(edges, "a")) == 1
    assert callers_of(edges, "a") == callers_of(edges, "b")
    assert ("EXIT:a", callers_of(edges, "a")[0], "function_return") in edges
    assert ("EXIT:b", callers_of(edges, "b")[0], "function_return") in edges


@pytest.mark.parametrize("language", LANGUAGES)
def test_mutual_recursion_links_in_both_directions(language):
    edges = call_edges(build(language, "mutual"))

    assert callers_of(edges, "odd") == [
        next(s for s in callers_of(edges, "odd") if s.startswith("return odd("))
    ]
    assert callers_of(edges, "even") == [
        next(s for s in callers_of(edges, "even") if s.startswith("return even("))
    ]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_function_calling_itself_is_linked(language):
    edges = call_edges(build(language, "recursion"))

    caller = callers_of(edges, "f")[0]
    assert caller.startswith("return f(")
    assert ("EXIT:f", caller, "function_return") in edges


@pytest.mark.parametrize("language", LANGUAGES)
def test_calls_to_undefined_functions_get_no_edges(language):
    assert call_edges(build(language, "undefined")) == set()


def test_overloads_are_all_linked_and_each_returns_from_its_own_exit():
    builder = CFGBuilder("java")
    builder.setup_parser()
    cfg = builder.build_cfg(
        "class A { void m(int x) {} void m(String s) {} void n() { m(1); } }"
    )

    call_node = next(n for n in cfg.nodes.values() if n.source_text == "m(1);")
    entries = [
        successor
        for successor, label in call_node.edge_labels.items()
        if label == "function_call"
    ]
    returning_exits = {
        node.id
        for node in cfg.nodes.values()
        if node.edge_labels.get(call_node.id) == "function_return"
    }

    assert len(entries) == 2
    assert len(returning_exits) == 2
    assert returning_exits == {
        exit_id
        for entry_id, exit_id in zip(cfg.entry_node_ids, cfg.exit_node_ids)
        if entry_id in entries
    }
