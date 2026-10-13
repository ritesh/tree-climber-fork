"""The networkx export."""

import itertools

import networkx as nx
from query_helpers import pair, LANGUAGES, build, roles

from tree_climber.query import DEF_USE, DataFlowEdge


@LANGUAGES
def test_nodes_carry_their_attributes(language):
    graph = build(language)
    exported = graph.to_networkx()

    assert isinstance(exported, nx.MultiDiGraph)
    assert sorted(exported.nodes) == sorted(graph.cfg.nodes)
    found = roles(graph)
    clean = exported.nodes[found["clean"].id]
    assert clean["text"] == found["clean"].source_text
    assert clean["node_type"] == "STATEMENT"
    assert clean["function"] == "main"
    assert clean["calls"] == ["clean"]
    assert clean["definitions"] == ["y"]
    assert "x" in clean["uses"]
    assert exported.nodes[found["helper_entry"].id]["function"] == "helper"
    assert exported.nodes[found["helper_entry"].id]["node_type"] == "ENTRY"


@LANGUAGES
def test_control_edges_mirror_the_cfg(language):
    graph = build(language)
    exported = graph.to_networkx()
    found = roles(graph)

    expected = {
        (node.id, successor): graph.edge_kind(node, successor)
        for node in graph.nodes
        for successor in node.successors
    }
    actual = {(u, v): data["kind"] for u, v, data in exported.edges(data=True)}
    assert actual == expected
    assert exported.number_of_edges() == len(expected)
    assert all(data["layer"] == "control" for *_, data in exported.edges(data=True))
    assert exported.edges[found["cond"].id, found["sink"].id, 0]["kind"] == "true"
    assert exported.edges[found["ret"].id, found["helper_entry"].id, 0]["kind"] == (
        "function_call"
    )


@LANGUAGES
def test_data_flow_layer_is_optional(language):
    graph = build(language)
    found = roles(graph)

    plain = graph.to_networkx()
    assert not [d for *_, d in plain.edges(data=True) if d["layer"] == "data"]
    with_data = graph.to_networkx(data_flow=True)
    data = [(u, v, d) for u, v, d in with_data.edges(data=True) if d["layer"] == "data"]
    assert len(data) == len(graph.data_flow_edges())
    assert with_data.number_of_edges() == plain.number_of_edges() + len(data)
    assert all(d["kind"] == DEF_USE for *_, d in data)
    assert (found["src"].id, found["clean"].id) in {(u, v) for u, v, _ in data}
    sample = next(
        d for u, v, d in data if (u, v) == (found["src"].id, found["clean"].id)
    )
    assert sample["source_variable"] == "x" and sample["target_variable"] == "x"


@LANGUAGES
def test_parallel_control_and_data_edges_are_kept(language):
    graph = build(language)
    found = roles(graph)
    exported = graph.to_networkx(data_flow=True)

    between = exported.get_edge_data(found["src"].id, found["clean"].id)
    assert sorted(d["layer"] for d in between.values()) == ["control", "data"]


@LANGUAGES
def test_extra_edges_are_exported_with_their_kind(language):
    graph = build(language)
    found = roles(graph)
    extra = DataFlowEdge(
        found["ret"].id, "total", found["helper_entry"].id, "n", "argument"
    )

    exported = graph.to_networkx(data_flow=True, extra_edges=[extra])

    data = exported.get_edge_data(found["ret"].id, found["helper_entry"].id)
    argument = [d for d in data.values() if d["layer"] == "data"]
    assert argument == [
        {
            "layer": "data",
            "kind": "argument",
            "source_variable": "total",
            "target_variable": "n",
        }
    ]
    assert len(graph.to_networkx(data_flow=True).edges) + 1 == len(exported.edges)
    assert not any(
        d["layer"] == "data"
        for d in (
            graph.to_networkx().get_edge_data(found["ret"].id, found["helper_entry"].id)
            or {}
        ).values()
    )
    assert (
        graph.to_networkx(extra_edges=[extra]).number_of_edges()
        == graph.to_networkx().number_of_edges()
    )


@LANGUAGES
def test_networkx_agrees_with_the_query_layer(language):
    graph = build(language)
    exported = graph.to_networkx()

    for source, target in itertools.product(graph.nodes, repeat=2):
        assert graph.can_reach(source, target) == nx.has_path(
            exported, source.id, target.id
        )
        path = graph.shortest_path(source, target)
        if path is None:
            assert not nx.has_path(exported, source.id, target.id)
        else:
            assert len(path) - 1 == nx.shortest_path_length(
                exported, source.id, target.id
            )


@LANGUAGES
def test_data_layer_reachability_matches_slices(language):
    graph = build(language)
    exported = graph.to_networkx(data_flow=True)
    data_only = nx.MultiDiGraph(
        (u, v, d) for u, v, d in exported.edges(data=True) if d["layer"] == "data"
    )
    data_only.add_nodes_from(exported.nodes)

    for node in graph.nodes:
        reached = nx.descendants(data_only, node.id) | {node.id}
        assert {n.id for n in graph.forward_slice(node)} == reached
        ancestors = nx.ancestors(data_only, node.id) | {node.id}
        assert {n.id for n in graph.backward_slice(node)} == ancestors
    assert nx.has_path(data_only, *pair(graph, "src", "out"))
