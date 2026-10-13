"""The Path result type: accessors, terminal form, JSON form, equality."""

import json

import pytest
from query_helpers import pair, LANGUAGES, build, ids

from tree_climber.query import CodeGraph, Path, PathStep

PYTHON_PATH = """\
[5] x = input()
  --> [6] y = clean(x)
  --> [7] y
  --true--> [9] system(y)"""

PYTHON_DATA_PATH = """\
[5] x = input()
  --def_use x--> [6] y = clean(x)
  --def_use y--> [9] system(y)"""


def test_string_form_of_a_control_path():
    graph = build("python")
    path = graph.shortest_path(*pair(graph, "src", "sink"))

    assert str(path) == PYTHON_PATH


def test_string_form_of_a_data_flow_path():
    graph = build("python")
    path = graph.data_flow_path(*pair(graph, "src", "sink"))

    assert str(path) == PYTHON_DATA_PATH


def test_string_form_names_entry_and_exit_nodes():
    graph = build("python")
    path = graph.shortest_path(*pair(graph, "main_entry", "main_exit"))

    lines = str(path).splitlines()
    assert lines[0] == "[3] ENTRY main"
    assert lines[-1].endswith("[4] EXIT main")
    assert lines[1] == "  --> [5] x = input()"


@LANGUAGES
def test_string_form_has_one_line_per_step(language):
    graph = build(language)
    path = graph.shortest_path(*pair(graph, "src", "out"))

    assert path is not None
    lines = str(path).splitlines()
    assert len(lines) == len(path) == 8
    assert lines[0].startswith("[5] ")
    assert lines[3].startswith("  --true--> [9] ")
    assert lines[6].startswith("  --false--> [15] ")


def test_string_form_of_a_call_edge():
    graph = build("python")
    path = graph.shortest_path(*pair(graph, "ret", "helper_ret"))

    assert str(path) == (
        "[15] r = helper(total)\n"
        "  --function_call--> [0] ENTRY helper\n"
        "  --> [2] return n + 1"
    )


def test_string_form_uses_the_first_line_and_shortens_long_text():
    source = "x = (\n    1 +\n    2)\ny = " + " + ".join(["longname"] * 12) + "\n"
    graph = CodeGraph.from_source("python", source)
    path = graph.shortest_path(*ids_of(graph, "x = (", "y = longname"))

    assert path is not None
    lines = str(path).splitlines()
    full = "y = " + " + ".join(["longname"] * 12)
    assert lines[1] == f"  --> [3] {full[:57]}..."
    assert path.texts[0] == "x = ("
    assert "1 +" not in str(path)
    assert len(lines[1].split("] ", 1)[1]) == 60


def ids_of(graph, first, second):
    return graph.by_text(first)[0].id, graph.by_text(second)[0].id


def test_json_form():
    graph = build("python")
    path = graph.data_flow_path(*pair(graph, "src", "sink"))

    assert path is not None
    assert path.to_dict() == {
        "steps": [
            {
                "node": 5,
                "node_type": "STATEMENT",
                "text": "x = input()",
                "edge": None,
                "variable": None,
            },
            {
                "node": 6,
                "node_type": "STATEMENT",
                "text": "y = clean(x)",
                "edge": "def_use",
                "variable": "x",
            },
            {
                "node": 9,
                "node_type": "STATEMENT",
                "text": "system(y)",
                "edge": "def_use",
                "variable": "y",
            },
        ]
    }


@LANGUAGES
def test_json_form_survives_dumps_and_loads(language):
    graph = build(language)
    for path in (
        graph.shortest_path(*pair(graph, "src", "out")),
        graph.data_flow_path(*pair(graph, "src", "out")),
    ):
        assert path is not None
        assert json.loads(json.dumps(path.to_dict())) == path.to_dict()
        rebuilt = Path(tuple(PathStep(**step) for step in path.to_dict()["steps"]))
        assert rebuilt == path


def test_step_json_form():
    step = PathStep(3, "ENTRY", "f", "true", "v")

    assert step.to_dict() == {
        "node": 3,
        "node_type": "ENTRY",
        "text": "f",
        "edge": "true",
        "variable": "v",
    }


@LANGUAGES
def test_accessors(language):
    graph = build(language)
    path = graph.shortest_path(*pair(graph, "cond", "zero"))

    assert path is not None
    assert path.nodes == ids(graph, "cond", "sink", "zero")
    assert path.edges == ["true", "flow"]
    assert len(path.texts) == 3
    assert path.source.node == path.nodes[0]
    assert path.target.node == path.nodes[-1]
    assert path.source.edge is None
    assert path.target.edge == "flow"
    assert [step.node for step in path] == path.nodes
    assert len(path) == 3


def test_paths_compare_by_value_and_hash():
    graph = build("python")
    first = graph.shortest_path(*pair(graph, "src", "sink"))
    second = graph.shortest_path(*pair(graph, "src", "sink"))
    other = graph.shortest_path(*pair(graph, "src", "zero"))

    assert first == second
    assert first is not second
    assert first != other
    assert len({first, second, other}) == 2


def test_control_and_data_paths_differ():
    graph = build("python")

    assert graph.shortest_path(*pair(graph, "src", "sink")) != graph.data_flow_path(
        *pair(graph, "src", "sink")
    )


def test_step_labels_and_arrows():
    assert PathStep(1, "STATEMENT", "x = 1").label() == "[1] x = 1"
    assert PathStep(1, "STATEMENT", "x", "flow").arrow() == "-->"
    assert PathStep(1, "STATEMENT", "x", None).arrow() == "-->"
    assert PathStep(1, "STATEMENT", "x", "false").arrow() == "--false-->"
    assert PathStep(1, "STATEMENT", "x", "flow", "v").arrow() == "--flow v-->"
    assert PathStep(1, "EXIT", "g").label() == "[1] EXIT g"


def test_paths_are_immutable():
    graph = build("python")
    path = graph.shortest_path(*pair(graph, "src", "sink"))

    assert path is not None
    with pytest.raises(AttributeError):
        setattr(path, "steps", ())
    with pytest.raises(AttributeError):
        setattr(path.steps[0], "node", 1)
    path.nodes.append(1)
    assert 1 not in path.nodes
