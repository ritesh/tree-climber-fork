"""Flow queries: edge-kind filters, reachability, shortest and bounded paths."""

import pytest
from query_helpers import pair, LANGUAGES, build, ids, named, roles

from tree_climber.query import (
    CALL_KINDS,
    EXCEPTION,
    FALSE,
    FLOW,
    FUNCTION_CALL,
    FUNCTION_RETURN,
    TRUE,
    CodeGraph,
)

TRY_SOURCE = """\
def f(a):
    try:
        b = g(a)
    except E:
        b = 0
    return b
"""


@LANGUAGES
def test_successors_and_predecessors_without_a_filter(language):
    graph = build(language)

    assert named(graph, graph.successors(roles(graph)["cond"])) == ["sink", "reset"]
    assert named(graph, graph.predecessors(roles(graph)["zero"])) == ["sink", "reset"]
    assert named(graph, graph.successors(roles(graph)["src"].id)) == ["clean"]
    assert graph.successors(roles(graph)["main_exit"]) == []
    assert graph.predecessors(roles(graph)["main_entry"]) == []


@LANGUAGES
def test_true_and_false_labels(language):
    graph = build(language)
    found = roles(graph)

    assert named(graph, graph.successors(found["cond"], labels=[TRUE])) == ["sink"]
    assert named(graph, graph.successors(found["cond"], labels=[FALSE])) == ["reset"]
    assert named(graph, graph.successors(found["loop"], labels=[TRUE])) == ["acc"]
    assert named(graph, graph.successors(found["loop"], labels=[FALSE])) == ["ret"]
    assert named(graph, graph.successors(found["cond"], labels=[TRUE, FALSE])) == [
        "sink",
        "reset",
    ]
    assert graph.successors(found["cond"], labels=[FLOW]) == []
    assert graph.successors(found["cond"], labels=[]) == []


@LANGUAGES
def test_flow_label_selects_unlabeled_edges(language):
    graph = build(language)
    found = roles(graph)

    assert named(graph, graph.successors(found["src"], labels=[FLOW])) == ["clean"]
    assert graph.successors(found["src"], labels=[TRUE]) == []
    assert named(graph, graph.successors(found["ret"], labels=[FLOW])) == ["out"]
    assert named(graph, graph.predecessors(found["loop"], labels=[FLOW])) == [
        "zero",
        "acc",
    ]


@LANGUAGES
def test_call_and_return_labels(language):
    graph = build(language)
    found = roles(graph)

    assert named(graph, graph.successors(found["ret"], labels=[FUNCTION_CALL])) == [
        "helper_entry"
    ]
    assert graph.successors(found["ret"], labels=[FUNCTION_RETURN]) == []
    assert named(
        graph, graph.successors(found["helper_exit"], labels=[FUNCTION_RETURN])
    ) == ["ret"]
    assert named(graph, graph.predecessors(found["ret"], labels=[FUNCTION_RETURN])) == [
        "helper_exit"
    ]
    assert named(
        graph, graph.predecessors(found["helper_entry"], labels=CALL_KINDS)
    ) == ["ret"]
    assert named(graph, graph.predecessors(found["ret"], labels=[FUNCTION_CALL])) == []


@LANGUAGES
def test_exclude_removes_kinds(language):
    graph = build(language)
    found = roles(graph)

    assert named(graph, graph.successors(found["ret"])) == ["helper_entry", "out"]
    assert named(graph, graph.successors(found["ret"], exclude=CALL_KINDS)) == ["out"]
    assert named(graph, graph.successors(found["cond"], exclude=[TRUE])) == ["reset"]
    assert named(
        graph, graph.predecessors(found["ret"], exclude=[FUNCTION_RETURN])
    ) == ["loop"]
    assert named(
        graph,
        graph.successors(
            found["ret"], labels=[FLOW, FUNCTION_CALL], exclude=CALL_KINDS
        ),
    ) == ["out"]


def test_exception_edges():
    graph = CodeGraph.from_source("python", TRY_SOURCE)
    entry = graph.functions()[0]
    body = graph.by_text("b = g(a)")[0]
    handler = graph.by_text("except E")[0]

    assert [n.id for n in graph.successors(entry, labels=[EXCEPTION])] == [handler.id]
    assert graph.edge_kind(entry, handler) == EXCEPTION
    assert graph.successors(entry, labels=[TRUE]) == []
    assert [n.id for n in graph.successors(entry, exclude=[EXCEPTION])] == [body.id]
    assert [n.id for n in graph.predecessors(handler, labels=[EXCEPTION])] == [entry.id]
    assert graph.predecessors(handler, exclude=[EXCEPTION]) == []
    assert [n.source_text for n in graph.successors(handler, labels=[TRUE])] == [
        "b = 0"
    ]
    assert graph.can_reach(entry, handler, labels=[EXCEPTION])
    assert not graph.can_reach(body, handler)
    path = graph.shortest_path(entry, graph.by_text("return b")[0], exclude=[EXCEPTION])
    assert path is not None and path.edges == [FLOW, FLOW]


