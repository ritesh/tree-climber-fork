"""Forward and backward slices, with and without extra data-flow edges.

The extra edges are built by hand, the way an interprocedural analysis would
describe a call: the argument `total` flows to the parameter `n`, and the
callee's `n` flows back into the result `r` of the call.
"""

import pytest
from query_helpers import LANGUAGES, build, ids, named, roles

from tree_climber.query import CodeGraph, DataFlowEdge


def call_edges(graph):
    found = roles(graph)
    argument = DataFlowEdge(
        found["ret"].id, "total", found["helper_entry"].id, "n", "argument"
    )
    result = DataFlowEdge(found["helper_ret"].id, "n", found["ret"].id, "r", "return")
    return argument, result


@LANGUAGES
def test_forward_slice_from_the_source(language):
    graph = build(language)

    assert named(graph, graph.forward_slice(roles(graph)["src"])) == [
        "src",
        "clean",
        "cond",
        "sink",
        "loop",
        "acc",
        "ret",
        "out",
    ]


@LANGUAGES
def test_forward_slice_accepts_an_id(language):
    graph = build(language)
    found = roles(graph)

    assert graph.forward_slice(found["src"].id) == graph.forward_slice(found["src"])


@LANGUAGES
def test_forward_slice_stops_where_nothing_is_defined(language):
    graph = build(language)

    assert named(graph, graph.forward_slice(roles(graph)["sink"])) == ["sink"]
    assert named(graph, graph.forward_slice(roles(graph)["cond"])) == ["cond"]
    assert named(graph, graph.forward_slice(roles(graph)["out"])) == ["out"]


@LANGUAGES
def test_forward_slice_includes_loop_carried_flow(language):
    graph = build(language)

    assert named(graph, graph.forward_slice(roles(graph)["zero"])) == [
        "zero",
        "loop",
        "acc",
        "ret",
        "out",
    ]


@LANGUAGES
def test_forward_slice_is_not_the_whole_flow(language):
    graph = build(language)

    assert named(graph, graph.forward_slice(roles(graph)["reset"])) == [
        "reset",
        "loop",
        "acc",
        "ret",
        "out",
    ]
    assert roles(graph)["reset"] not in graph.forward_slice(roles(graph)["src"])
    assert roles(graph)["zero"] not in graph.forward_slice(roles(graph)["src"])
    assert roles(graph)["src"] not in graph.forward_slice(roles(graph)["clean"])


@LANGUAGES
def test_backward_slice(language):
    graph = build(language)
    found = roles(graph)

    assert named(graph, graph.backward_slice(found["sink"])) == ["src", "clean", "sink"]
    assert named(graph, graph.backward_slice(found["acc"])) == [
        "src",
        "clean",
        "reset",
        "zero",
        "acc",
    ]
    assert named(graph, graph.backward_slice(found["out"])) == [
        "src",
        "clean",
        "reset",
        "zero",
        "acc",
        "ret",
        "out",
    ]
    assert named(graph, graph.backward_slice(found["src"])) == ["src"]
    assert named(graph, graph.backward_slice(found["clean"].id)) == ["src", "clean"]


@LANGUAGES
def test_backward_slice_ignores_what_only_follows(language):
    graph = build(language)
    found = roles(graph)

    assert found["acc"] not in graph.backward_slice(found["sink"])
    assert found["reset"] not in graph.backward_slice(found["sink"])
    assert found["helper_ret"] not in graph.backward_slice(found["out"])


@LANGUAGES
def test_slices_with_a_variable(language):
    graph = build(language)
    found = roles(graph)

    assert named(graph, graph.backward_slice(found["acc"], variable="y")) == [
        "src",
        "clean",
        "reset",
        "acc",
    ]
    assert named(graph, graph.backward_slice(found["acc"], variable="total")) == [
        "src",
        "clean",
        "reset",
        "zero",
        "acc",
    ]
    assert named(graph, graph.forward_slice(found["clean"], variable="y")) == [
        "clean",
        "cond",
        "sink",
        "loop",
        "acc",
        "ret",
        "out",
    ]
    assert named(graph, graph.forward_slice(found["clean"], variable="x")) == named(
        graph, graph.forward_slice(found["clean"], variable="y")
    )


@LANGUAGES
def test_slice_variable_must_be_at_the_node(language):
    graph = build(language)
    found = roles(graph)

    with pytest.raises(ValueError):
        graph.forward_slice(found["src"], variable="total")
    with pytest.raises(ValueError):
        graph.backward_slice(found["src"], variable="total")
    with pytest.raises(KeyError):
        graph.forward_slice(999)
    with pytest.raises(KeyError):
        graph.backward_slice(999)


@LANGUAGES
def test_without_extra_edges_slices_stop_at_the_call(language):
    graph = build(language)
    found = roles(graph)

    assert named(graph, graph.backward_slice(found["helper_ret"])) == [
        "helper_entry",
        "helper_ret",
    ]
    assert found["helper_entry"] not in graph.forward_slice(found["src"])
    assert found["helper_ret"] not in graph.forward_slice(found["src"])


