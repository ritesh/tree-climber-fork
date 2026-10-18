"""Taint rules: where untrusted values come from, where they must not go, and
what makes them safe.

A call pattern is a glob (`fnmatch`) matched against a call's whole callee
expression: `system` is a plain `system(...)` call, `os.system` that function
through its module, `*.execute` a method of any object.
"""

import json
import re
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from tree_climber.cfg.cfg_types import CallSite

Position = Union[int, str]


@lru_cache(maxsize=None)
def _attribute_pattern(attribute: str) -> re.Pattern:
    body = r"\.".join(
        r"\w+" if part == "*" else re.escape(part) for part in attribute.split(".")
    )
    return re.compile(rf"(?<![\w.]){body}(?!\w)")


def call_matches(pattern: str, site: CallSite) -> bool:
    return fnmatchcase(site.callee_text, pattern)


@dataclass(frozen=True)
class Source:
    """Exactly one of: `call` (the call's result is tainted), `parameter` (a
    parameter, by name or position, of the functions matching `function`), or
    `attribute` (an attribute access such as `request.args`, matched in the
    source text; `*` stands for one name)."""

    call: Optional[str] = None
    parameter: Optional[Position] = None
    function: str = "*"
    attribute: Optional[str] = None

    def __post_init__(self):
        given = [self.call, self.parameter, self.attribute]
        if sum(value is not None for value in given) != 1:
            raise ValueError("A source has exactly one of call, parameter, attribute")

    def attribute_pattern(self) -> Optional[re.Pattern]:
        if self.attribute is None:
            return None
        return _attribute_pattern(self.attribute)

    def attribute_literal(self) -> str:
        """The longest part of the attribute that is not `*`: text that every
        match contains, to rule out most nodes before the regex runs."""
        parts = (self.attribute or "").split(".")
        return max((part for part in parts if part != "*"), key=len, default="")

    def to_dict(self) -> Dict[str, Any]:
        if self.call is not None:
            return {"call": self.call}
        if self.attribute is not None:
            return {"attribute": self.attribute}
        return {"parameter": self.parameter, "function": self.function}


@dataclass(frozen=True)
class Sink:
    """A call whose watched arguments must not be tainted: positional indexes
    and keyword names, or every argument when `arguments` is None."""

    call: str
    arguments: Optional[Sequence[Position]] = None

    def watches(self, site: CallSite, index: int) -> bool:
        if self.arguments is None:
            return True
        argument = site.arguments[index]
        if argument.kind == "keyword":
            return argument.keyword in self.arguments
        if argument.kind in ("star", "double_star"):
            return True
        position = sum(
            1 for earlier in site.arguments[:index] if earlier.kind == "positional"
        )
        return position in self.arguments

    def to_dict(self) -> Dict[str, Any]:
        arguments = list(self.arguments) if self.arguments is not None else None
        return {"call": self.call, "arguments": arguments}


@dataclass(frozen=True)
class Sanitizer:
    """A call whose result is clean, whatever it was given."""

    call: str

    def to_dict(self) -> Dict[str, Any]:
        return {"call": self.call}


@dataclass(frozen=True)
class Rule:
    id: str
    sources: Sequence[Source]
    sinks: Sequence[Sink]
    sanitizers: Sequence[Sanitizer] = ()
    description: str = ""
    languages: Optional[Sequence[str]] = None

    def applies_to(self, language: Optional[str]) -> bool:
        return language is None or self.languages is None or language in self.languages

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Rule":
        unknown = set(data) - {
            "id",
            "description",
            "languages",
            "sources",
            "sinks",
            "sanitizers",
        }
        if unknown:
            raise ValueError(f"Unknown rule keys: {sorted(unknown)}")
        return cls(
            id=data["id"],
            description=data.get("description", ""),
            languages=data.get("languages"),
            sources=tuple(Source(**source) for source in data.get("sources", [])),
            sinks=tuple(
                Sink(
                    sink["call"],
                    tuple(sink["arguments"])
                    if sink.get("arguments") is not None
                    else None,
                )
                for sink in data.get("sinks", [])
            ),
            sanitizers=tuple(
                Sanitizer(**sanitizer) for sanitizer in data.get("sanitizers", [])
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "languages": list(self.languages) if self.languages is not None else None,
            "sources": [source.to_dict() for source in self.sources],
            "sinks": [sink.to_dict() for sink in self.sinks],
            "sanitizers": [sanitizer.to_dict() for sanitizer in self.sanitizers],
        }


@dataclass(frozen=True)
class RuleSet:
    rules: Sequence[Rule] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuleSet":
        rules = tuple(Rule.from_dict(rule) for rule in data.get("rules", []))
        ids = [rule.id for rule in rules]
        if len(ids) != len(set(ids)):
            raise ValueError("Rule ids must be unique")
        return cls(rules)

    @classmethod
    def from_json(cls, text: str) -> "RuleSet":
        return cls.from_dict(json.loads(text))

    @classmethod
    def load(cls, path: Union[str, Path]) -> "RuleSet":
        """Rules from a JSON file. For YAML, parse it yourself and pass the dict
        to `from_dict` (PyYAML is not a dependency)."""
        return cls.from_json(Path(path).read_text())

    def for_language(self, language: Optional[str]) -> List[Rule]:
        return [rule for rule in self.rules if rule.applies_to(language)]

    def to_dict(self) -> Dict[str, Any]:
        return {"rules": [rule.to_dict() for rule in self.rules]}