@LANGUAGES
def test_edge_kind(language):
    graph = build(language)
    found = roles(graph)

    assert graph.edge_kind(found["src"], found["clean"]) == FLOW
    assert graph.edge_kind(found["cond"], found["sink"]) == TRUE
    assert graph.edge_kind(found["cond"], found["reset"]) == FALSE
    assert graph.edge_kind(found["ret"], found["helper_entry"]) == FUNCTION_CALL
    assert graph.edge_kind(found["helper_exit"], found["ret"]) == FUNCTION_RETURN
    assert graph.edge_kind(found["clean"], found["src"]) is None
    assert graph.edge_kind(found["src"].id, found["clean"].id) == FLOW


@LANGUAGES
def test_reachable_follows_calls_by_default(language):
    graph = build(language)
    found = roles(graph)

    everything = graph.reachable(found["main_entry"])
    assert everything == graph.nodes
    assert found["helper_ret"] in everything
    assert found["main_entry"] in everything
    assert found["helper_entry"] in everything


@LANGUAGES
def test_reachable_without_call_edges_stays_in_the_function(language):
    graph = build(language)
    found = roles(graph)

    inside = graph.reachable(found["main_entry"], exclude=CALL_KINDS)
    assert inside == graph.function_nodes(found["main_entry"])
    assert found["helper_entry"] not in inside
    only_flow = graph.reachable(found["cond"], labels=[TRUE])
    assert named(graph, only_flow) == ["cond", "sink"]


@LANGUAGES
def test_reachable_includes_the_start(language):
    graph = build(language)
    found = roles(graph)

    assert graph.reachable(found["main_exit"]) == [found["main_exit"]]
    assert found["loop"] in graph.reachable(found["loop"])
    assert named(graph, graph.reachable(found["reset"], exclude=CALL_KINDS)) == [
        "main_exit",
        "reset",
        "zero",
        "loop",
        "acc",
        "ret",
        "out",
    ]


@LANGUAGES
def test_reachable_backward(language):
    graph = build(language)
    found = roles(graph)

    assert named(graph, graph.reachable(found["sink"], backward=True)) == [
        "main_entry",
        "src",
        "clean",
        "cond",
        "sink",
    ]
    assert named(
        graph, graph.reachable(found["helper_ret"], backward=True, exclude=CALL_KINDS)
    ) == ["helper_entry", "helper_ret"]
    through_calls = graph.reachable(found["helper_ret"], backward=True)
    assert found["main_entry"] in through_calls
    assert found["acc"] in through_calls
    assert found["ret"] in through_calls
    assert found["src"] in through_calls


@LANGUAGES
def test_can_reach(language):
    graph = build(language)
    found = roles(graph)

    assert graph.can_reach(found["src"], found["out"])
    assert graph.can_reach(found["src"], found["helper_ret"])
    assert not graph.can_reach(found["src"], found["helper_ret"], exclude=CALL_KINDS)
    assert not graph.can_reach(found["out"], found["src"])
    assert not graph.can_reach(found["sink"], found["reset"])
    assert graph.can_reach(found["acc"], found["acc"])
    assert graph.can_reach(found["reset"].id, found["out"].id)
    assert graph.can_reach(found["cond"], found["sink"], labels=[TRUE])
    assert not graph.can_reach(found["cond"], found["sink"], labels=[FALSE])


@LANGUAGES
def test_shortest_path(language):
    graph = build(language)
    path = graph.shortest_path(*pair(graph, "src", "out"))

    assert path is not None
    assert path.nodes == ids(
        graph, "src", "clean", "cond", "sink", "zero", "loop", "ret", "out"
    )
    assert path.edges == [FLOW, FLOW, TRUE, FLOW, FLOW, FALSE, FLOW]


@LANGUAGES
def test_shortest_path_prefers_the_lower_id_on_a_tie(language):
    graph = build(language)
    path = graph.shortest_path(*pair(graph, "cond", "zero"))

    assert path is not None
    assert path.nodes == ids(graph, "cond", "sink", "zero")


@LANGUAGES
def test_shortest_path_is_shorter_than_a_detour(language):
    graph = build(language)
    path = graph.shortest_path(*pair(graph, "zero", "ret"))

    assert path is not None
    assert path.nodes == ids(graph, "zero", "loop", "ret")
    assert path.edges == [FLOW, FALSE]


