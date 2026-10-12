"""Single source of truth for the programming languages Tree Climber supports."""

import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from tree_climber.cfg.visitor import CFGVisitor


@dataclass(frozen=True)
class LanguageSpec:
    """Describes one supported language.

    `name` is the registry key and the tree-sitter grammar name. `visitor` is a
    "module:Class" path, imported lazily so listing languages stays cheap.
    """

    name: str
    display_name: str
    extensions: Tuple[str, ...]
    visitor: str


LANGUAGES: Dict[str, LanguageSpec] = {
    spec.name: spec
    for spec in (
        LanguageSpec(
            name="c",
            display_name="C",
            extensions=(".c", ".h"),
            visitor="tree_climber.cfg.languages.c:CCFGVisitor",
        ),
        LanguageSpec(
            name="java",
            display_name="Java",
            extensions=(".java",),
            visitor="tree_climber.cfg.languages.java:JavaCFGVisitor",
        ),
    )
}

SUPPORTED_LANGUAGES: List[str] = list(LANGUAGES)
DEFAULT_LANGUAGE: str = "c"


def get_language(name: str) -> LanguageSpec:
    """Return the spec for a language name, or raise ValueError if unsupported."""
    try:
        return LANGUAGES[name]
    except KeyError:
        raise ValueError(f"Unsupported language: {name}") from None


def create_visitor(name: str) -> "CFGVisitor":
    """Create a fresh CFG visitor for a language."""
    module_name, class_name = get_language(name).visitor.split(":")
    visitor_class = getattr(importlib.import_module(module_name), class_name)
    return visitor_class()


def language_for_extension(suffix: str) -> Optional[str]:
    """Return the language name for a file extension such as ".c", if any."""
    suffix = suffix.lower()
    for spec in LANGUAGES.values():
        if suffix in spec.extensions:
            return spec.name
    return None
