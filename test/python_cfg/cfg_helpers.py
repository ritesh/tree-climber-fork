"""Helpers shared by the Python CFG and def/use tests."""

from typing import List, Optional, Set, Tuple

from tree_climber.cfg.builder import CFGBuilder
from tree_climber.cfg.cfg_types import CFGNode, NodeType
from tree_climber.cfg.visitor import CFG

Edge = Tuple[str, str, Optional[str]]


def build_cfg(code: str) -> CFG:
    builder = CFGBuilder("python")
    builder.setup_parser()
    return builder.build_cfg(code)


def label(node: CFGNode) -> str:
    """Name a node by its text; ENTRY/EXIT nodes are prefixed with their type."""
    if node.node_type in (NodeType.ENTRY, NodeType.EXIT):
        return f"{node.node_type.name}:{node.source_text}"
    return node.source_text


def edges(cfg: CFG) -> Set[Edge]:
    return {
        (label(node), label(cfg.nodes[successor]), node.edge_labels.get(successor))
        for node in cfg.nodes.values()
        for successor in node.successors
    }


def node_by_text(cfg: CFG, text: str) -> CFGNode:
    matches = [node for node in cfg.nodes.values() if label(node) == text]
    assert len(matches) == 1, f"Expected exactly one node '{text}', got {len(matches)}"
    return matches[0]


def reachable_from(cfg: CFG, start_id: int) -> Set[int]:
    seen: Set[int] = set()
    stack = [start_id]
    while stack:
        node_id = stack.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        stack.extend(cfg.nodes[node_id].successors)
    return seen


def entry_names(cfg: CFG) -> List[str]:
    return [cfg.nodes[entry_id].source_text for entry_id in cfg.entry_node_ids]