@LANGUAGES
def test_shortest_path_crosses_calls_by_default(language):
    graph = build(language)
    path = graph.shortest_path(*pair(graph, "ret", "helper_ret"))

    assert path is not None
    assert path.nodes == ids(graph, "ret", "helper_entry", "helper_ret")
    assert path.edges == [FUNCTION_CALL, FLOW]
    back = graph.shortest_path(*pair(graph, "helper_ret", "out"))
    assert back is not None
    assert back.nodes == ids(graph, "helper_ret", "helper_exit", "ret", "out")
    assert back.edges == [FLOW, FUNCTION_RETURN, FLOW]


@LANGUAGES
def test_shortest_path_filters(language):
    graph = build(language)
    found = roles(graph)

    assert (
        graph.shortest_path(found["ret"], found["helper_ret"], exclude=CALL_KINDS)
        is None
    )
    assert graph.shortest_path(found["src"], found["out"], labels=[FLOW]) is None
    assert graph.shortest_path(found["src"], found["sink"], labels=[FLOW]) is None
    only_true = graph.shortest_path(found["cond"], found["sink"], labels=[TRUE])
    assert only_true is not None and only_true.edges == [TRUE]
    around = graph.shortest_path(found["cond"], found["zero"], exclude=[TRUE])
    assert around is not None
    assert around.nodes == ids(graph, "cond", "reset", "zero")


@LANGUAGES
def test_shortest_path_avoid(language):
    graph = build(language)
    found = roles(graph)

    path = graph.shortest_path(found["src"], found["zero"], avoid=[found["sink"]])
    assert path is not None
    assert path.nodes == ids(graph, "src", "clean", "cond", "reset", "zero")
    assert (
        graph.shortest_path(
            found["src"], found["zero"], avoid=[found["sink"], found["reset"]]
        )
        is None
    )
    ends = graph.shortest_path(
        found["src"], found["clean"], avoid=[found["src"], found["clean"]]
    )
    assert ends is not None and ends.nodes == ids(graph, "src", "clean")
    assert graph.shortest_path(found["src"], found["zero"], avoid=[found["sink"].id])


@LANGUAGES
def test_shortest_path_none_and_trivial(language):
    graph = build(language)
    found = roles(graph)

    assert graph.shortest_path(found["out"], found["src"]) is None
    same = graph.shortest_path(found["acc"], found["acc"])
    assert same is not None and same.nodes == [found["acc"].id] and same.edges == []
    with pytest.raises(KeyError):
        graph.shortest_path(found["acc"], 999)


@LANGUAGES
def test_all_paths_through_a_diamond(language):
    graph = build(language)
    paths = graph.paths(*pair(graph, "src", "zero"))

    assert [path.nodes for path in paths] == [
        ids(graph, "src", "clean", "cond", "sink", "zero"),
        ids(graph, "src", "clean", "cond", "reset", "zero"),
    ]
    assert [path.edges for path in paths] == [
        [FLOW, FLOW, TRUE, FLOW],
        [FLOW, FLOW, FALSE, FLOW],
    ]


@LANGUAGES
def test_all_paths_in_a_loop_visit_no_node_twice(language):
    graph = build(language)

    paths = graph.paths(*pair(graph, "zero", "ret"))
    assert [path.nodes for path in paths] == [ids(graph, "zero", "loop", "ret")]
    inside = graph.paths(*pair(graph, "loop", "acc"))
    assert [path.nodes for path in inside] == [ids(graph, "loop", "acc")]
    cycle_back = graph.paths(*pair(graph, "acc", "loop"))
    assert [path.nodes for path in cycle_back] == [ids(graph, "acc", "loop")]


@LANGUAGES
def test_all_paths_across_a_call(language):
    graph = build(language)
    paths = graph.paths(*pair(graph, "main_entry", "helper_ret"))

    assert len(paths) == 2
    for path in paths:
        assert path.nodes[-3:] == ids(graph, "ret", "helper_entry", "helper_ret")
        assert path.edges[-2:] == [FUNCTION_CALL, FLOW]
    assert (
        graph.paths(*pair(graph, "main_entry", "helper_ret"), exclude=CALL_KINDS) == []
    )


@LANGUAGES
def test_all_paths_respect_max_paths(language):
    graph = build(language)
    source, target = ids(graph, "src", "zero")

    assert len(graph.paths(source, target, max_paths=2)) == 2
    one = graph.paths(source, target, max_paths=1)
    assert [path.nodes for path in one] == [
        ids(graph, "src", "clean", "cond", "sink", "zero")
    ]
    assert len(graph.paths(source, target, max_paths=3)) == 2