@LANGUAGES
def test_forward_slice_follows_extra_edges_into_the_callee(language):
    graph = build(language)
    found = roles(graph)
    argument, result = call_edges(graph)

    reached = graph.forward_slice(found["src"], extra_edges=[argument])
    assert named(graph, reached) == [
        "helper_entry",
        "helper_ret",
        "src",
        "clean",
        "cond",
        "sink",
        "loop",
        "acc",
        "ret",
        "out",
    ]
    both = graph.forward_slice(found["src"], extra_edges=[argument, result])
    assert both == reached


@LANGUAGES
def test_backward_slice_follows_extra_edges_into_the_caller(language):
    graph = build(language)
    found = roles(graph)
    argument, result = call_edges(graph)

    reached = graph.backward_slice(found["helper_ret"], extra_edges=[argument])
    assert named(graph, reached) == [
        "helper_entry",
        "helper_ret",
        "src",
        "clean",
        "reset",
        "zero",
        "acc",
        "ret",
    ]
    from_out = graph.backward_slice(found["out"], extra_edges=[argument, result])
    assert found["helper_entry"] in from_out
    assert found["helper_ret"] in from_out
    assert found["src"] in from_out


@LANGUAGES
def test_extra_edges_are_used_for_one_call_only(language):
    graph = build(language)
    found = roles(graph)
    argument, result = call_edges(graph)

    before = graph.forward_slice(found["src"])
    with_edges = graph.forward_slice(found["src"], extra_edges=[argument, result])
    after = graph.forward_slice(found["src"])

    assert with_edges != before
    assert after == before
    assert graph.data_flow_path(found["src"], found["helper_ret"]) is None
    assert (
        graph.data_flow_path(found["src"], found["helper_ret"], extra_edges=[argument])
        is not None
    )
    assert graph.data_flow_path(found["src"], found["helper_ret"]) is None
    assert graph.data_flow_edges() == graph.data_flow_edges(extra_edges=[])


@LANGUAGES
def test_extra_edges_may_be_any_iterable(language):
    graph = build(language)
    found = roles(graph)
    argument, result = call_edges(graph)

    from_list = graph.forward_slice(found["src"], extra_edges=[argument, result])

    assert (
        graph.forward_slice(found["src"], extra_edges=iter([argument, result]))
        == from_list
    )
    assert (
        graph.forward_slice(found["src"], extra_edges=(e for e in (argument, result)))
        == from_list
    )
    assert (
        graph.forward_slice(found["src"], extra_edges={argument, result}) == from_list
    )
    assert graph.forward_slice(found["src"], extra_edges=()) == graph.forward_slice(
        found["src"]
    )


@LANGUAGES
def test_extra_edges_are_variable_sensitive(language):
    graph = build(language)
    found = roles(graph)
    edge = DataFlowEdge(found["acc"].id, "y", found["helper_entry"].id, "n", "argument")

    assert found["helper_entry"] in graph.forward_slice(
        found["clean"], extra_edges=[edge]
    )
    assert found["helper_entry"] in graph.forward_slice(
        found["reset"], extra_edges=[edge]
    )
    assert found["helper_entry"] not in graph.forward_slice(
        found["zero"], extra_edges=[edge]
    )
    assert found["helper_entry"] not in graph.forward_slice(
        found["acc"], variable="total", extra_edges=[edge]
    )
    assert found["helper_entry"] in graph.forward_slice(
        found["acc"], variable="y", extra_edges=[edge]
    )


@LANGUAGES
def test_extra_edges_from_a_defined_variable(language):
    graph = build(language)
    found = roles(graph)
    edge = DataFlowEdge(
        found["zero"].id, "total", found["helper_entry"].id, "n", "copy"
    )

    assert found["helper_entry"] in graph.forward_slice(
        found["zero"], extra_edges=[edge]
    )
    assert found["helper_entry"] not in graph.forward_slice(
        found["src"], extra_edges=[edge]
    )
    back = graph.backward_slice(found["helper_ret"], extra_edges=[edge])
    assert named(graph, back) == ["helper_entry", "helper_ret", "zero"]


@LANGUAGES
def test_extra_edges_with_a_name_that_is_not_a_variable_there(language):
    graph = build(language)
    found = roles(graph)
    into_call = DataFlowEdge(
        found["helper_ret"].id, "<return>", found["ret"].id, "<result>", "return"
    )
    out_of_call = DataFlowEdge(
        found["ret"].id, "<result>", found["helper_entry"].id, "<arg>", "x"
    )

    forward = graph.forward_slice(found["helper_entry"], extra_edges=[into_call])
    assert named(graph, forward) == ["helper_entry", "helper_ret", "ret", "out"]
    backward = graph.backward_slice(found["out"], extra_edges=[into_call])
    assert found["helper_ret"] in backward
    assert found["helper_entry"] in backward
    assert found["src"] in backward
    chained = graph.forward_slice(
        found["helper_entry"], extra_edges=[into_call, out_of_call]
    )
    assert found["helper_entry"] in chained and found["out"] in chained


