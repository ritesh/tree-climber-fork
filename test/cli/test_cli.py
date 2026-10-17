"""
Tests for the tree-climber command line: option spellings, --version and
--list-languages, error messages, and the image format and resolution.

Most tests drive the Typer app in-process; two run `python -m tree_climber.cli`
to cover the real entry point.
"""

import subprocess
import sys
from pathlib import Path

import pygraphviz as pgv
import pytest
import typer
import typer.main
from typer.testing import CliRunner

from tree_climber import __version__
from tree_climber.cli.__main__ import app
from tree_climber.cli.visualizers.constants import (
    DEFAULT_DPI,
    MAX_PNG_PIXELS,
    NETWORK_SIMPLEX_LIMIT,
)
from tree_climber.cli.visualizers.utils import draw_graph, png_dpi
from tree_climber.language_registry import SUPPORTED_LANGUAGES

runner = CliRunner()

C_SOURCE = "int main() { int x = 1; return x; }\n"
SAMPLES = {
    "c": ("prog.c", C_SOURCE),
    "java": ("Prog.java", "class A { int f() { return 1; } }\n"),
    "python": ("prog.py", "def f():\n    return 1\n"),
}


@pytest.fixture
def c_file(tmp_path):
    path = tmp_path / "prog.c"
    path.write_text(C_SOURCE)
    return path


@pytest.mark.parametrize("kind", ["ast", "cfg", "dfg", "cpg"])
@pytest.mark.parametrize("separator", ["-", "_"], ids=["hyphen", "underscore"])
def test_both_spellings_of_each_draw_flag_work(c_file, tmp_path, kind, separator):
    result = runner.invoke(
        app, [str(c_file), f"--draw{separator}{kind}", "--output", str(tmp_path)]
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / f"prog.c_{kind}.png").exists()


