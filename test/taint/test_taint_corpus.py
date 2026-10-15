"""
The taint corpus in test/taint/corpus: programs annotated with what the
built-in rules must report, must not report, and do not report yet (see the
corpus README for the annotation format).
"""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import FrozenSet, List, Optional, Tuple

import pytest

from tree_climber.cfg.builder import CFGBuilder
from tree_climber.language_registry import language_for_extension
from tree_climber.reporting import node_line
from tree_climber.taint import analyze, builtin_rules

CORPUS = Path(__file__).parent / "corpus"
FILES = sorted(
    path
    for path in CORPUS.rglob("*")
    if path.is_file() and language_for_extension(path.suffix) is not None
)
ANNOTATION = re.compile(
    r"^\s*(?:#|//)\s*(ruleid|ok|todoruleid|todook):\s*([\w-]+)(?:\s*--\s*(.*\S))?\s*$"
)
OPTIONS = re.compile(r"taint-options:\s*([\w ]+)")
COMMENT = re.compile(r"^\s*(#|//|/\*|\*)")


@dataclass(frozen=True)
class Case:
    path: Path
    line: int
    kind: str
    rule: str
    reason: Optional[str]

    @property
    def id(self) -> str:
        return f"{self.path.relative_to(CORPUS)}:{self.line}:{self.kind}:{self.rule}"


def language(path: Path) -> str:
    found = language_for_extension(path.suffix)
    assert found is not None
    return found


def annotations(path: Path) -> List[Case]:
    lines = path.read_text().splitlines()
    cases = []
    for index, text in enumerate(lines):
        match = ANNOTATION.match(text)
        if match is None:
            continue
        target = next(
            number
            for number in range(index + 1, len(lines))
            if lines[number].strip() and not COMMENT.match(lines[number])
        )
        kind, rule, reason = match.groups()
        cases.append(Case(path, target + 1, kind, rule, reason))
    return cases


@cache
def findings(path: Path) -> FrozenSet[Tuple[str, int]]:
    source = path.read_text()
    match = OPTIONS.search(source)
    options = set(match.group(1).split()) if match else set()
    builder = CFGBuilder(language(path))
    builder.setup_parser()
    cfg = builder.build_cfg(source)
    found = analyze(
        cfg,
        builtin_rules(language(path)),
        language(path),
        implicit_flows="implicit_flows" in options,
        field_sensitive="field_sensitive" in options,
    )
    lines = set()
    for finding in found:
        line = node_line(cfg.nodes[finding.sink])
        assert line is not None
        lines.add((finding.rule, line))
    return frozenset(lines)


CASES = [case for path in FILES for case in annotations(path)]


def param(case: Case):
    marks = []
    if case.kind.startswith("todo"):
        marks.append(pytest.mark.xfail(strict=True, reason=case.reason or ""))
    return pytest.param(case, id=case.id, marks=marks)


def test_the_corpus_covers_every_language():
    assert {language(path) for path in FILES} == {"c", "java", "python"}
    assert all(annotations(path) for path in FILES)


@pytest.mark.parametrize(
    "path", [pytest.param(p, id=str(p.relative_to(CORPUS))) for p in FILES]
)
def test_annotations_are_well_formed(path: Path):
    rules = {rule.id for rule in builtin_rules(language(path)).rules}
    for case in annotations(path):
        assert case.rule in rules, case.id
        assert bool(case.reason) == case.kind.startswith("todo"), case.id


@pytest.mark.parametrize("case", [param(case) for case in CASES])
def test_annotation(case: Case):
    found = (case.rule, case.line) in findings(case.path)
    assert found == (case.kind in ("ruleid", "todoruleid"))


@pytest.mark.parametrize(
    "path", [pytest.param(p, id=str(p.relative_to(CORPUS))) for p in FILES]
)
def test_every_finding_is_annotated(path: Path):
    expected = {
        (case.rule, case.line)
        for case in annotations(path)
        if case.kind in ("ruleid", "todook")
    }
    assert sorted(findings(path) - expected) == []
