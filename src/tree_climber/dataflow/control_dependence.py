"""Control dependence: which branch decides whether a node runs.

A node is control dependent on a branch X through one of X's edges when taking
that edge makes it run, and X's other edges do not have to. Computed per
function from post-dominators (Cooper, Harvey and Kennedy's algorithm on the
reversed CFG, rooted at the function's EXIT), so every construct is handled
through its edges: Python `match`, `try`/`finally` and loop `else`, C and Java
`switch`. Call and return edges are not part of a function's flow.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from tree_climber.cfg.cfg_types import NodeType
from tree_climber.cfg.visitor import CFG
from tree_climber.dataflow.interprocedural import CALL_LABELS, function_nodes

FLOW = "flow"

Dependence = Tuple[int, str]


@dataclass
class ControlDependence:
    """`controllers[n]` are the (branch node, edge label) pairs `n` depends on;
    `dependents[x]` are the nodes that depend on branch `x`."""

    controllers: Dict[int, List[Dependence]] = field(default_factory=dict)
    dependents: Dict[int, List[int]] = field(default_factory=dict)


def _successors(cfg: CFG, node_id: int, members: Set[int]) -> List[Tuple[int, str]]:
    node = cfg.nodes[node_id]
    return [
        (successor, node.edge_labels.get(successor) or FLOW)
        for successor in sorted(node.successors)
        if node.edge_labels.get(successor) not in CALL_LABELS and successor in members
    ]


def _post_dominators(
    cfg: CFG, members: Set[int], exit_id: int
) -> Dict[int, Optional[int]]:
    """Immediate post-dominators; None for the exit and for nodes that cannot
    reach it."""
    predecessors: Dict[int, List[int]] = {n: [] for n in members}
    for n in members:
        for successor, _ in _successors(cfg, n, members):
            predecessors[successor].append(n)

    order: List[int] = []
    seen = {exit_id}
    stack = [(exit_id, iter(predecessors[exit_id]))]
    while stack:
        node, children = stack[-1]
        child = next(children, None)
        if child is None:
            stack.pop()
            order.append(node)
        elif child not in seen:
            seen.add(child)
            stack.append((child, iter(predecessors[child])))
    order.reverse()
    rank = {node: index for index, node in enumerate(order)}

    ipdom: Dict[int, int] = {exit_id: exit_id}

    def intersect(a: int, b: int) -> int:
        while a != b:
            while rank[a] > rank[b]:
                a = ipdom[a]
            while rank[b] > rank[a]:
                b = ipdom[b]
        return a

    changed = True
    while changed:
        changed = False
        for node in order[1:]:
            candidates = [s for s, _ in _successors(cfg, node, members) if s in ipdom]
            if not candidates:
                continue
            new = candidates[0]
            for other in candidates[1:]:
                new = intersect(other, new)
            if ipdom.get(node) != new:
                ipdom[node] = new
                changed = True

    result: Dict[int, Optional[int]] = {n: ipdom.get(n) for n in members}
    result[exit_id] = None
    return result


def control_dependence(cfg: CFG) -> ControlDependence:
    owner = function_nodes(cfg)
    groups: Dict[int, Set[int]] = {}
    for node_id, entry in owner.items():
        groups.setdefault(entry, set()).add(node_id)

    result = ControlDependence()
    for members in groups.values():
        exits = [n for n in members if cfg.nodes[n].node_type == NodeType.EXIT]
        if len(exits) != 1:
            continue
        ipdom = _post_dominators(cfg, members, exits[0])
        for branch in sorted(members):
            edges = _successors(cfg, branch, members)
            if len(edges) < 2:
                continue
            for successor, label in edges:
                runner: Optional[int] = successor
                while runner is not None and runner != ipdom[branch]:
                    dependence = (branch, label)
                    controllers = result.controllers.setdefault(runner, [])
                    if dependence not in controllers:
                        controllers.append(dependence)
                        dependents = result.dependents.setdefault(branch, [])
                        if runner not in dependents:
                            dependents.append(runner)
                    runner = ipdom[runner]
    for values in result.dependents.values():
        values.sort()
    return result
