"""
Tests for `tree-climber taint` and `tree-climber query`, including the examples
in the "Tracing user input" section of docs/python-guide.md, and for the path
highlight drawn on the CFG and DFG images.
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pygraphviz as pgv
import pytest
import typer.main
from typer.testing import CliRunner

from tree_climber.cfg.builder import CFGBuilder
from tree_climber.cli.__main__ import app
from tree_climber.cli.commands import _analyze_dataflow
from tree_climber.cli.options import AnalysisOptions
from tree_climber.cli.source import StdinSource
from tree_climber.cli.visualizers import CFGVisualizer, DFGVisualizer
from tree_climber.cli.visualizers.constants import PATH_EDGE_COLOR, PATH_NODE_COLOR
from tree_climber.cli.visualizers.utils import highlight_path
from tree_climber.query import Path as Path_
from tree_climber.query import PathStep
from tree_climber.taint import analyze, builtin_rules
from tree_climber.viz.app import TaintRequest, taint_source_code

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"})

APP = """\
import os
import shlex
from flask import request


def ping():
    host = request.args.get("host")
    run("ping -c 1 " + host)
    run("ping -c 1 " + shlex.quote(host))


def run(command):
    os.system(command)


def search(cursor):
    term = request.args["q"]
    cursor.execute("SELECT * FROM t WHERE name = ?", (term,))
    cursor.execute("SELECT * FROM t WHERE name = '" + term + "'")
"""

TAINT_OUTPUT = """\
Analyzing: app.py
1. python-command-injection: argument 0 of os.system (line 13)
   line 7    [7] host = request.args.get("host")
   line 8      --def_use host--> [8] run("ping -c 1 " + host)
   line 12     --argument command--> [10] ENTRY run
   line 13     --def_use command--> [12] os.system(command)
