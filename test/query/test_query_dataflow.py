"""Def-use and use-def queries, data-flow edges and data-flow paths."""

import pytest
from query_helpers import pair, LANGUAGES, build, ids, roles

from tree_climber.dataflow.analyses.def_use import DefUseSolver
from tree_climber.dataflow.analyses.reaching_definitions import (
    ReachingDefinitionsProblem,
)
from tree_climber.dataflow.analyses.use_def import UseDefSolver
from tree_climber.dataflow.solver import RoundRobinSolver
from tree_climber.query import DEF_USE, CodeGraph, DataFlowEdge


def expected(graph, mapping):
    return {
        roles(graph)[key].id: sorted(roles(graph)[value].id for value in values)
        for key, values in mapping.items()
    }


@LANGUAGES
def test_def_use_per_variable(language):
    graph = build(language)

    assert graph.def_use("x") == expected(graph, {"src": ["clean"]})
    assert graph.def_use("y") == expected(
        graph, {"clean": ["cond", "sink", "acc"], "reset": ["acc"]}
    )
    assert graph.def_use("total") == expected(
        graph, {"zero": ["loop", "acc", "ret"], "acc": ["loop", "acc", "ret"]}
    )
    assert graph.def_use("n") == expected(graph, {"helper_entry": ["helper_ret"]})
    assert graph.def_use("r") == expected(graph, {"ret": ["out"]})


@LANGUAGES
def test_use_def_per_variable(language):
    graph = build(language)

    assert graph.use_def("x") == expected(graph, {"clean": ["src"]})
    assert graph.use_def("y") == expected(
        graph, {"cond": ["clean"], "sink": ["clean"], "acc": ["clean", "reset"]}
    )
    assert graph.use_def("total") == expected(
        graph, {"loop": ["zero", "acc"], "acc": ["zero", "acc"], "ret": ["zero", "acc"]}
    )
    assert graph.use_def("r") == expected(graph, {"out": ["ret"]})


@LANGUAGES
def test_unknown_variables_have_no_chains(language):
    graph = build(language)

    assert graph.def_use("nothing") == {}
    assert graph.use_def("nothing") == {}


def test_a_use_without_a_definition_maps_to_nothing():
    graph = CodeGraph.from_source("python", "y = x + 1\n")
    use = graph.by_text("y = x + 1")[0]

    assert graph.use_def("x") == {use.id: []}
    assert graph.def_use("x") == {}


@LANGUAGES
def test_use_def_is_the_inverse_of_def_use(language):
    graph = build(language)

    for variable in ("x", "y", "total", "n", "r"):
        inverse = {}
        for definition, uses in graph.def_use(variable).items():
            for use in uses:
                inverse.setdefault(use, []).append(definition)
        assert graph.use_def(variable) == {
            use: sorted(definitions) for use, definitions in sorted(inverse.items())
        }


@LANGUAGES
def test_chains_agree_with_the_solvers(language):
    graph = build(language)
    reaching = RoundRobinSolver().solve(graph.cfg, ReachingDefinitionsProblem())
    chains = DefUseSolver().solve(graph.cfg, reaching).chains
    use_def = UseDefSolver().solve(graph.cfg, reaching).chains

    for variable, variable_chains in chains.items():
        assert graph.def_use(variable) == {
            chain.definition: chain.uses
            for chain in sorted(variable_chains, key=lambda c: c.definition)
        }
    for variable, variable_chains in use_def.items():
        assert graph.use_def(variable) == {
            chain.use: sorted(chain.definitions)
            for chain in sorted(variable_chains, key=lambda c: c.use)
        }


@LANGUAGES
def test_data_flow_edges(language):
    graph = build(language)
    found = roles(graph)
    edges = graph.data_flow_edges()

    assert all(edge.kind == DEF_USE for edge in edges)
    assert all(edge.source_variable == edge.target_variable for edge in edges)
    assert DataFlowEdge(found["src"].id, "x", found["clean"].id, "x", DEF_USE) in edges
    assert (
        DataFlowEdge(found["acc"].id, "total", found["acc"].id, "total", DEF_USE)
        in edges
    )
    assert (
        DataFlowEdge(found["reset"].id, "y", found["clean"].id, "y", DEF_USE)
        not in edges
    )
    by_variable = {}
    for edge in edges:
        by_variable.setdefault(edge.source_variable, []).append(edge)
    for variable, variable_edges in by_variable.items():
        listed = sum(len(uses) for uses in graph.def_use(variable).values())
        assert len(variable_edges) == listed
    assert len(set(edges)) == len(edges)


@LANGUAGES
def test_data_flow_edges_append_extra_edges_once(language):
    graph = build(language)
    found = roles(graph)
    extra = DataFlowEdge(
        found["ret"].id, "total", found["helper_entry"].id, "n", "argument"
    )

    edges = graph.data_flow_edges([extra, extra])

    assert edges[-1] == extra
    assert edges.count(extra) == 1
    assert edges[:-1] == graph.data_flow_edges()
    assert extra not in graph.data_flow_edges()


@LANGUAGES
def test_extra_edges_show_up_in_def_use_and_use_def(language):
    graph = build(language)
    found = roles(graph)
    extra = DataFlowEdge(
        found["ret"].id, "total", found["helper_entry"].id, "n", "argument"
    )

    assert graph.def_use("total", [extra])[found["ret"].id] == [
        found["helper_entry"].id
    ]
    assert found["ret"].id not in graph.def_use("total")
    assert graph.use_def("n", [extra])[found["helper_entry"].id] == [found["ret"].id]
    assert found["helper_entry"].id not in graph.use_def("n")
    assert graph.def_use("x", [extra]) == graph.def_use("x")
    with pytest.raises(KeyError):
        graph.def_use("total", [DataFlowEdge(999, "total", 0, "n", "argument")])


