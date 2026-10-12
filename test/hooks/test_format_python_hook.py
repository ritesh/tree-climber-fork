"""
Tests for the Claude Code PostToolUse formatting hook (.claude/hooks/format_python.py).

The hook must format only the Python file that was edited, with the project's
pinned ruff (`uv run ruff`), and never fail a tool call.
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
HOOK = ROOT / ".claude" / "hooks" / "format_python.py"
SETTINGS = ROOT / ".claude" / "settings.json"


def run_hook(payload, env=None):
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
    )


def edit_payload(path: Path):
    return {"tool_name": "Edit", "tool_input": {"file_path": str(path)}}


@pytest.fixture
def recording_uv(tmp_path):
    """A stand-in `uv` that records its arguments instead of running anything."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "uv_calls.txt"
    uv = bin_dir / "uv"
    uv.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n')
    uv.chmod(uv.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    return env, log


class TestFormatting:
    def test_formats_the_edited_python_file_only(self, tmp_path):
        edited = tmp_path / "edited.py"
        sibling = tmp_path / "sibling.py"
        edited.write_text("x   =  1\n")
        sibling.write_text("y   =  2\n")

        result = run_hook(edit_payload(edited))

        assert result.returncode == 0, result.stderr
        assert edited.read_text() == "x = 1\n"
        assert sibling.read_text() == "y   =  2\n"

    def test_leaves_markdown_code_blocks_alone(self, tmp_path):
        notes = tmp_path / "notes.md"
        original = "# Notes\n\n```python\nz   =  3\n```\n"
        notes.write_text(original)

        result = run_hook(edit_payload(notes))

        assert result.returncode == 0
        assert notes.read_text() == original


class TestWhichRuffRuns:
    def test_uses_the_projects_pinned_ruff_through_uv(self, tmp_path, recording_uv):
        env, log = recording_uv
        path = tmp_path / "module.py"
        path.write_text("x = 1\n")

        run_hook(edit_payload(path), env=env)

        assert log.read_text().split() == [
            "run",
            "--quiet",
            "ruff",
            "format",
            str(path),
        ]

    @pytest.mark.parametrize(
        "name", ["README.md", "settings.json", "data.toml", "script"]
    )
    def test_ignores_files_that_are_not_python(self, tmp_path, recording_uv, name):
        env, log = recording_uv

        result = run_hook(edit_payload(tmp_path / name), env=env)

        assert result.returncode == 0
        assert not log.exists()


class TestNeverFailsAToolCall:
    @pytest.mark.parametrize(
        "payload",
        [
            "not json",
            "",
            "[]",
            "{}",
            {"tool_input": {}},
            {"tool_input": {"file_path": 3}},
        ],
        ids=["garbage", "empty", "list", "empty-object", "no-path", "non-string-path"],
    )
    def test_unexpected_input_is_ignored(self, recording_uv, payload):
        env, log = recording_uv

        result = run_hook(payload, env=env)

        assert result.returncode == 0
        assert not log.exists()

    def test_a_file_ruff_cannot_format_does_not_fail_the_hook(self, tmp_path):
        broken = tmp_path / "broken.py"
        broken.write_text("def (:\n")

        assert run_hook(edit_payload(broken)).returncode == 0


class TestSettings:
    def hook_commands(self):
        settings = json.loads(SETTINGS.read_text())
        return [
            hook["command"]
            for entry in settings["hooks"]["PostToolUse"]
            for hook in entry["hooks"]
        ]

    def test_the_formatting_hook_is_configured_for_file_edits(self):
        settings = json.loads(SETTINGS.read_text())
        entry = settings["hooks"]["PostToolUse"][0]

        assert set(entry["matcher"].split("|")) == {"Edit", "MultiEdit", "Write"}
        assert any("format_python.py" in command for command in self.hook_commands())

    @pytest.mark.parametrize("project_dir_is_set", [True, False])
    def test_the_configured_command_finds_the_script(
        self, tmp_path, project_dir_is_set
    ):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        if project_dir_is_set:
            env["CLAUDE_PROJECT_DIR"] = str(ROOT)
        payload = json.dumps({"tool_input": {"file_path": str(tmp_path / "notes.txt")}})

        for command in self.hook_commands():
            result = subprocess.run(
                command,
                shell=True,
                input=payload,
                capture_output=True,
                text=True,
                cwd=ROOT,
                env=env,
            )

            assert result.returncode == 0, result.stderr

    def test_no_hook_runs_a_bare_whole_tree_ruff_format(self):
        for command in self.hook_commands():
            assert command.strip() != "ruff format"
            assert not command.strip().startswith("ruff ")