@LANGUAGES
def test_extra_edges_with_an_unknown_node_are_rejected(language):
    graph = build(language)
    found = roles(graph)
    bad_source = DataFlowEdge(999, "total", found["helper_entry"].id, "n", "argument")
    bad_target = DataFlowEdge(found["ret"].id, "total", 999, "n", "argument")

    with pytest.raises(KeyError):
        graph.forward_slice(found["src"], extra_edges=[bad_source])
    with pytest.raises(KeyError):
        graph.backward_slice(found["src"], extra_edges=[bad_target])


@LANGUAGES
def test_data_flow_path_through_extra_edges(language):
    graph = build(language)
    found = roles(graph)
    argument, result = call_edges(graph)

    path = graph.data_flow_path(
        found["src"], found["out"], extra_edges=[argument, result]
    )
    assert path is not None
    assert path.nodes == ids(graph, "src", "clean", "acc", "ret", "out")

    to_callee = graph.data_flow_path(
        found["src"], found["helper_ret"], extra_edges=[argument, result]
    )
    assert to_callee is not None
    assert to_callee.nodes == ids(
        graph, "src", "clean", "acc", "ret", "helper_entry", "helper_ret"
    )
    assert to_callee.edges == ["def_use", "def_use", "def_use", "argument", "def_use"]
    assert [step.variable for step in to_callee] == [None, "x", "y", "total", "n", "n"]
    assert "--argument n-->" in str(to_callee)


@LANGUAGES
def test_shortest_data_flow_path_prefers_the_extra_edge_when_shorter(language):
    graph = build(language)
    found = roles(graph)
    argument, result = call_edges(graph)

    path = graph.data_flow_path(
        found["ret"], found["out"], extra_edges=[argument, result]
    )
    assert path is not None
    assert path.nodes == ids(graph, "ret", "out")
    assert path.edges == ["def_use"]
    via_callee = graph.data_flow_path(
        found["ret"], found["out"], avoid=[], extra_edges=[argument, result]
    )
    assert via_callee == path
    detour = graph.data_flow_path(
        found["zero"], found["out"], extra_edges=[argument, result]
    )
    assert detour is not None
    assert len(detour) == 3


@LANGUAGES
def test_all_data_flow_paths_through_extra_edges(language):
    graph = build(language)
    found = roles(graph)
    argument, result = call_edges(graph)

    paths = graph.data_flow_paths(
        found["zero"], found["out"], extra_edges=[argument, result]
    )
    assert sorted(path.nodes for path in paths) == sorted(
        [
            ids(graph, "zero", "ret", "out"),
            ids(graph, "zero", "acc", "ret", "out"),
        ]
    )
    callee = graph.data_flow_paths(
        found["zero"], found["helper_ret"], extra_edges=[argument]
    )
    assert sorted(path.nodes for path in callee) == sorted(
        [
            ids(graph, "zero", "ret", "helper_entry", "helper_ret"),
            ids(graph, "zero", "acc", "ret", "helper_entry", "helper_ret"),
        ]
    )
    for max_length, count in ((2, 0), (3, 1), (4, 2)):
        bounded = graph.data_flow_paths(
            found["zero"],
            found["helper_ret"],
            max_length=max_length,
            extra_edges=[argument],
        )
        assert len(bounded) == count
    assert graph.data_flow_paths(found["zero"], found["helper_ret"]) == []


def test_two_arguments_stay_apart():
    source = (
        "def f(a, b):\n"
        "    return a\n"
        "\n\n"
        "def main():\n"
        "    p = input()\n"
        "    q = 1\n"
        "    r = f(p, q)\n"
        "    return r\n"
    )
    graph = CodeGraph.from_source("python", source)
    entry = [n for n in graph.functions() if n.source_text == "f"][0]
    ret = graph.by_text("return a")[0]
    call = graph.by_text("r = f(p, q)")[0]
    first = DataFlowEdge(call.id, "p", entry.id, "a", "argument")
    second = DataFlowEdge(call.id, "q", entry.id, "b", "argument")
    back = DataFlowEdge(ret.id, "a", call.id, "r", "return")
    tainted = graph.by_text("p = input()")[0]
    constant = graph.by_text("q = 1")[0]

    assert ret in graph.forward_slice(tainted, extra_edges=[first, second, back])
    assert entry in graph.forward_slice(tainted, extra_edges=[first, second, back])
    assert graph.data_flow_path(tainted, ret, extra_edges=[first, back]) is not None
    assert graph.data_flow_path(tainted, entry, extra_edges=[first]) is not None
    assert graph.data_flow_path(tainted, entry, extra_edges=[second]) is None
    assert graph.data_flow_path(constant, entry, extra_edges=[second]) is not None
    assert graph.data_flow_path(constant, entry, extra_edges=[first]) is None
    assert (
        graph.data_flow_path(constant, ret, extra_edges=[first, second, back]) is None
    )
    assert constant not in graph.backward_slice(ret, extra_edges=[first, second, back])
    assert tainted in graph.backward_slice(ret, extra_edges=[first, second, back])
