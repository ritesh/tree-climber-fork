"""
Tests for tree_climber.language_registry, the single source of truth for
supported languages.

Every registered language is checked end to end (grammar, visitor, builder), so
adding a language to the registry is covered without writing new tests.
"""

import asyncio
from pathlib import Path

import pytest
from tree_sitter_languages import get_parser

from tree_climber.cfg.builder import CFGBuilder
from tree_climber.cfg.languages.c import CCFGVisitor
from tree_climber.cfg.languages.java import JavaCFGVisitor
from tree_climber.cfg.languages.python import PythonCFGVisitor
from tree_climber.cfg.visitor import CFGVisitor
from tree_climber.cli import DEFAULT_LANGUAGE as CLI_DEFAULT_LANGUAGE
from tree_climber.cli import SUPPORTED_LANGUAGES as CLI_SUPPORTED_LANGUAGES
from tree_climber.cli.source import FileSource
from tree_climber.language_registry import (
    DEFAULT_LANGUAGE,
    LANGUAGES,
    SUPPORTED_LANGUAGES,
    create_visitor,
    get_language,
    language_for_extension,
)
from tree_climber.viz.app import app, root


def test_registry_contents():
    assert {"c", "java", "python"} <= set(LANGUAGES)
    assert SUPPORTED_LANGUAGES == list(LANGUAGES)
    assert DEFAULT_LANGUAGE in LANGUAGES


@pytest.mark.parametrize("name", list(LANGUAGES))
class TestEachRegisteredLanguage:
    def test_spec_is_well_formed(self, name):
        spec = get_language(name)

        assert spec.name == name
        assert spec.display_name
        assert spec.extensions
        for extension in spec.extensions:
            assert extension.startswith(".")
            assert extension == extension.lower()

    def test_grammar_loads(self, name):
        assert get_parser(name) is not None

    def test_visitor_is_created_fresh_each_time(self, name):
        first = create_visitor(name)
        second = create_visitor(name)

        assert isinstance(first, CFGVisitor)
        assert first is not second

    def test_builder_sets_up_a_parser(self, name):
        builder = CFGBuilder(name)
        builder.setup_parser()

        assert builder.parser is not None


def test_visitor_classes():
    assert isinstance(create_visitor("c"), CCFGVisitor)
    assert isinstance(create_visitor("java"), JavaCFGVisitor)
    assert isinstance(create_visitor("python"), PythonCFGVisitor)


def test_no_extension_is_claimed_by_two_languages():
    seen = {}
    for spec in LANGUAGES.values():
        for extension in spec.extensions:
            assert extension not in seen, (
                f"{extension} is claimed by {seen[extension]} and {spec.name}"
            )
            seen[extension] = spec.name


@pytest.mark.parametrize(
    "suffix, expected",
    [
        (".c", "c"),
        (".h", "c"),
        (".C", "c"),
        (".java", "java"),
        (".JAVA", "java"),
        (".py", "python"),
        (".pyi", "python"),
        (".PY", "python"),
        (".txt", None),
        ("", None),
    ],
)
def test_language_for_extension(suffix, expected):
    assert language_for_extension(suffix) == expected


@pytest.mark.parametrize(
    "filename, expected",
    [
        ("prog.c", "c"),
        ("prog.h", "c"),
        ("Main.JAVA", "java"),
        ("script.py", "python"),
        ("notes.txt", None),
    ],
)
def test_file_source_language_hint(filename, expected):
    assert FileSource(Path("somewhere") / filename).get_language_hint() == expected


def test_unsupported_language():
    with pytest.raises(ValueError, match="Unsupported language: cobol"):
        get_language("cobol")
    with pytest.raises(ValueError, match="Unsupported language: cobol"):
        create_visitor("cobol")


def test_cli_and_api_use_the_registry():
    assert CLI_SUPPORTED_LANGUAGES == SUPPORTED_LANGUAGES
    assert CLI_DEFAULT_LANGUAGE == DEFAULT_LANGUAGE
    assert asyncio.run(root())["supported_languages"] == SUPPORTED_LANGUAGES

    language_schema = app.openapi()["components"]["schemas"]["ParseRequest"][
        "properties"
    ]["language"]
    assert language_schema["enum"] == SUPPORTED_LANGUAGES