@pytest.mark.parametrize("flag", ["--draw-duc", "--draw_duc"])
def test_draw_duc_is_an_alias_for_draw_dfg(c_file, tmp_path, flag):
    result = runner.invoke(app, [str(c_file), flag, "--output", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "prog.c_dfg.png").exists()


def test_spellings_can_be_mixed_and_values_can_be_attached(c_file, tmp_path):
    result = runner.invoke(
        app, [str(c_file), "--draw-ast", "--draw_cfg", f"--output={tmp_path}"]
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "prog.c_ast.png").exists()
    assert (tmp_path / "prog.c_cfg.png").exists()


@pytest.mark.parametrize("language", list(SAMPLES))
def test_each_language_is_detected_from_its_file_extension(tmp_path, language):
    filename, source = SAMPLES[language]
    path = tmp_path / filename
    path.write_text(source)

    result = runner.invoke(app, [str(path), "--draw-cfg", "--output", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert (tmp_path / f"{filename}_cfg.png").exists()


def test_the_python_example_from_the_help_text_works(tmp_path):
    example = Path(__file__).parents[1] / "python_cfg" / "basic_constructs.py"

    result = runner.invoke(
        app,
        [str(example), "--draw-cfg", "--draw-dfg", "--output", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "basic_constructs.py_cfg.png").exists()
    assert (tmp_path / "basic_constructs.py_dfg.png").exists()


def test_python_can_be_read_from_stdin(tmp_path):
    result = runner.invoke(
        app,
        ["-", "-l", "python", "--draw-cfg", "--output", str(tmp_path)],
        input="def f(x):\n    return x\n",
    )

    assert result.exit_code == 0, result.output
    assert list(tmp_path.glob("*_cfg.png"))


def test_version_flag():
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert f"Tree Climber v{__version__}" in result.output


def test_list_languages_flag():
    result = runner.invoke(app, ["--list-languages"])

    assert result.exit_code == 0
    for language in SUPPORTED_LANGUAGES:
        assert language in result.output


def test_help_documents_the_hyphenated_spelling():
    result = runner.invoke(app, ["--help"])
    declared = {
        opt
        for param in typer.main.get_command(app).params
        for opt in (*param.opts, *param.secondary_opts)
    }

    assert result.exit_code == 0
    assert "--draw-cfg" in declared
    assert "--draw_cfg" not in declared
    assert "--version" in declared
    assert "--list-languages" in declared


def test_a_visualization_option_is_required(c_file):
    result = runner.invoke(app, [str(c_file)])

    assert result.exit_code == 1
    assert "--draw-cfg" in result.output


def test_unsupported_language_is_rejected(c_file):
    result = runner.invoke(app, [str(c_file), "--draw-cfg", "--language", "cobol"])

    assert result.exit_code == 1
    assert "Unsupported language 'cobol'" in result.output


def test_entry_point_runs_the_analysis(c_file, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tree_climber.cli",
            str(c_file),
            "--draw_cfg",
            "--output",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "prog.c_cfg.png").exists()


def test_entry_point_reports_the_version():
    result = subprocess.run(
        [sys.executable, "-m", "tree_climber.cli", "--version"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert f"Tree Climber v{__version__}" in result.stdout


@pytest.fixture
def launched(monkeypatch):
    calls = []

    def fake_launch(target, *args, **kwargs):
        calls.append(target)
        return 0

    monkeypatch.setattr("tree_climber.cli.commands.typer.launch", fake_launch)
    return calls


def test_show_is_off_by_default(c_file, tmp_path, launched):
    result = runner.invoke(app, [str(c_file), "--draw-cfg", "-o", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert launched == []


def test_show_opens_every_saved_image(c_file, tmp_path, launched):
    result = runner.invoke(
        app,
        [str(c_file), "--draw-ast", "--draw-cfg", "--draw-dfg", "--draw-cpg", "--show"]
        + ["-o", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    assert launched == [
        str(tmp_path / f"prog.c_{kind}.png") for kind in ("ast", "cfg", "dfg", "cpg")
    ]


def test_a_viewer_that_fails_to_launch_only_warns(c_file, tmp_path, monkeypatch):
    monkeypatch.setattr("tree_climber.cli.commands.typer.launch", lambda *a, **k: 127)

    result = runner.invoke(
        app, [str(c_file), "--draw-cfg", "--show", "-o", str(tmp_path)]
    )

    assert result.exit_code == 0, result.output
    assert "could not open" in result.output
    assert (tmp_path / "prog.c_cfg.png").exists()


MAGIC = {"png": b"\x89PNG", "svg": b"<?xml", "pdf": b"%PDF"}


@pytest.mark.parametrize("image_format", ["svg", "pdf"])
def test_format_sets_the_image_type_and_extension(c_file, tmp_path, image_format):
    result = runner.invoke(
        app,
        [str(c_file), "--draw-ast", "--draw-cfg", "--draw-dfg", "--draw-cpg"]
        + ["--format", image_format, "-o", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    for kind in ("ast", "cfg", "dfg", "cpg"):
        path = tmp_path / f"prog.c_{kind}.{image_format}"
        assert path.read_bytes().startswith(MAGIC[image_format]), path
    assert not list(tmp_path.glob("*.png"))


def test_an_unknown_format_is_rejected(c_file, tmp_path):
    result = runner.invoke(
        app, [str(c_file), "--draw-cfg", "--format", "gif", "-o", str(tmp_path)]
    )

    assert result.exit_code == 2
    assert "gif" in result.output
    assert list(tmp_path.iterdir()) == [c_file]


def graph_of_size(width_inches: float, height_inches: float) -> pgv.AGraph:
    graph = pgv.AGraph()
    graph.graph_attr["bb"] = f"0,0,{width_inches * 72},{height_inches * 72}"
    return graph


def test_a_small_png_is_drawn_at_full_resolution():
    assert png_dpi(graph_of_size(10, 20)) == DEFAULT_DPI


def test_a_large_png_is_drawn_under_the_pixel_cap():
    dpi = png_dpi(graph_of_size(1000, 100))

    assert dpi == 15
    assert (1000 * dpi) * (100 * dpi) <= MAX_PNG_PIXELS < (1000 * 16) * (100 * 16)


def test_a_png_exactly_at_the_cap_keeps_full_resolution():
    side = MAX_PNG_PIXELS**0.5 / DEFAULT_DPI

    assert png_dpi(graph_of_size(side, side)) == DEFAULT_DPI


def test_a_png_just_over_the_cap_is_scaled_down():
    side = (MAX_PNG_PIXELS**0.5 + 1) / DEFAULT_DPI

    assert png_dpi(graph_of_size(side, side)) == DEFAULT_DPI - 1


@pytest.mark.parametrize("image_format", ["png", "svg"])
def test_draw_graph_limits_the_layout_and_sets_dpi_for_png(tmp_path, image_format):
    graph = pgv.AGraph(directed=True)
    graph.add_edge("a", "b")
    path = tmp_path / f"graph.{image_format}"

    draw_graph(graph, path)

    assert path.read_bytes().startswith(MAGIC[image_format])
    assert graph.graph_attr["nslimit"] == NETWORK_SIMPLEX_LIMIT
    expected = str(DEFAULT_DPI) if image_format == "png" else ""
    assert (graph.graph_attr.get("dpi") or "") == expected


def test_a_large_drawing_is_saved_under_the_pixel_cap(tmp_path):
    graph = pgv.AGraph()
    graph.add_node("big", shape="box", width="60", height="60", fixedsize="true")
    path = tmp_path / "graph.png"

    draw_graph(graph, path)

    header = path.read_bytes()[:24]
    width, height = int.from_bytes(header[16:20]), int.from_bytes(header[20:24])
    assert width * height <= MAX_PNG_PIXELS
    assert int(graph.graph_attr["dpi"]) == png_dpi(graph) < DEFAULT_DPI