2. python-sql-injection: argument 0 of cursor.execute (line 19)
   line 17   [15] term = request.args["q"]
   line 19     --def_use term--> [17] cursor.execute("SELECT * FROM t WHERE name = '" + term + ...
2 findings
"""

EVAL_RULES = {
    "rules": [
        {
            "id": "eval",
            "languages": ["python"],
            "sources": [{"call": "input"}],
            "sinks": [{"call": "eval", "arguments": [0]}],
        }
    ]
}


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "app.py").write_text(APP)
    return tmp_path


def invoke(*args, **kwargs):
    return runner.invoke(app, list(args), **kwargs)


class TestTaint:
    def test_the_guide_example(self, in_tmp):
        result = invoke("taint", "app.py")

        assert result.exit_code == 0, result.output
        assert result.output == TAINT_OUTPUT

    def test_rules_builtin_is_the_default(self, in_tmp):
        assert invoke("taint", "app.py", "--rules", "builtin").output == TAINT_OUTPUT

    def test_json(self, in_tmp):
        result = invoke("taint", "app.py", "--json")

        assert result.exit_code == 0, result.output
        findings = json.loads(result.output)["findings"]
        assert [f["rule"] for f in findings] == [
            "python-command-injection",
            "python-sql-injection",
        ]
        assert findings[0]["path"]["steps"][1] == {
            "node": 8,
            "node_type": "STATEMENT",
            "text": 'run("ping -c 1 " + host)',
            "edge": "def_use",
            "variable": "host",
        }
        source = CFGBuilder("python")
        source.setup_parser()
        expected = analyze(source.build_cfg(APP), builtin_rules("python"), "python")
        assert findings == [finding.to_dict() for finding in expected]

    def test_one_finding(self, in_tmp):
        result = invoke("taint", "app.py", "--finding", "2")

        assert result.exit_code == 0, result.output
        assert "2. python-sql-injection" in result.output
        assert "python-command-injection" not in result.output
        assert result.output.endswith("2 findings\n")

    def test_one_finding_as_json(self, in_tmp):
        result = invoke("taint", "app.py", "--finding", "2", "--json")

        assert [f["rule"] for f in json.loads(result.output)["findings"]] == [
            "python-sql-injection"
        ]

    @pytest.mark.parametrize("number", ["3", "0"])
    def test_a_finding_that_does_not_exist(self, in_tmp, number):
        result = invoke("taint", "app.py", "--finding", number)

        assert result.exit_code != 0
        if number == "3":
            assert "No finding 3: 2 findings in app.py" in result.output

    def test_no_findings(self, in_tmp):
        (in_tmp / "safe.py").write_text("x = 1\nprint(x)\n")

        result = invoke("taint", "safe.py")

        assert result.exit_code == 0, result.output
        assert result.output == "Analyzing: safe.py\nNo findings\n"

    def test_one_finding_is_singular(self, in_tmp):
        (in_tmp / "one.py").write_text("import os\nos.system(input())\n")

        assert invoke("taint", "one.py").output.endswith("\n1 finding\n")

    def test_json_rules(self, in_tmp):
        (in_tmp / "rules.json").write_text(json.dumps(EVAL_RULES))
        (in_tmp / "calc.py").write_text("x = input()\neval(x)\nos.system(x)\n")

        result = invoke("taint", "calc.py", "--rules", "rules.json")

        assert result.exit_code == 0, result.output
        assert "1. eval: argument 0 of eval (line 2)" in result.output
        assert "os.system" not in result.output

    @pytest.mark.parametrize("name", ["rules.yaml", "rules.YML"])
    def test_yaml_rules_are_refused(self, in_tmp, name):
        (in_tmp / name).write_text("rules: []\n")

        result = invoke("taint", "app.py", "--rules", name)

        assert result.exit_code == 1
        assert "YAML rule files are not supported" in result.output
        assert "JSON" in result.output

    def test_missing_rules_file(self, in_tmp):
        result = invoke("taint", "app.py", "--rules", "nope.json")

        assert result.exit_code == 1
        assert "Cannot read rules from nope.json" in result.output

    def test_malformed_json(self, in_tmp):
        (in_tmp / "rules.json").write_text("{")

        result = invoke("taint", "app.py", "--rules", "rules.json")

        assert result.exit_code == 1
        assert "Invalid JSON in rules.json" in result.output

    @pytest.mark.parametrize(
        "rules, message",
        [
            ({"rules": [{"sinks": []}]}, "missing key 'id'"),
            ({"rules": [{"id": "a", "colour": 1}]}, "Unknown rule keys"),
            ([1], "Invalid rules in rules.json"),
            ({"rules": [{"id": "a", "sources": [{}]}]}, "exactly one of"),
        ],
    )
    def test_invalid_rules(self, in_tmp, rules, message):
        (in_tmp / "rules.json").write_text(json.dumps(rules))

        result = invoke("taint", "app.py", "--rules", "rules.json")

        assert result.exit_code == 1
        assert message in result.output

    def test_rules_for_another_language_only(self, in_tmp):
        (in_tmp / "rules.json").write_text(json.dumps(EVAL_RULES))
        (in_tmp / "prog.c").write_text("int main() { return 0; }\n")

        result = invoke("taint", "prog.c", "--rules", "rules.json")

        assert result.exit_code == 1
        assert "No rules for c in rules.json" in result.output

    @pytest.mark.parametrize(
        "filename, source, rule",
        [
            (
                "prog.c",
                "int main(int argc, char **argv) { system(argv[1]); return 0; }\n",
                "c-command-injection",
            ),
            (
                "A.java",
                "class A { void f(HttpServletRequest r) throws Exception {\n"
                '  Runtime.getRuntime().exec(r.getParameter("c")); } }\n',
                "java-command-injection",
            ),
        ],
    )
    def test_c_and_java(self, in_tmp, filename, source, rule):
        (in_tmp / filename).write_text(source)

        result = invoke("taint", filename)

        assert result.exit_code == 0, result.output
        assert f"1. {rule}" in result.output

    def test_stdin(self, in_tmp):
        result = invoke(
            "taint", "-", "-l", "python", input="import os\nos.system(input())\n"
        )

        assert result.exit_code == 0, result.output
        assert result.output.startswith("Analyzing: stdin\n1. python-command")

    def test_empty_stdin_is_an_error(self, in_tmp):
        result = invoke("taint", "-", "-l", "python", input="  \n")

        assert result.exit_code == 1
        assert "Stdin is empty" in result.output

    def test_stdin_from_a_terminal_is_an_error(self, in_tmp, monkeypatch):
        monkeypatch.setattr(
            "tree_climber.cli.__main__.is_stdin_available", lambda: False
        )
        result = invoke("query", "-", "-l", "c", "--calls", "puts")

        assert result.exit_code == 1
        assert "no stdin input detected" in result.output

    def test_stdin_needs_a_language(self, in_tmp):
        result = invoke("taint", "-", input="x = 1\n")

        assert result.exit_code == 1
        assert "Language must be specified" in result.output

    def test_unknown_language(self, in_tmp):
        result = invoke("taint", "app.py", "-l", "cobol")

        assert result.exit_code == 1
        assert "Unsupported language 'cobol'" in result.output

    def test_the_language_option_overrides_the_extension(self, in_tmp):
        (in_tmp / "app.txt").write_text(APP)

        result = invoke("taint", "app.txt", "-l", "python")

        assert result.exit_code == 0, result.output
        assert result.output.endswith("2 findings\n")

    def test_undetected_language(self, in_tmp):
        (in_tmp / "notes.txt").write_text("hello\n")

        result = invoke("taint", "notes.txt")

        assert result.exit_code == 1
        assert "Could not auto-detect language" in result.output

    def test_missing_file(self, in_tmp):
        result = invoke("taint", "gone.py")

        assert result.exit_code == 1
        assert "Not a file: gone.py" in result.output

    def test_draw_every_finding(self, in_tmp):
        result = invoke("taint", "app.py", "--draw-cfg", "--draw-dfg", "-o", "out")

        assert result.exit_code == 0, result.output
        assert sorted(p.name for p in (in_tmp / "out").iterdir()) == [
            "app.py_finding1_cfg.png",
            "app.py_finding1_dfg.png",
            "app.py_finding2_cfg.png",
            "app.py_finding2_dfg.png",
        ]
        assert "Saved finding 2 on the DFG" in result.output

    def test_drawing_reuses_the_data_flow_of_the_analysis(self, in_tmp, monkeypatch):
        monkeypatch.setattr(
            "tree_climber.cli.commands._analyze_dataflow",
            lambda cfg: pytest.fail("the data flow was solved again"),
        )

        result = invoke("taint", "app.py", "--finding", "1", "--draw-dfg")

        assert result.exit_code == 0, result.output

    def test_draw_in_another_format(self, in_tmp):
        result = invoke(
            "taint", "app.py", "--finding", "1", "--draw-cfg", "--format", "svg"
        )

        assert result.exit_code == 0, result.output
        drawn = in_tmp / "app.py_finding1_cfg.svg"
        assert drawn.read_text().startswith("<?xml")
        assert not list(in_tmp.glob("*.png"))

    def test_draw_one_finding_next_to_the_file(self, in_tmp):
        result = invoke("taint", "app.py", "--finding", "2", "--draw-dfg")

        assert result.exit_code == 0, result.output
        assert sorted(p.name for p in in_tmp.glob("*.png")) == [
            "app.py_finding2_dfg.png"
        ]

    def test_drawing_keeps_json_output_parseable(self, in_tmp):
        result = runner.invoke(
            app, ["taint", "app.py", "--json", "--draw-cfg", "-o", "out"]
        )

        assert result.exit_code == 0, result.output
        assert len(json.loads(result.stdout)["findings"]) == 2

    def test_show_opens_the_images(self, in_tmp, monkeypatch):
        launched = []
        monkeypatch.setattr(
            "tree_climber.cli.commands.typer.launch",
            lambda target, *a, **k: launched.append(target) or 0,
        )

        result = invoke("taint", "app.py", "-f", "1", "--draw-cfg", "--show")

        assert result.exit_code == 0, result.output
        assert launched == ["app.py_finding1_cfg.png"]

    def test_show_without_drawing_opens_nothing(self, in_tmp, monkeypatch):
        launched = []
        monkeypatch.setattr(
            "tree_climber.cli.commands.typer.launch",
            lambda target, *a, **k: launched.append(target) or 0,
        )

        assert invoke("taint", "app.py", "--show").exit_code == 0
        assert launched == []

    def test_help(self):
        result = invoke("taint", "--help")

        assert result.exit_code == 0
        assert "--rules" in result.output
        assert "--draw-cfg" in result.output


class TestHighlight:
    @pytest.fixture(scope="class")
    def drawn(self):
        builder = CFGBuilder("python")
        builder.setup_parser()
        cfg = builder.build_cfg(APP)
        finding = analyze(cfg, builtin_rules("python"), "python")[0]
        options = AnalysisOptions(
            draw_ast=False,
            draw_cfg=True,
            draw_dfg=True,
            draw_cpg=False,
            language="python",
            layout="subtree",
            output_dir=None,  # type: ignore[arg-type]
            show=False,
            verbose=False,
            quiet=True,
            timing=False,
        )
        source = StdinSource(APP)
        graphs = {
            "cfg": CFGVisualizer(source, options, None, cfg, _analyze_dataflow(cfg)),
            "dfg": DFGVisualizer(source, options, None, cfg, _analyze_dataflow(cfg)),
        }
        return finding, {kind: v.graph() for kind, v in graphs.items()}

    def test_the_drawn_images_have_the_path(self, in_tmp, monkeypatch):
        images = []
        monkeypatch.setattr(
            "pygraphviz.AGraph.draw", lambda graph, *a, **k: images.append(graph)
        )

        result = invoke("taint", "app.py", "-f", "1", "--draw-cfg", "--draw-dfg")

        assert result.exit_code == 0, result.output
        assert len(images) == 2
        for graph in images:
            labels = [edge.attr["label"] for edge in graph.edges()]
            assert "1: def_use host" in labels
            assert graph.get_node(12).attr["fillcolor"] == PATH_NODE_COLOR

    def test_a_step_without_an_edge_kind_is_flow(self):
        graph: Any = pgv.AGraph(strict=False, directed=True)
        builder = CFGBuilder("python")
        builder.setup_parser()
        cfg = builder.build_cfg("x = 1\nprint(x)\n")
        first, second = sorted(cfg.nodes)[2:4]
        path = Path_((PathStep.of(cfg.nodes[first]), PathStep.of(cfg.nodes[second])))

        highlight_path(graph, cfg, path)

        assert [edge.attr["label"] for edge in graph.edges()] == ["1: flow"]

    @pytest.mark.parametrize("kind", ["cfg", "dfg"])
    def test_path_nodes_and_steps(self, drawn, kind):
        finding, graphs = drawn
        graph = graphs[kind]
        cfg = CFGBuilder("python")
        cfg.setup_parser()
        before = len(graph.edges())

        highlight_path(graph, cfg.build_cfg(APP), finding.path)

        assert finding.path.nodes == [7, 8, 10, 12]
        for node_id in finding.path.nodes:
            node = graph.get_node(node_id)
            assert node.attr["fillcolor"] == PATH_NODE_COLOR
            assert node.attr["color"] == PATH_EDGE_COLOR
            assert node.attr["penwidth"] == "3"
        assert graph.get_node(10).attr["label"] == "run"
        assert graph.get_node(9).attr["fillcolor"] != PATH_NODE_COLOR
        steps = [
            (int(edge[0]), int(edge[1]), edge.attr["label"])
            for edge in graph.edges()
            if edge.attr["color"] == PATH_EDGE_COLOR
        ]
        assert steps == [
            (7, 8, "1: def_use host"),
            (8, 10, "2: argument command"),
            (10, 12, "3: def_use command"),
        ]
        assert len(graph.edges()) == before + 3


QUERY_CALLS = """\
Calls to system: 1 node
   line 13   [12] os.system(command)  (in run)
"""

QUERY_SLICE = """\
Forward slice from line 7: 5 nodes
   line 7    [7] host = request.args.get("host")  (in ping)
   line 8    [8] run("ping -c 1 " + host)  (in ping)
   line 9    [9] run("ping -c 1 " + shlex.quote(host))  (in ping)
   line 12   [10] ENTRY run  (in run)
   line 13   [12] os.system(command)  (in run)
"""

QUERY_BACKWARD = """\
Backward slice from line 13: 2 nodes
   line 12   [10] ENTRY run  (in run)
   line 13   [12] os.system(command)  (in run)
"""


class TestQuery:
    def test_calls_from_the_guide(self, in_tmp):
        result = invoke("query", "app.py", "--calls", "system")

        assert result.exit_code == 0, result.output
        assert result.output == QUERY_CALLS

    def test_several_names(self, in_tmp):
        result = invoke("query", "app.py", "--calls", "run", "--calls", "execute")

        assert result.output.startswith("Calls to run, execute: 4 nodes\n")

    def test_no_callers(self, in_tmp):
        result = invoke("query", "app.py", "--calls", "nothing")

        assert result.exit_code == 0
        assert result.output == "Calls to nothing: no nodes\n"

    def test_forward_slice_from_the_guide(self, in_tmp):
        result = invoke("query", "app.py", "--slice-from", "7")

        assert result.exit_code == 0, result.output
        assert result.output == QUERY_SLICE

    def test_backward_slice_within_functions(self, in_tmp):
        result = invoke(
            "query", "app.py", "--slice-from", "13", "--backward", "--no-across-calls"
        )

        assert result.output == QUERY_BACKWARD

    def test_backward_slice_across_calls(self, in_tmp):
        result = invoke("query", "app.py", "--slice-from", "13", "--backward")

        assert result.output.startswith("Backward slice from line 13: 8 nodes\n")
        assert '[7] host = request.args.get("host")' in result.output

    def test_forward_slice_within_functions(self, in_tmp):
        result = invoke("query", "app.py", "--slice-from", "7", "--no-across-calls")

        assert result.output.startswith("Forward slice from line 7: 3 nodes\n")
        assert "os.system" not in result.output

    def test_variable(self, in_tmp):
        (in_tmp / "two.py").write_text("a, b = f()\nprint(a)\nprint(b)\n")

        result = invoke("query", "two.py", "--slice-from", "1", "--variable", "b")

        assert result.output.startswith("Forward slice from line 1 (b): 2 nodes\n")
        assert "print(b)" in result.output
        assert "print(a)" not in result.output

    def test_a_line_inside_a_statement(self, in_tmp):
        (in_tmp / "long.py").write_text("x = f(\n    1,\n)\nprint(x)\n")

        middle = invoke("query", "long.py", "--slice-from", "2")
        last = invoke("query", "long.py", "--slice-from", "3")

        assert middle.exit_code == 0, middle.output
        assert middle.output.startswith("Forward slice from line 2: 2 nodes\n")
        assert last.output.startswith("Forward slice from line 3: 2 nodes\n")

    def test_a_multiline_node_shows_its_first_line(self, in_tmp):
        (in_tmp / "long.py").write_text("x = f(\n    1,\n)\nprint(x)\n")

        result = invoke("query", "long.py", "--slice-from", "1", "--json")

        assert [node["text"] for node in json.loads(result.output)["nodes"]] == [
            "x = f(",
            "print(x)",
        ]

    def test_a_line_with_no_statement(self, in_tmp):
        result = invoke("query", "app.py", "--slice-from", "5")

        assert result.exit_code == 1
        assert "No statement on line 5" in result.output

    def test_json(self, in_tmp):
        result = invoke("query", "app.py", "--calls", "system", "--json")

        assert json.loads(result.output) == {
            "nodes": [
                {
                    "node": 12,
                    "node_type": "STATEMENT",
                    "text": "os.system(command)",
                    "line": 13,
                    "function": "run",
                }
            ]
        }

    @pytest.mark.parametrize(
        "args",
        [[], ["--calls", "f", "--slice-from", "1"]],
        ids=["neither", "both"],
    )
    def test_exactly_one_question(self, in_tmp, args):
        result = invoke("query", "app.py", *args)

        assert result.exit_code == 1
        assert "exactly one of --calls and --slice-from" in result.output

    def test_stdin(self, in_tmp):
        result = invoke(
            "query",
            "-",
            "-l",
            "c",
            "--calls",
            "puts",
            input='int main() { puts("x"); }\n',
        )

        assert result.exit_code == 0, result.output
        assert "(in main)" in result.output


GUIDE = Path(__file__).parents[2] / "docs" / "python-guide.md"


class TestGuide:
    @pytest.fixture(scope="class")
    def section(self):
        text = GUIDE.read_text()
        start = text.index("### Tracing user input")
        return text[start : text.index("\n## 4. HTTP API", start)]

    def blocks(self, section, language):
        fenced = re.findall(r"^```(\w*)\n(.*?)^```$", section, re.S | re.M)
        return [body for tag, body in fenced if tag == language]

    def test_the_program_is_the_one_of_the_taint_section(self):
        text = GUIDE.read_text()
        program = re.search(r"APP = '''\n(.*?)'''", text, re.S)

        assert program is not None
        assert program.group(1) == APP

    def test_the_outputs(self, section):
        assert self.blocks(section, "") == [
            TAINT_OUTPUT,
            QUERY_CALLS,
            QUERY_SLICE + QUERY_BACKWARD,
        ]

    def test_the_commands(self, section, in_tmp):
        commands = [
            line.split()[3:]
            for block in self.blocks(section, "bash")
            for line in block.splitlines()
            if line.startswith("uv run tree-climber")
        ]
        outputs = [invoke(*args) for args in commands]

        assert [result.exit_code for result in outputs] == [0] * len(commands)
        assert [result.output for result in outputs] == [
            TAINT_OUTPUT,
            QUERY_CALLS,
            QUERY_SLICE,
            QUERY_BACKWARD,
        ]

    def test_the_api_response(self, section):
        request = re.search(r"-d '(\{.*?\})'", section)
        assert request is not None
        body = json.loads(request.group(1).replace("\n", "\\n"))

        response = taint_source_code(TaintRequest.model_validate(body)).model_dump()

        assert [json.loads(block) for block in self.blocks(section, "json")] == [
            response
        ]


class TestDispatch:
    def test_drawing_still_takes_a_file_first(self, in_tmp):
        result = invoke("app.py", "--draw-cfg", "-o", "out")

        assert result.exit_code == 0, result.output
        assert (in_tmp / "out" / "app.py_cfg.png").exists()

    def test_a_file_named_like_a_command_with_a_path(self, in_tmp):
        (in_tmp / "taint").write_text(APP)

        result = invoke("./taint", "-l", "python", "--draw-cfg", "-o", "out")

        assert result.exit_code == 0, result.output
        assert (in_tmp / "out" / "taint_cfg.png").exists()

    def test_the_root_command_keeps_its_options(self):
        params = typer.main.get_command(app).params

        assert "--draw-cfg" in {opt for param in params for opt in param.opts}

    def test_root_help_mentions_the_commands(self):
        result = invoke("--help")

        assert "tree-climber taint app.py" in result.output
        assert "tree-climber query app.py --calls system" in result.output

    def test_entry_point(self, in_tmp):
        result = subprocess.run(
            [sys.executable, "-m", "tree_climber.cli", "query", "app.py"]
            + ["--calls", "system"],
            capture_output=True,
            text=True,
            cwd=in_tmp,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout == QUERY_CALLS

    def test_entry_point_help_names_the_command(self):
        result = subprocess.run(
            [sys.executable, "-m", "tree_climber.cli", "taint", "--help"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert "taint [OPTIONS] FILENAME" in result.stdout
