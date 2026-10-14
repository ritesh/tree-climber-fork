"""Control dependence in the query API: dependences, dependents, and slices."""

from query_helpers import LANGUAGES, build, named, roles

from tree_climber.query import CodeGraph


@LANGUAGES
def test_control_dependences(language):
    graph = build(language)
    found = roles(graph)

    def deps(role):
        return [
            (named(graph, [b])[0], label)
            for b, label in graph.control_dependences(found[role])
        ]

    assert deps("sink") == [("cond", "true")]
    assert deps("reset") == [("cond", "false")]
    assert deps("acc") == [("loop", "true")]
    assert deps("loop") == [("loop", "true")]
    assert deps("ret") == []
    assert deps("src") == []


@LANGUAGES
def test_control_dependents(language):
    graph = build(language)
    found = roles(graph)

    assert named(graph, graph.control_dependents(found["cond"])) == ["sink", "reset"]
    assert named(graph, graph.control_dependents(found["loop"])) == ["loop", "acc"]
    assert graph.control_dependents(found["src"]) == []
    assert graph.control_dependents(found["cond"].id) == graph.control_dependents(
        found["cond"]
    )


@LANGUAGES
def test_backward_slice_with_control(language):
    graph = build(language)
    found = roles(graph)

    without = named(graph, graph.backward_slice(found["sink"]))
    with_control = named(graph, graph.backward_slice(found["sink"], control=True))
    assert "cond" not in without
    assert set(with_control) == set(without) | {"cond"}


@LANGUAGES
def test_forward_slice_with_control(language):
    graph = build(language)
    found = roles(graph)

    without = named(graph, graph.forward_slice(found["src"]))
    with_control = named(graph, graph.forward_slice(found["src"], control=True))
    assert "reset" not in without
    assert set(with_control) == set(without) | {"reset"}


def test_control_brings_in_the_data_of_the_condition():
    source = (
        "def f():\n"
        "    flag = check()\n"
        "    other = 1\n"
        "    if flag:\n"
        "        y = 1\n"
        "    else:\n"
        "        y = 2\n"
        "    return y\n"
    )
    graph = CodeGraph.from_source("python", source)
    ret = graph.by_text("return y")[0]

    assert [n.source_text for n in graph.backward_slice(ret)] == [
        "y = 1",
        "y = 2",
        "return y",
    ]
    assert [n.source_text for n in graph.backward_slice(ret, control=True)] == [
        "flag = check()",
        "flag",
        "y = 1",
        "y = 2",
        "return y",
    ]
    flag = graph.by_text("flag = check()")[0]
    assert [n.source_text for n in graph.forward_slice(flag)] == [
        "flag = check()",
        "flag",
    ]
    assert [n.source_text for n in graph.forward_slice(flag, control=True)] == [
        "flag = check()",
        "flag",
        "y = 1",
        "y = 2",
        "return y",
    ]


def test_control_is_transitive_through_nested_branches():
    source = "def f(a, b):\n    if a:\n        if b:\n            y = 1\n            return y\n    return 0\n"
    graph = CodeGraph.from_source("python", source)
    inner = graph.by_text("y = 1")[0]

    assert [n.source_text for n in graph.backward_slice(inner, control=True)] == [
        "f",
        "a",
        "b",
        "y = 1",
    ]


def test_the_data_of_a_condition_brings_in_its_own_conditions():
    source = (
        "def f(a):\n"
        "    if a:\n"
        "        flag = 1\n"
        "    else:\n"
        "        flag = 2\n"
        "    if flag:\n"
        "        y = 1\n"
        "    return 0\n"
    )
    graph = CodeGraph.from_source("python", source)
    inner = graph.by_text("y = 1")[0]

    assert [n.source_text for n in graph.backward_slice(inner, control=True)] == [
        "f",
        "a",
        "flag = 1",
        "flag = 2",
        "flag",
        "y = 1",
    ]
