# Define a simple dataflow problem (e.g., reaching definitions)
from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from tree_sitter import Node

from tree_climber.ast_utils import dfs, get_source_text
from tree_climber.cfg.cfg_types import CFGNode
from tree_climber.dataflow.dataflow_types import (
    DataflowFact,
    DataflowInitializer,
    DataflowProblem,
    MeetOperation,
    TransferFunction,
)


class ReachingDefinition(DataflowFact):
    def __init__(self, variable: str, node_id: int):
        self.variable_name = variable
        self.node_id = node_id

    def __hash__(self) -> int:
        return hash((self.variable_name, self.node_id))

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, ReachingDefinition)
            and self.node_id == other.node_id
            and self.variable_name == other.variable_name
        )

    def __repr__(self) -> str:
        return (
            f"ReachingDefinition(variable={self.variable_name}, node_id={self.node_id})"
        )


def extract_function_call_arguments(ast_node: Node) -> List[str]:
    """Extract variable names used as arguments in function calls."""
    arguments = []

    def process_call(node: Node) -> Optional[str]:
        if node.type in ("call_expression", "method_invocation"):
            # Find argument_list or arguments
            for child in node.children:
                if child.type in ("argument_list", "arguments"):
                    # Extract identifiers from arguments
                    for arg_child in child.children:
                        if arg_child.type == "identifier":
                            arguments.append(get_source_text(arg_child))
                        elif arg_child.is_named:  # Handle complex expressions
                            # Look for identifiers within the argument expression
                            for identifier in dfs(
                                arg_child,
                                lambda n: (
                                    get_source_text(n)
                                    if n.type == "identifier"
                                    else None
                                ),
                            ):
                                if identifier:
                                    arguments.append(identifier)
        return None

    dfs(ast_node, process_call)
    return arguments


class Union(MeetOperation):
    def __call__(self, facts: Iterable[frozenset[DataflowFact]]) -> Set[DataflowFact]:
        return set().union(*facts)


class ReachingDefinitionsGenKill(TransferFunction):
    def __init__(self) -> None:
        self._gen: Dict[
            int, Tuple[CFGNode, FrozenSet[str], FrozenSet[DataflowFact]]
        ] = {}

    def gen(self, node: CFGNode) -> Tuple[FrozenSet[str], FrozenSet[DataflowFact]]:
        """The names the node defines and their facts, built once per node so that
        facts compare by identity."""
        cached = self._gen.get(node.id)
        if cached is None or cached[0] is not node:
            names = frozenset(
                node.metadata.variable_definitions if node.ast_node else []
            )
            facts = frozenset(ReachingDefinition(name, node.id) for name in names)
            cached = (node, names, facts)
            self._gen[node.id] = cached
        return cached[1], cached[2]

    def __call__(self, node: CFGNode, in_facts: Set[DataflowFact]) -> Set[DataflowFact]:
        defined_variables, gen_facts = self.gen(node)
        if not defined_variables:
            return set(in_facts)
        kill_facts = {
            fact
            for fact in in_facts
            if isinstance(fact, ReachingDefinition)
            and fact.variable_name in defined_variables
        }

        out_facts = (in_facts - kill_facts) | gen_facts
        return out_facts


class Empty(DataflowInitializer):
    def __call__(self, _node: CFGNode) -> Set[DataflowFact]:
        # Initialize with an empty set of facts
        return set()


def ReachingDefinitionsProblem() -> DataflowProblem:
    """Factory function to create a reaching definitions analysis."""
    return DataflowProblem(
        meet=Union(),
        transfer=ReachingDefinitionsGenKill(),
        in_init=Empty(),
        out_init=Empty(),
    )
