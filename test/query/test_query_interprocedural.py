"""Interprocedural flows as `DataFlowEdge`s: data-flow queries that cross calls."""

import pytest

from tree_climber.dataflow.interprocedural import analyze_interprocedural
from tree_climber.query import (
    ARGUMENT,
    FREE_VARIABLE,
    RETURN,
    CodeGraph,
    DataFlowEdge,
    interprocedural_edges,
)
from tree_climber.query.edges import _receiver_variables

ACROSS_A_CALL = {
    "python": "def g(p):\n    system(p)\n\n\ndef f():\n    x = input()\n    g(x)\n",
    "c": "void g(char *p) { system(p); }\nvoid f() { char *x = input(); g(x); }\n",
    "java": "class A { void g(String p) { system(p); } void f() { String x = input(); g(x); } }",
}

OUT_OF_A_CALL = {
    "python": "def read():\n    return input()\n\n\ndef f():\n    y = read()\n    system(y)\n",
    "c": "int read() { return input(); }\nvoid f() { int y = read(); system(y); }\n",
    "java": "class A { String read() { return input(); } void f() { String y = read(); system(y); } }",
}

LANGUAGES = pytest.mark.parametrize("language", ["c", "java", "python"])


def flow(graph, source, target, edges=None):
    path = graph.data_flow_path(source, target, extra_edges=edges)
    return None if path is None else [(step.edge, step.variable) for step in path.steps]


@LANGUAGES
def test_an_argument_flows_into_the_callee(language):
    graph = CodeGraph.from_source(language, ACROSS_A_CALL[language])
    source, sink = graph.calling("input")[0], graph.calling("system")[0]

    assert graph.data_flow_path(source, sink) is None
    assert flow(graph, source, sink, graph.interprocedural_edges()) == [
        (None, None),
        ("def_use", "x"),
        (ARGUMENT, "p"),
        ("def_use", "p"),
    ]


@LANGUAGES
def test_a_return_flows_into_the_assignment(language):
    graph = CodeGraph.from_source(language, OUT_OF_A_CALL[language])
    source, sink = graph.calling("input")[0], graph.calling("system")[0]

    assert graph.data_flow_path(source, sink) is None
    assert flow(graph, source, sink, graph.interprocedural_edges()) == [
        (None, None),
        (RETURN, "y"),
        ("def_use", "y"),
    ]


def test_a_return_into_a_call_that_is_not_assigned():
    source = "def read():\n    return input()\n\n\ndef f():\n    system(read())\n"
    graph = CodeGraph.from_source("python", source)
    ret, sink = graph.by_text("return input()")[0], graph.calling("system")[0]

    assert DataFlowEdge(ret.id, "<return>", sink.id, "<call 1>", RETURN) in (
        graph.interprocedural_edges()
    )
    assert flow(graph, ret, sink, graph.interprocedural_edges()) == [
        (None, None),
        (RETURN, "<call 1>"),
    ]


def test_a_nested_call_that_returns_flows_on_as_the_argument():
    source = (
        "def read():\n    return input()\n\n\n"
        "def g(p):\n    system(p)\n\n\n"
        "def f():\n    g(read())\n"
    )
    graph = CodeGraph.from_source("python", source)
    edges = graph.interprocedural_edges()
    ret, call, sink = (
        graph.by_text("return input()")[0],
        graph.by_text("g(read())")[0],
        graph.calling("system")[0],
    )
    g_entry = graph.function_of(sink)
    assert g_entry is not None

    assert DataFlowEdge(call.id, "<call 1>", g_entry.id, "p", ARGUMENT) in edges
    assert flow(graph, ret, sink, edges) == [
        (None, None),
        (RETURN, "<call 1>"),
        (ARGUMENT, "p"),
        ("def_use", "p"),
    ]


def test_a_nested_call_without_a_return_adds_no_placeholder():
    source = "def g(p):\n    system(p)\n\n\ndef f(x):\n    g(strip(x))\n"
    graph = CodeGraph.from_source("python", source)
    call = graph.by_text("g(strip(x))")[0]

    sources = [
        e.source_variable for e in graph.interprocedural_edges() if e.source == call.id
    ]
    assert sorted(sources) == ["strip", "x"]


def test_the_receiver_flows_into_self():
    source = (
        "class R:\n    def go(self, c):\n        system(c)\n\n\n"
        "def f():\n    x = input()\n    r = R()\n    r.go(x)\n"
    )
    graph = CodeGraph.from_source("python", source)
    call = graph.by_text("r.go(x)")[0]
    go = [entry for entry in graph.functions() if entry.source_text == "R.go"][0]

    edges = [e for e in graph.interprocedural_edges() if e.source == call.id]
    assert edges == [
        DataFlowEdge(call.id, "r", go.id, "self", ARGUMENT),
        DataFlowEdge(call.id, "x", go.id, "c", ARGUMENT),
    ]


def test_receiver_variables_are_the_names_it_reads():
    uses = ["self", "data", "k", "Runner", "a"]

    assert _receiver_variables("self.data", uses) == ["self"]
    assert _receiver_variables("Runner(True)", uses) == []
    assert _receiver_variables("a_b.c", uses) == []
    assert _receiver_variables("(a + k)", uses) == ["k", "a"]


def test_a_constructor_receiver_binds_nothing():
    source = (
        "class Runner:\n    def __init__(self, shell):\n        self.shell = shell\n\n"
        "    def go(self, cmd):\n        system(cmd)\n\n\n"
        "def f(x):\n    Runner(True).go(x)\n"
    )
    graph = CodeGraph.from_source("python", source)
    call = graph.by_text("Runner(True).go(x)")[0]
    go = [entry for entry in graph.functions() if entry.source_text == "Runner.go"][0]

    into_go = [e for e in graph.interprocedural_edges() if e.target == go.id]
    assert into_go == [DataFlowEdge(call.id, "x", go.id, "cmd", ARGUMENT)]


