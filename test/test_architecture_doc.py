"""
The examples in docs/architecture.md: the Python blocks run in order, in one
namespace, and each prints what the block after it shows. Quoted code names
the source file it comes from, which must exist.
"""

import io
import re
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
DOC = (ROOT / "docs" / "architecture.md").read_text()
BLOCKS = list(re.finditer(r"^```(\w*)\n(.*?)^```$", DOC, re.M | re.S))
EXAMPLES = [
    (first.group(2), second.group(2))
    for first, second in zip(BLOCKS, BLOCKS[1:])
    if first.group(1) == "python"
    and second.group(1) == ""
    and DOC[first.end() : second.start()] == "\n\n"
]
QUOTED = [
    match.group(1)
    for block in BLOCKS
    if block.group(1) == "python"
    and (match := re.match(r"# ([\w/]+\.py)", block.group(2)))
]


def test_the_document_has_its_examples_and_quotes():
    assert len(EXAMPLES) == 10
    assert len(QUOTED) == 10


def test_the_examples_print_what_the_document_shows():
    namespace: dict = {}
    for code, expected in EXAMPLES:
        printed = io.StringIO()
        with redirect_stdout(printed):
            exec(code, namespace)
        assert printed.getvalue() == expected, code


@pytest.mark.parametrize("path", QUOTED)
def test_quoted_code_names_a_real_file(path):
    assert (ROOT / "src" / "tree_climber" / path).is_file()