@LANGUAGES
def test_data_flow_path_follows_the_chain(language):
    graph = build(language)
    path = graph.data_flow_path(*pair(graph, "src", "sink"))

    assert path is not None
    assert path.nodes == ids(graph, "src", "clean", "sink")
    assert path.edges == [DEF_USE, DEF_USE]
    assert [step.variable for step in path] == [None, "x", "y"]


@LANGUAGES
def test_data_flow_path_is_shortest_in_steps(language):
    graph = build(language)

    path = graph.data_flow_path(*pair(graph, "src", "out"))
    assert path is not None
    assert path.nodes == ids(graph, "src", "clean", "acc", "ret", "out")
    assert [step.variable for step in path] == [None, "x", "y", "total", "r"]
    direct = graph.data_flow_path(*pair(graph, "zero", "ret"))
    assert direct is not None and direct.nodes == ids(graph, "zero", "ret")


@LANGUAGES
def test_data_flow_path_between_unrelated_nodes_is_none(language):
    graph = build(language)

    assert graph.data_flow_path(*pair(graph, "sink", "src")) is None
    assert graph.data_flow_path(*pair(graph, "reset", "sink")) is None
    assert graph.data_flow_path(*pair(graph, "out", "src")) is None
    assert graph.data_flow_path(*pair(graph, "src", "helper_ret")) is None


@LANGUAGES
def test_data_flow_path_to_itself_is_one_node(language):
    graph = build(language)
    path = graph.data_flow_path(*pair(graph, "acc", "acc"))

    assert path is not None
    assert path.nodes == ids(graph, "acc") and path.edges == []


@LANGUAGES
def test_data_flow_path_variable_and_avoid(language):
    graph = build(language)
    found = roles(graph)

    assert graph.data_flow_path(found["src"], found["sink"], variable="x") is not None
    assert graph.data_flow_path(found["clean"], found["sink"], variable="y") is not None
    assert graph.data_flow_path(found["clean"], found["acc"], variable="x") is not None
    with pytest.raises(ValueError):
        graph.data_flow_path(found["src"], found["sink"], variable="y")
    assert (
        graph.data_flow_path(found["src"], found["sink"], avoid=[found["clean"]])
        is None
    )
    assert (
        graph.data_flow_path(found["src"], found["out"], avoid=[found["zero"]])
        is not None
    )
    assert (
        graph.data_flow_path(found["src"], found["out"], avoid=[found["acc"]]) is None
    )
    ends = graph.data_flow_path(
        found["src"], found["clean"], avoid=[found["src"], found["clean"]]
    )
    assert ends is not None and len(ends) == 2


@LANGUAGES
def test_data_flow_path_renders_variable_arrows(language):
    graph = build(language)
    path = graph.data_flow_path(*pair(graph, "src", "sink"))

    assert path is not None
    lines = str(path).splitlines()
    assert lines[1].startswith("  --def_use x--> [")
    assert lines[2].startswith("  --def_use y--> [")


@LANGUAGES
def test_all_data_flow_paths(language):
    graph = build(language)

    paths = graph.data_flow_paths(*pair(graph, "zero", "ret"))
    assert sorted(path.nodes for path in paths) == sorted(
        [ids(graph, "zero", "ret"), ids(graph, "zero", "acc", "ret")]
    )
    only = graph.data_flow_paths(*pair(graph, "src", "out"))
    assert [path.nodes for path in only] == [
        ids(graph, "src", "clean", "acc", "ret", "out")
    ]


@LANGUAGES
def test_all_data_flow_paths_respect_bounds(language):
    graph = build(language)
    source, target = ids(graph, "zero", "ret")

    assert len(graph.data_flow_paths(source, target, max_paths=1)) == 1
    assert len(graph.data_flow_paths(source, target, max_paths=2)) == 2
    assert len(graph.data_flow_paths(source, target, max_length=2)) == 2
    one_step = graph.data_flow_paths(source, target, max_length=1)
    assert [path.nodes for path in one_step] == [[source, target]]
    assert graph.data_flow_paths(source, target, max_length=0) == []
    with pytest.raises(ValueError):
        graph.data_flow_paths(source, target, max_paths=0)
    with pytest.raises(ValueError):
        graph.data_flow_paths(source, target, max_length=-1)


@LANGUAGES
def test_all_data_flow_paths_do_not_loop_on_loop_carried_flow(language):
    graph = build(language)

    paths = graph.data_flow_paths(*pair(graph, "acc", "ret"))
    assert [path.nodes for path in paths] == [ids(graph, "acc", "ret")]
    assert graph.data_flow_paths(*pair(graph, "acc", "acc")) != []
    assert graph.data_flow_paths(*pair(graph, "ret", "src")) == []


@LANGUAGES
def test_all_data_flow_paths_variable_avoid_and_dedupe(language):
    graph = build(language)
    found = roles(graph)

    through = graph.data_flow_paths(found["clean"], found["ret"], variable="y")
    assert [path.nodes for path in through] == [ids(graph, "clean", "acc", "ret")]
    assert (
        graph.data_flow_paths(found["clean"], found["ret"], avoid=[found["acc"]]) == []
    )
    again = graph.data_flow_paths(found["src"], found["ret"])
    assert len(again) == len({tuple(path.steps) for path in again})
