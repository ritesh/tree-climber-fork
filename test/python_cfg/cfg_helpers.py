"""Helpers shared by the Python CFG and def/use tests."""

from typing import Dict, List, Optional, Set, Tuple

from tree_climber.cfg.builder import CFGBuilder
from tree_climber.cfg.cfg_types import CFGNode, NodeType
from tree_climber.cfg.visitor import CFG
from tree_climber.dataflow.analyses.def_use import DefUseSolver
from tree_climber.dataflow.analyses.reaching_definitions import (
    ReachingDefinitionsProblem,
)
from tree_climber.dataflow.solver import WorklistSolver

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


def def_use_chains(code: str, variable: str) -> Dict[str, List[str]]:
    """Def-use chains of a variable as {definition text: sorted use texts}."""
    cfg = build_cfg(code)
    reaching = WorklistSolver().solve(cfg, ReachingDefinitionsProblem())
    result = DefUseSolver().solve(cfg, reaching)
    return {
        label(cfg.nodes[chain.definition]): sorted(
            label(cfg.nodes[use]) for use in chain.uses
        )
        for chain in result.chains.get(variable, [])
    }


CALL_LABELS = ("function_call", "function_return")


def function_nodes(cfg: CFG, name: str) -> Set[int]:
    """Nodes of one function: reachable from its entry without following call edges."""
    entry = next(
        entry_id
        for entry_id in cfg.entry_node_ids
        if cfg.nodes[entry_id].source_text == name
    )
    seen: Set[int] = set()
    stack = [entry]
    while stack:
        node_id = stack.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        node = cfg.nodes[node_id]
        stack.extend(
            successor
            for successor in node.successors
            if node.edge_labels.get(successor) not in CALL_LABELS
        )
    return seen


def first_line(text: str) -> str:
    return text.splitlines()[0] if text else text


def function_edges(cfg: CFG, name: str) -> Set[Edge]:
    """Edges inside one function, by the first line of each node's text."""
    members = function_nodes(cfg, name)
    return {
        (
            first_line(label(node)),
            first_line(label(cfg.nodes[successor])),
            node.edge_labels.get(successor),
        )
        for node_id in members
        for node in [cfg.nodes[node_id]]
        for successor in node.successors
        if successor in members and node.edge_labels.get(successor) not in CALL_LABELS
    }


def function_chains(cfg: CFG, name: str) -> Dict[str, Dict[str, List[str]]]:
    """Def-use chains inside one function: {variable: {definition: [uses]}}."""
    members = function_nodes(cfg, name)
    reaching = WorklistSolver().solve(cfg, ReachingDefinitionsProblem())
    result = DefUseSolver().solve(cfg, reaching)
    chains: Dict[str, Dict[str, List[str]]] = {}
    for variable, variable_chains in result.chains.items():
        for chain in variable_chains:
            if chain.definition not in members:
                continue
            chains.setdefault(variable, {})[
                first_line(label(cfg.nodes[chain.definition]))
            ] = sorted(
                first_line(label(cfg.nodes[use]))
                for use in chain.uses
                if use in members
            )
    return chains
