"""
The examples in docs/taint-guide.md, taken from the guide itself: each file it
asks to save, each command followed by its output, and each Python example
followed by its output.
"""

import io
import os
import re
import shutil
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

GUIDE = (Path(__file__).parents[2] / "docs" / "taint-guide.md").read_text()

BLOCKS = list(re.finditer(r"^```(\w*)\n(.*?)^```$", GUIDE, re.M | re.S))
FILES = {
    name.group(1): block.group(2)
    for block in BLOCKS
    if (name := re.search(r"`([\w.]+)`:\n\n$", GUIDE[: block.start()]))
}
PAIRS = [
    (first.group(1), first.group(2), second.group(2))
    for first, second in zip(BLOCKS, BLOCKS[1:])
    if GUIDE[first.end() : second.start()] == "\n\n" and second.group(1) == ""
]
COMMANDS = [(code, output) for kind, code, output in PAIRS if kind == "bash"]
PROGRAMS = [(code, output) for kind, code, output in PAIRS if kind == "python"]


def test_the_guide_has_its_examples():
    assert set(FILES) == {"app.py", "views.py", "rules.json", "logger.c", "Search.java"}
    assert len(COMMANDS) == 8
    assert len(PROGRAMS) == 2


@pytest.mark.parametrize(
    "command, output", COMMANDS, ids=[c.strip() for c, _ in COMMANDS]
)
def test_command(command, output, tmp_path):
    if "| jq" in command and shutil.which("jq") is None:
        pytest.skip("jq is not installed")
    for name, text in FILES.items():
        (tmp_path / name).write_text(text)
    command = command.replace(
        "uv run tree-climber", f"{sys.executable} -m tree_climber.cli"
    )
    result = subprocess.run(
        command,
        shell=True,
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"},
    )
    assert result.stdout == output


@pytest.mark.parametrize("program, output", PROGRAMS)
def test_program(program, output):
    printed = io.StringIO()
    with redirect_stdout(printed):
        exec(program, {})
    assert printed.getvalue() == output
