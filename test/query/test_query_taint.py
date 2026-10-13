"""The prototype taint tracker from the epic (#44), rewritten against the query API.

`prototype` is the original: a traversal written directly against the CFG and the
def-use chains. `tracked` is the same analysis on `tree_climber.query`. The tests
check that they report the same findings, and pin the findings on the
`data_flow_patterns.py` fixture.
"""

from collections import deque
from pathlib import Path

import pytest

from tree_climber.cfg.builder import CFGBuilder
from tree_climber.dataflow.analyses.def_use import DefUseSolver
from tree_climber.dataflow.analyses.reaching_definitions import (
    ReachingDefinitionsProblem,
)
from tree_climber.dataflow.solver import RoundRobinSolver
from tree_climber.query import CodeGraph

SOURCES = {"input", "getenv", "source"}
SINKS = {"system", "eval", "execute", "sink"}
SANITIZERS = {"escape", "quote", "sanitize"}

FIXTURE = Path(__file__).parent.parent / "python_cfg" / "data_flow_patterns.py"


def prototype(code):
    builder = CFGBuilder("python")
    builder.setup_parser()
    cfg = builder.build_cfg(code)
    reaching = RoundRobinSolver().solve(cfg, ReachingDefinitionsProblem())
    chains = DefUseSolver().solve(cfg, reaching).chains
    uses = {
        (c.variable_name, c.definition): c.uses for cs in chains.values() for c in cs
    }

    def text(node_id):
        return cfg.nodes[node_id].source_text.splitlines()[0]

    tainted = {}
    work = deque()
    for node_id, node in cfg.nodes.items():
        if SOURCES & set(node.metadata.function_calls):
            for variable in node.metadata.variable_definitions:
                tainted[(variable, node_id)] = [text(node_id)]
                work.append((variable, node_id))
    while work:
        key = work.popleft()
        for use in uses.get(key, []):
            node = cfg.nodes[use]
            if SANITIZERS & set(node.metadata.function_calls):
                continue
            for variable in node.metadata.variable_definitions:
                if (variable, use) not in tainted:
                    tainted[(variable, use)] = tainted[key] + [text(use)]
                    work.append((variable, use))
    findings = set()
    for (variable, definition), path in tainted.items():
        for use in uses.get((variable, definition), []):
            if SINKS & set(cfg.nodes[use].metadata.function_calls):
                findings.add(tuple(path + [text(use)]))
    return findings


def tracked(code, language="python"):
    graph = CodeGraph.from_source(language, code)
    sanitizers = graph.calling(*SANITIZERS)
    return {
        tuple(path.texts)
        for source in graph.calling(*SOURCES)
        for sink in graph.calling(*SINKS)
        if (path := graph.data_flow_path(source, sink, avoid=sanitizers))
    }


def endpoints(findings):
    return {(path[0], path[-1]) for path in findings}