def test_closures_and_globals_are_free_variable_edges():
    source = (
        "LIMIT = input()\n\n\n"
        "def outer():\n    x = input()\n\n"
        "    def inner():\n        system(x + LIMIT)\n\n    inner()\n"
    )
    graph = CodeGraph.from_source("python", source)
    edges = graph.interprocedural_edges()
    limit, x, sink = (
        graph.by_text("LIMIT = input()")[0],
        graph.by_text("x = input()")[0],
        graph.calling("system")[0],
    )

    assert DataFlowEdge(limit.id, "LIMIT", sink.id, "LIMIT", FREE_VARIABLE) in edges
    assert DataFlowEdge(x.id, "x", sink.id, "x", FREE_VARIABLE) in edges
    assert flow(graph, x, sink, edges) == [(None, None), (FREE_VARIABLE, "x")]


def test_c_globals_are_free_variable_edges():
    source = "char *g;\nvoid set() { g = input(); }\nvoid use() { system(g); }\n"
    graph = CodeGraph.from_source("c", source)
    write, sink = graph.by_text("g = input();")[0], graph.calling("system")[0]

    assert graph.interprocedural_edges() == [
        DataFlowEdge(write.id, "g", sink.id, "g", FREE_VARIABLE)
    ]


def test_value_in_through_an_argument_and_out_through_a_return():
    source = (
        "def wrap(v):\n    return v\n\n\n"
        "def f():\n    x = input()\n    y = wrap(x)\n    system(y)\n"
    )
    graph = CodeGraph.from_source("python", source)
    edges = graph.interprocedural_edges()
    entry = graph.functions()[0]
    ret, call = graph.by_text("return v")[0], graph.by_text("y = wrap(x)")[0]

    assert DataFlowEdge(call.id, "x", entry.id, "v", ARGUMENT) in edges
    assert DataFlowEdge(ret.id, "<return>", call.id, "y", RETURN) in edges
    assert flow(graph, entry, call, edges) == [
        (None, None),
        ("def_use", "v"),
        (RETURN, "y"),
    ]


def test_every_flow_has_an_edge():
    source = (
        "class R:\n    def go(self, c, *rest, k=1, **kw):\n        return c\n\n\n"
        "def wrap(v):\n    return v\n\n\n"
        "def f(a, b):\n    r = R()\n    y = r.go(a, b, k=a, z=b)\n    return wrap(y)\n"
    )
    graph = CodeGraph.from_source("python", source)
    flows = analyze_interprocedural(graph.cfg)
    edges = graph.interprocedural_edges()

    for argument in flows.argument_flows:
        assert any(
            e.kind == ARGUMENT
            and e.source == argument.call.node
            and e.target == argument.callee
            and e.target_variable == argument.parameter
            for e in edges
        )
    for returned in flows.return_flows:
        assert any(
            e.kind == RETURN
            and e.source == returned.return_node
            and e.target == returned.call.node
            for e in edges
        )
    assert len(edges) == len(set(edges))


def test_the_graph_computes_the_edges_once_and_returns_a_copy():
    graph = CodeGraph.from_source("python", ACROSS_A_CALL["python"])
    edges = graph.interprocedural_edges()

    assert edges == interprocedural_edges(graph.cfg)
    edges.clear()
    assert graph.interprocedural_edges() != []


def test_a_nested_call_flows_only_to_the_argument_it_is():
    source = (
        "def read():\n    return input()\n\n\n"
        "def h(v):\n    return v\n\n\n"
        "def g(a, b):\n    system(b)\n\n\n"
        "def f(x):\n    g(x, h(read()))\n"
    )
    graph = CodeGraph.from_source("python", source)
    call = graph.by_text("g(x, h(read()))")[0]
    entries = {entry.source_text: entry.id for entry in graph.functions()}

    from_call = sorted(
        (e.source_variable, e.target, e.target_variable)
        for e in graph.interprocedural_edges()
        if e.source == call.id
    )
    assert from_call == sorted(
        [
            ("<call 1>", entries["g"], "b"),
            ("<call 2>", entries["h"], "v"),
            ("h", entries["g"], "b"),
            ("read", entries["g"], "b"),
            ("read", entries["h"], "v"),
            ("x", entries["g"], "a"),
        ]
    )


def test_the_same_flow_twice_is_one_edge():
    source = "def f(*rest):\n    return rest\n\n\ndef g(x):\n    f(x, x)\n"
    graph = CodeGraph.from_source("python", source)
    call = graph.by_text("f(x, x)")[0]

    assert len(analyze_interprocedural(graph.cfg).argument_flows) == 2
    assert [e for e in graph.interprocedural_edges() if e.source == call.id] == [
        DataFlowEdge(call.id, "x", graph.functions()[0].id, "rest", ARGUMENT)
    ]


def test_the_edges_are_built_from_the_flows_the_graph_already_has(monkeypatch):
    graph = CodeGraph.from_source("python", "def f(a):\n    return a\n\n\nx = f(1)\n")
    flows = graph.interprocedural_flows

    def recomputed(cfg):
        raise AssertionError("recomputed")

    monkeypatch.setattr("tree_climber.query.edges.analyze_interprocedural", recomputed)

    assert graph.interprocedural_edges() == interprocedural_edges(graph.cfg, flows)
    assert graph.interprocedural_edges()
