"""
Tests for programs with nothing to analyze: an empty file, only comments, only
declarations (a C header), or only package/import lines (Java).

C and Java build an empty CFG for these instead of raising. Python keeps an
empty `<module>` ENTRY/EXIT pair, since a module always has top-level flow.
"""

import subprocess
import sys

import pytest

from tree_climber.cfg.builder import CFGBuilder
from tree_climber.dataflow.analyses.def_use import DefUseSolver
from tree_climber.dataflow.analyses.reaching_definitions import (
    ReachingDefinitionsProblem,
)
from tree_climber.dataflow.analyses.use_def import UseDefSolver
from tree_climber.dataflow.solver import WorklistSolver
from tree_climber.viz.app import ParseRequest, parse_source_code

EMPTY_PROGRAMS = [
    ("c", ""),
    ("c", "// only a comment\n"),
    ("c", "int x;\nstruct S { int a; };\ntypedef int T;\n"),
    ("java", ""),
    ("java", "// only a comment\n"),
    ("java", "package a;\nimport b.C;\n"),
]
IDS = [
    "c-empty",
    "c-comment",
    "c-declarations",
    "java-empty",
    "java-comment",
    "java-imports",
]


def build(language: str, code: str):
    builder = CFGBuilder(language)
    builder.setup_parser()
    return builder.build_cfg(code)


@pytest.mark.parametrize("language, code", EMPTY_PROGRAMS, ids=IDS)
def test_a_program_with_nothing_to_analyze_gives_an_empty_cfg(language, code):
    cfg = build(language, code)

    assert cfg.nodes == {}
    assert cfg.entry_node_ids == []
    assert cfg.exit_node_ids == []


@pytest.mark.parametrize("language, code", EMPTY_PROGRAMS, ids=IDS)
def test_the_dataflow_solvers_accept_an_empty_cfg(language, code):
    cfg = build(language, code)

    result = WorklistSolver().solve(cfg, ReachingDefinitionsProblem())

    assert DefUseSolver().solve(cfg, result).chains == {}
    assert UseDefSolver().solve(cfg, result).chains == {}


@pytest.mark.parametrize("language, code", EMPTY_PROGRAMS, ids=IDS)
def test_the_api_returns_an_empty_graph_instead_of_an_error(language, code):
    request = ParseRequest.model_validate({"source_code": code, "language": language})

    response = parse_source_code(request)

    assert response.success, response.error
    assert response.cfg is not None
    assert response.cfg["nodes"] == {}


def test_python_keeps_an_empty_module_flow():
    cfg = build("python", "")

    assert [node.source_text for node in cfg.nodes.values()] == ["<module>", "<module>"]


@pytest.mark.parametrize(
    "language, code",
    [
        ("c", "int x;\nint f() { return x; }\n"),
        ("java", "package a;\nimport b.C;\nclass A { int f() { return 1; } }\n"),
    ],
)
def test_declarations_around_real_code_do_not_hide_it(language, code):
    assert len(build(language, code).nodes) > 0


@pytest.mark.parametrize("name", ["empty.c", "header.h", "Empty.java"])
def test_the_cli_handles_an_empty_file(tmp_path, name):
    path = tmp_path / name
    path.write_text("int x;\n" if name == "header.h" else "")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tree_climber.cli",
            str(path),
            "--draw_cfg",
            "--draw_dfg",
            "--output",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
