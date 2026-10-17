from collections import deque
from typing import Dict, List

from tree_climber.cfg.visitor import CFG
from tree_climber.dataflow.dataflow_types import DataflowProblem, DataflowResult

INTERPROCEDURAL_EDGES = ("function_call", "function_return")


def _propagates(cfg: CFG, source: int, target: int) -> bool:
    return cfg.nodes[source].edge_labels.get(target) not in INTERPROCEDURAL_EDGES


class RoundRobinSolver:
    def solve(self, cfg: CFG, problem: DataflowProblem) -> DataflowResult:
        """
        Solve a dataflow problem on a given Control Flow Graph (CFG).
        """
        # Initialize IN and OUT sets
        in_facts = {node_id: set() for node_id, _ in cfg.nodes.items()}
        out_facts = {node_id: set() for node_id, _ in cfg.nodes.items()}
        for node_id, node in cfg.nodes.items():
            in_facts[node_id] = problem.in_init(node)
            out_facts[node_id] = problem.out_init(node)

        # Iterate until convergence
        changed = True
        while changed:
            changed = False  # Reset changed for the next iteration
            for node_id, node in cfg.nodes.items():
                old_out_facts = set(out_facts[node_id])
                predecessors = [
                    p
                    for p in node.predecessors
                    if cfg.nodes[p].edge_labels.get(node_id)
                    not in (
                        "function_call",
                        "function_return",
                    )  # Don't propagate DFG information across function call/return edges
                ]
                in_facts[node_id] = problem.meet(
                    [frozenset(out_facts[pred]) for pred in predecessors]
                )
                out_facts[node_id] = problem.transfer(node, in_facts[node_id])
                if out_facts[node_id] != old_out_facts:
                    changed = True

        return DataflowResult(in_facts=in_facts, out_facts=out_facts)


def reverse_postorder(cfg: CFG, successors: Dict[int, List[int]]) -> List[int]:
    has_predecessor = {target for targets in successors.values() for target in targets}
    roots = [node_id for node_id in cfg.nodes if node_id not in has_predecessor]
    seen = set()
    postorder = []
    for root in roots + list(cfg.nodes):
        if root in seen:
            continue
        seen.add(root)
        stack = [(root, iter(successors[root]))]
        while stack:
            node_id, pending = stack[-1]
            following = next((s for s in pending if s not in seen), None)
            if following is None:
                postorder.append(node_id)
                stack.pop()
            else:
                seen.add(following)
                stack.append((following, iter(successors[following])))
    return postorder[::-1]


class WorklistSolver:
    """Re-evaluates only the nodes whose inputs changed, visiting them in reverse
    postorder. It reaches the same fixpoint as `RoundRobinSolver`."""

    def solve(self, cfg: CFG, problem: DataflowProblem) -> DataflowResult:
        predecessors = {
            node_id: [p for p in node.predecessors if _propagates(cfg, p, node_id)]
            for node_id, node in cfg.nodes.items()
        }
        successors: Dict[int, List[int]] = {node_id: [] for node_id in cfg.nodes}
        for node_id, sources in predecessors.items():
            for source in sources:
                successors[source].append(node_id)
        in_facts = {
            node_id: problem.in_init(node) for node_id, node in cfg.nodes.items()
        }
        out_facts = {
            node_id: problem.out_init(node) for node_id, node in cfg.nodes.items()
        }
        frozen = {node_id: frozenset(facts) for node_id, facts in out_facts.items()}

        order = reverse_postorder(cfg, successors)
        worklist = deque(order)
        queued = set(order)
        while worklist:
            node_id = worklist.popleft()
            queued.remove(node_id)
            in_facts[node_id] = problem.meet(
                [frozen[pred] for pred in predecessors[node_id]]
            )
            out = problem.transfer(cfg.nodes[node_id], in_facts[node_id])
            if out == out_facts[node_id]:
                continue
            out_facts[node_id] = out
            frozen[node_id] = frozenset(out)
            for successor in successors[node_id]:
                if successor not in queued:
                    queued.add(successor)
                    worklist.append(successor)

        return DataflowResult(in_facts=in_facts, out_facts=out_facts)
