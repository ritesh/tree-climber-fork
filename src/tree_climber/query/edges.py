import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from tree_climber.cfg.visitor import CFG
from tree_climber.dataflow.interprocedural import (
    RECEIVER,
    InterproceduralResult,
    analyze_interprocedural,
)

FLOW = "flow"
TRUE = "true"
FALSE = "false"
EXCEPTION = "exception"
FUNCTION_CALL = "function_call"
FUNCTION_RETURN = "function_return"
DEF_USE = "def_use"
ARGUMENT = "argument"
RETURN = "return"
FREE_VARIABLE = "free_variable"
CONTROL = "control"

CALL_KINDS: Tuple[str, str] = (FUNCTION_CALL, FUNCTION_RETURN)


@dataclass(frozen=True)
class DataFlowEdge:
    """A value flowing from `source_variable` at node `source` to
    `target_variable` at node `target`.

    Def-use chains are edges of kind `def_use`. Analyses that connect more than
    one chain, such as an argument to a callee's parameter, describe their flows
    as edges of another kind and pass them to the data-flow queries.
    """

    source: int
    source_variable: str
    target: int
    target_variable: str
    kind: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "source_variable": self.source_variable,
            "target": self.target,
            "target_variable": self.target_variable,
            "kind": self.kind,
        }


RETURN_VALUE = "<return>"


def call_result(site: int) -> str:
    """The placeholder for the result of call site `site` of a node."""
    return f"<call {site}>"


def _receiver_variables(receiver: str, uses: List[str]) -> List[str]:
    return [
        name
        for name in uses
        if re.search(rf"(?<![\w.]){re.escape(name)}(?!\w)(?!\s*\()", receiver)
    ]


def interprocedural_edges(
    cfg: CFG, flows: Optional[InterproceduralResult] = None
) -> List[DataFlowEdge]:
    """The argument, return and free-variable flows of `analyze_interprocedural`
    as `DataFlowEdge`s, for the `extra_edges` of the data-flow queries.

    An argument flows from each variable it reads, and from a nested call that is
    the argument when a return flows into that call; a return flows from the whole
    return node to the variables the call is assigned to, or to the call's result
    placeholder. `flows` are the CFG's flows when already computed.
    """
    if flows is None:
        flows = analyze_interprocedural(cfg)
    returned = {(flow.call.node, flow.call.site) for flow in flows.return_flows}
    edges: Dict[DataFlowEdge, None] = {}

    for flow in flows.argument_flows:
        node = cfg.nodes[flow.call.node]
        sites = node.metadata.call_sites
        site = sites[flow.call.site]
        if flow.argument == RECEIVER:
            role, position = "receiver", None
            variables = _receiver_variables(
                site.receiver or "", node.metadata.variable_uses
            )
        else:
            role, position = "argument", flow.argument
            variables = list(site.arguments[flow.argument].uses)
        variables += [
            call_result(index)
            for index, inner in enumerate(sites)
            if inner.feeds is not None
            and inner.feeds.call == flow.call.site
            and inner.feeds.role == role
            and inner.feeds.position == position
            and (flow.call.node, index) in returned
        ]
        for variable in variables:
            edge = DataFlowEdge(
                flow.call.node, variable, flow.callee, flow.parameter, ARGUMENT
            )
            edges[edge] = None

    for flow in flows.return_flows:
        site = cfg.nodes[flow.call.node].metadata.call_sites[flow.call.site]
        for target in site.assigned_to or [call_result(flow.call.site)]:
            edge = DataFlowEdge(
                flow.return_node, RETURN_VALUE, flow.call.node, target, RETURN
            )
            edges[edge] = None

    for flow in flows.free_variable_flows:
        edge = DataFlowEdge(
            flow.definition, flow.variable, flow.use, flow.variable, FREE_VARIABLE
        )
        edges[edge] = None

    return list(edges)
