"""
Tests for the tree-climber command line: option spellings, --version and
--list-languages, and error messages.

Most tests drive the Typer app in-process; two run `python -m tree_climber.cli`
to cover the real entry point.
"""

import subprocess
import sys
from pathlib import Path

import pytest
import typer
import typer.main
from typer.testing import CliRunner

from tree_climber import __version__
from tree_climber.cli.__main__ import app
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