@LANGUAGES
def test_all_paths_respect_max_length_exactly(language):
    graph = build(language)
    source, target = ids(graph, "src", "zero")

    assert len(graph.paths(source, target, max_length=4)) == 2
    assert graph.paths(source, target, max_length=3) == []
    assert graph.paths(source, target, max_length=0) == []
    assert len(graph.paths(source, target, max_length=100)) == 2


@LANGUAGES
def test_all_paths_filters_and_avoid(language):
    graph = build(language)
    found = roles(graph)
    source, target = found["src"], found["zero"]

    assert [p.nodes for p in graph.paths(source, target, avoid=[found["sink"]])] == [
        ids(graph, "src", "clean", "cond", "reset", "zero")
    ]
    assert [p.nodes for p in graph.paths(source, target, exclude=[TRUE])] == [
        ids(graph, "src", "clean", "cond", "reset", "zero")
    ]
    assert [p.nodes for p in graph.paths(source, target, labels=[FLOW, TRUE])] == [
        ids(graph, "src", "clean", "cond", "sink", "zero")
    ]
    assert [
        p.nodes for p in graph.paths(found["cond"], target, labels=[FLOW, TRUE])
    ] == [ids(graph, "cond", "sink", "zero")]
    assert [p.nodes for p in graph.paths(found["cond"], target, exclude=[TRUE])] == [
        ids(graph, "cond", "reset", "zero")
    ]
    assert graph.paths(found["out"], found["src"]) == []
    kept = graph.paths(source, target, avoid=[source, target])
    assert len(kept) == 2


@LANGUAGES
def test_all_paths_same_node_is_the_single_node_path(language):
    graph = build(language)
    found = roles(graph)
    paths = graph.paths(found["loop"], found["loop"])

    assert len(paths) == 1
    assert paths[0].nodes == [found["loop"].id]


@LANGUAGES
def test_bounds_are_validated(language):
    graph = build(language)
    source, target = ids(graph, "src", "zero")

    with pytest.raises(ValueError):
        graph.paths(source, target, max_paths=0)
    with pytest.raises(ValueError):
        graph.paths(source, target, max_length=-1)
    assert len(graph.paths(source, target, max_length=4, max_paths=1)) == 1


def chain_of_diamonds(count: int) -> str:
    lines = ["def f(a):"]
    for index in range(count):
        lines += [
            f"    if a > {index}:",
            "        a = a + 1",
            "    else:",
            "        a = a - 1",
        ]
    lines.append("    return a")
    return "\n".join(lines) + "\n"


def test_bounds_hold_on_a_graph_with_thousands_of_paths():
    graph = CodeGraph.from_source("python", chain_of_diamonds(12))
    entry = graph.functions()[0]
    exit_node = graph.by_type("EXIT")[0]

    assert len(graph.paths(entry, exit_node)) == 100
    assert len(graph.paths(entry, exit_node, max_paths=5)) == 5
    assert len(graph.paths(entry, exit_node, max_paths=5000)) == 4096
    assert graph.paths(entry, exit_node, max_length=10) == []
    shortest = graph.shortest_path(entry, exit_node)
    assert shortest is not None
    edges = len(shortest) - 1
    assert len(graph.paths(entry, exit_node, max_paths=5000, max_length=edges)) == 4096
    assert graph.paths(entry, exit_node, max_paths=5000, max_length=edges - 1) == []


def test_unreachable_targets_do_not_wander_in_loops():
    source = "def f(a):\n    while a:\n        while a > 1:\n            a = a - 1\n    return 1\n\n\ndef g():\n    return 2\n"
    graph = CodeGraph.from_source("python", source)
    start = graph.by_type("LOOP_HEADER")[0]
    other = graph.by_text("return 2")[0]

    assert graph.paths(start, other) == []
    assert graph.shortest_path(start, other) is None
    inner = graph.by_text("a = a - 1")[0]
    assert len(graph.paths(start, inner)) == 1


def test_an_unreachable_target_is_answered_without_enumerating_paths():
    other = "\n\ndef g():\n    return 2\n"
    graph = CodeGraph.from_source("python", chain_of_diamonds(25) + other)
    entry = graph.function_nodes("f")[0]
    unreachable = graph.by_text("return 2")[0]

    assert graph.paths(entry, unreachable) == []
    assert graph.shortest_path(entry, unreachable) is None


def test_a_target_behind_an_avoided_node_is_answered_without_enumerating_paths():
    graph = CodeGraph.from_source("python", chain_of_diamonds(25))
    entry = graph.functions()[0]
    exit_node = graph.by_type("EXIT")[0]
    last = graph.by_text("return a")[0]

    assert graph.paths(entry, exit_node, avoid=[last]) == []
    assert graph.shortest_path(entry, exit_node, avoid=[last]) is None