CASES = {
    "direct": "data = input()\nsystem(data)\n",
    "through_assignment": 'a = input()\nb = "ls " + a\nsystem(b)\n',
    "reassignment_kills": 'a = input()\na = "constant"\nsystem(a)\n',
    "sanitizer_blocks": "a = input()\nb = escape(a)\nsystem(b)\n",
    "sanitizer_on_the_way_but_not_on_every_path": (
        "def f(flag):\n"
        "    a = input()\n"
        "    if flag:\n"
        "        b = escape(a)\n"
        "    else:\n"
        "        b = a\n"
        "    system(b)\n"
    ),
    "branch": "def f(c):\n    if c:\n        v = input()\n    else:\n        v = 'x'\n    system(v)\n",
    "loop": "def f(items):\n    t = input()\n    for i in items:\n        t = t + i\n    eval(t)\n",
    "try": "def f():\n    v = 'safe'\n    try:\n        v = input()\n        risky(v)\n    except E:\n        system(v)\n",
    "with": "def f():\n    with open(input()) as h:\n        t = h.read()\n    system(t)\n",
    "subscript": "def f():\n    d = {}\n    d['k'] = input()\n    system(d)\n",
    "no_source": "x = 1\nsystem(x)\n",
    "no_sink": "x = input()\ny = x\n",
    "two_sinks": "x = input()\nsystem(x)\neval(x)\n",
    "two_sources": "x = input()\ny = getenv('H')\nexecute(x + y)\n",
    "sanitized_sink_itself": "x = input()\neval(escape(x))\n",
    "not_across_calls": "def f():\n    x = input()\n    g(x)\n\n\ndef g(p):\n    system(p)\n",
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_same_findings_as_the_prototype(name):
    found, original = tracked(CASES[name]), prototype(CASES[name])

    assert endpoints(found) == endpoints(original)
    assert found <= original


def test_a_source_to_sink_path_is_found():
    assert tracked(CASES["through_assignment"]) == {
        ("a = input()", 'b = "ls " + a', "system(b)")
    }


def test_reassignment_kills_the_flow():
    assert tracked(CASES["reassignment_kills"]) == set()


def test_a_sanitizer_on_the_only_path_blocks_the_flow():
    assert tracked(CASES["sanitizer_blocks"]) == set()


def test_a_path_around_the_sanitizer_is_still_found():
    assert tracked(CASES["sanitizer_on_the_way_but_not_on_every_path"]) == {
        ("a = input()", "b = a", "system(b)")
    }


def test_a_sanitizer_that_is_also_the_sink_is_still_reported():
    assert tracked(CASES["sanitized_sink_itself"]) == {
        ("x = input()", "eval(escape(x))")
    }


def test_flow_is_not_followed_across_calls():
    assert tracked(CASES["not_across_calls"]) == set()


def test_flow_across_calls_is_found_with_interprocedural_edges():
    graph = CodeGraph.from_source("python", CASES["not_across_calls"])
    source, sink = graph.calling("input")[0], graph.calling("system")[0]

    path = graph.data_flow_path(source, sink, extra_edges=graph.interprocedural_edges())
    assert path is not None
    assert path.texts == ["x = input()", "g(x)", "g", "system(p)"]


def test_loop_carried_flow_is_found():
    graph = CodeGraph.from_source("python", CASES["loop"])
    source, sink = graph.calling("input")[0], graph.calling("eval")[0]

    assert tracked(CASES["loop"]) == {("t = input()", "eval(t)")}
    paths = graph.data_flow_paths(source, sink)
    assert sorted(path.texts for path in paths) == [
        ["t = input()", "eval(t)"],
        ["t = input()", "t = t + i", "eval(t)"],
    ]


def test_the_fixture_has_the_same_findings_as_the_prototype():
    code = FIXTURE.read_text()

    assert tracked(code) == prototype(code)


def test_fixture_findings_by_function():
    graph = CodeGraph.from_source("python", FIXTURE.read_text())
    sanitizers = graph.calling(*SANITIZERS)
    found = {}
    for source in graph.calling(*SOURCES):
        for sink in graph.calling(*SINKS):
            path = graph.data_flow_path(source, sink, avoid=sanitizers)
            if path:
                function = graph.function_of(sink)
                assert function is not None
                found.setdefault(function.source_text, []).append(path.texts)

    assert found == {
        "straight_flow": [
            ["data = source()", 'command = "run " + data', "sink(command)"]
        ],
        "branch_merge": [["value = source()", "sink(value)"]],
        "one_branch_defines": [["value = source()", "sink(value)"]],
        "flow_through_try": [["value = source()", "sink(value)"]],
        "with_target": [
            ["with open(source()) as handle", "text = handle.read()", "sink(text)"]
        ],
        "container_write": [['table["key"] = source()', "sink(table)"]],
        "attribute_write": [["obj.value = source()", "sink(obj)"]],
    }


C_AND_JAVA = {
    "c": (
        "void f() { int a = input(); int b = a + 1; system(b); }",
        "void f() { int a = input(); a = 0; system(a); }",
        "void f() { int a = input(); int b = escape(a); system(b); }",
    ),
    "java": (
        "class A { void f() { int a = input(); int b = a + 1; system(b); } }",
        "class A { void f() { int a = input(); a = 0; system(a); } }",
        "class A { void f() { int a = input(); int b = escape(a); system(b); } }",
    ),
}


@pytest.mark.parametrize("language", sorted(C_AND_JAVA))
def test_taint_in_c_and_java(language):
    flows, killed, sanitized = C_AND_JAVA[language]

    assert tracked(flows, language) == {
        ("int a = input();", "int b = a + 1;", "system(b);")
    }
    assert tracked(killed, language) == set()
    assert tracked(sanitized, language) == set()
