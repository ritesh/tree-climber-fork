"""The examples in the "Querying the graph" section of docs/python-guide.md."""

import json

import pytest

from tree_climber.query import CALL_KINDS, CodeGraph, DataFlowEdge

SOURCE = """\
def handler(request):
    name = request.args.get("name")
    cmd = build(name)
    if cmd:
        os.system(cmd)
    else:
        cmd = "true"
    return finish(cmd)


def build(text):
    return "ls " + text


def finish(value):
    return value
"""


@pytest.fixture(scope="module")
def graph():
    return CodeGraph.from_source("python", SOURCE)


def texts(nodes):
    return [node.source_text for node in nodes]


def test_lookups(graph):
    assert texts(graph.calling("system")) == ["os.system(cmd)"]
    assert texts(graph.calling("os.system")) == ["os.system(cmd)"]
    assert texts(graph.defining("cmd")) == ["cmd = build(name)", 'cmd = "true"']
    assert texts(graph.using("cmd")) == ["cmd", "os.system(cmd)", "return finish(cmd)"]
    assert texts(graph.functions()) == ["handler", "build", "finish"]
    assert [node.id for node in graph.function_nodes("build")] == [9, 10, 11]


def test_flow_queries(graph):
    cond = graph.by_type("CONDITION")[0]
    call = graph.calling("finish")[0]
    entry = graph.functions()[0]
    finish = graph.function_nodes("finish")[0]
    done = graph.by_text("return finish(cmd)")[0]

    assert texts(graph.successors(cond, labels=["true"])) == ["os.system(cmd)"]
    assert texts(graph.successors(cond, labels=["false"])) == ['cmd = "true"']
    assert [
        (n.source_text, graph.edge_kind(call, n)) for n in graph.successors(call)
    ] == [
        ("handler", "flow"),
        ("finish", "function_call"),
    ]
    assert texts(graph.successors(call, exclude=CALL_KINDS)) == ["handler"]
    assert len(graph.reachable(entry)) == 14
    assert len(graph.reachable(entry, exclude=CALL_KINDS)) == 8
    assert graph.can_reach(entry, finish)
    assert not graph.can_reach(entry, finish, exclude=CALL_KINDS)
    assert str(graph.shortest_path(entry, graph.calling("system")[0])) == (
        "[0] ENTRY handler\n"
        '  --> [2] name = request.args.get("name")\n'
        "  --> [3] cmd = build(name)\n"
        "  --> [4] cmd\n"
        "  --true--> [6] os.system(cmd)"
    )
    assert len(graph.paths(entry, done, max_paths=1)) == 1
    assert graph.paths(entry, done, max_length=4) == []
    assert len(graph.paths(entry, done, max_length=5)) == 2


def test_data_flow_queries(graph):
    entry = graph.functions()[0]
    sink = graph.calling("system")[0]
    build_call = graph.calling("build")[0]

    assert graph.def_use("cmd") == {3: [4, 6, 8], 7: [8]}
    assert graph.use_def("cmd") == {4: [3], 6: [3], 8: [3, 7]}
    assert texts(graph.forward_slice(entry)) == [
        "handler",
        'name = request.args.get("name")',
        "cmd = build(name)",
        "cmd",
        "os.system(cmd)",
        "return finish(cmd)",
    ]
    assert texts(graph.backward_slice(sink)) == [
        "handler",
        'name = request.args.get("name")',
        "cmd = build(name)",
        "os.system(cmd)",
    ]
    path = graph.data_flow_path(build_call, sink)
    assert str(path) == "[3] cmd = build(name)\n  --def_use cmd--> [6] os.system(cmd)"
    assert graph.data_flow_path(graph.by_text('cmd = "true"')[0], sink) is None
    assert json.loads(json.dumps(path.to_dict()))["steps"][1] == {
        "node": 6,
        "node_type": "STATEMENT",
        "text": "os.system(cmd)",
        "edge": "def_use",
        "variable": "cmd",
    }


def test_extra_edges(graph):
    build_call = graph.calling("build")[0]
    build_entry = [n for n in graph.functions() if n.source_text == "build"][0]
    build_ret = graph.by_text('return "ls " + text')[0]
    edges = [
        DataFlowEdge(build_call.id, "name", build_entry.id, "text", "argument"),
        DataFlowEdge(build_ret.id, "text", build_call.id, "cmd", "return"),
    ]
    request = graph.by_text("name =")[0]

    assert texts(graph.forward_slice(request)) == [
        'name = request.args.get("name")',
        "cmd = build(name)",
        "cmd",
        "os.system(cmd)",
        "return finish(cmd)",
    ]
    assert texts(graph.forward_slice(request, extra_edges=edges)) == [
        'name = request.args.get("name")',
        "cmd = build(name)",
        "cmd",
        "os.system(cmd)",
        "return finish(cmd)",
        "build",
        'return "ls " + text',
    ]
    assert str(graph.data_flow_path(request, build_ret, extra_edges=edges)) == (
        '[2] name = request.args.get("name")\n'
        "  --def_use name--> [3] cmd = build(name)\n"
        "  --argument text--> [9] ENTRY build\n"
        '  --def_use text--> [11] return "ls " + text'
    )
    assert graph.data_flow_path(request, build_ret) is None


def test_the_taint_example():
    code = """\
def run(flag):
    data = input()
    safe = escape(data)
    system(safe)
    cmd = "ls " + data
    if flag:
        data = "constant"
    system(data)
    eval(cmd)
"""
    graph = CodeGraph.from_source("python", code)
    sanitizers = graph.calling("escape", "quote")
    lines = []
    for source in graph.calling("input", "getenv"):
        for sink in graph.calling("system", "eval", "execute"):
            path = graph.data_flow_path(source, sink, avoid=sanitizers)
            if path:
                lines.append(" -> ".join(path.texts))

    assert lines == [
        "data = input() -> system(data)",
        'data = input() -> cmd = "ls " + data -> eval(cmd)',
    ]


def test_interprocedural_edges(graph):
    req = graph.by_text("name =")[0]
    edges = graph.interprocedural_edges()

    assert edges == [
        DataFlowEdge(3, "name", 9, "text", "argument"),
        DataFlowEdge(8, "cmd", 12, "value", "argument"),
        DataFlowEdge(11, "<return>", 3, "cmd", "return"),
        DataFlowEdge(14, "<return>", 8, "<call 0>", "return"),
    ]
    path = graph.data_flow_path(
        req, graph.by_text("return value")[0], extra_edges=edges
    )
    assert str(path) == (
        '[2] name = request.args.get("name")\n'
        "  --def_use name--> [3] cmd = build(name)\n"
        "  --def_use cmd--> [8] return finish(cmd)\n"
        "  --argument value--> [12] ENTRY finish\n"
        "  --def_use value--> [14] return value"
    )
