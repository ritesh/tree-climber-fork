"""What the CLI and the HTTP API report from the query and taint APIs: rule sets
named by the user, nodes by source line, and nodes as JSON."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from tree_climber.cfg.cfg_types import CFGNode
from tree_climber.query import CodeGraph
from tree_climber.taint import RuleSet, builtin_rules

BUILTIN_RULES = "builtin"
YAML_SUFFIXES = (".yaml", ".yml")


def rules_for_language(rules: RuleSet, language: str, origin: str) -> RuleSet:
    applicable = rules.for_language(language)
    if not applicable:
        raise ValueError(f"No rules for {language} in {origin}")
    return RuleSet(tuple(applicable))


def rules_from_dict(data: Any, language: str, origin: str = "the rules") -> RuleSet:
    try:
        rules = RuleSet.from_dict(data)
    except KeyError as e:
        raise ValueError(f"Invalid rules in {origin}: missing key {e}") from e
    except (AttributeError, TypeError, ValueError) as e:
        raise ValueError(f"Invalid rules in {origin}: {e}") from e
    return rules_for_language(rules, language, origin)


def load_rules(spec: str, language: str) -> RuleSet:
    """`builtin` for the example rules, or a JSON rule file."""
    if spec == BUILTIN_RULES:
        return rules_for_language(builtin_rules(), language, "the built-in rules")
    path = Path(spec)
    if path.suffix.lower() in YAML_SUFFIXES:
        raise ValueError(
            f"YAML rule files are not supported: write {path} as JSON (same structure)"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise ValueError(f"Cannot read rules from {path}: {e.strerror}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {path}: {e}") from e
    return rules_from_dict(data, language, str(path))


def node_line(node: CFGNode) -> Optional[int]:
    if node.ast_node is None:
        return None
    return node.ast_node.start_point[0] + 1


def nodes_on_line(graph: CodeGraph, line: int) -> List[CFGNode]:
    """The nodes that start on the line, or else the nodes spanning it (a line
    inside a statement)."""
    spans = [
        (node.ast_node.start_point[0] + 1, node.ast_node.end_point[0] + 1, node)
        for node in graph.nodes
        if node.ast_node is not None
    ]
    starting = [node for start, _, node in spans if start == line]
    return starting or [node for start, end, node in spans if start < line <= end]


def slice_from_line(
    graph: CodeGraph,
    line: int,
    backward: bool = False,
    variable: Optional[str] = None,
    across_calls: bool = True,
) -> List[CFGNode]:
    starts = nodes_on_line(graph, line)
    if not starts:
        raise ValueError(f"No statement on line {line}")
    extra_edges = graph.interprocedural_edges() if across_calls else None
    slice_of = graph.backward_slice if backward else graph.forward_slice
    found = {
        node.id: node
        for start in starts
        for node in slice_of(start, variable, extra_edges=extra_edges)
    }
    return [found[node_id] for node_id in sorted(found)]


def node_to_dict(graph: CodeGraph, node: CFGNode) -> Dict[str, Any]:
    function = graph.function_of(node)
    return {
        "node": node.id,
        "node_type": node.node_type.name,
        "text": node.source_text.splitlines()[0] if node.source_text else "",
        "line": node_line(node),
        "function": function.source_text if function else None,
    }
