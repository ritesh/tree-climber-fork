"""
Data flow between functions.

The solver keeps each function's flow separate (nothing crosses `function_call` /
`function_return` edges, so a callee's locals cannot overwrite the caller's). This
module adds the flow that does cross: arguments into parameters, return values into
call sites, and free variables (closures, `global`, `nonlocal`, C globals) into the
functions that read them. The result is a list of edges between the existing
def-use islands; the solver and its results are untouched.

Calls are resolved by name, as everywhere else: a call reaches every function
registered under its callee name. Free-variable flow is flow-insensitive: every
definition in a scope reaches every use that resolves to it.
"""

from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Set, Tuple

from tree_climber.cfg.cfg_types import (
    CallSite,
    FunctionInfo,
    NodeType,
)
from tree_climber.cfg.visitor import CFG

CALL_LABELS = ("function_call", "function_return")
RECEIVER = -1


@dataclass(frozen=True)
class CallRef:
    """A call site: the node it is in, and its index in that node's `call_sites`."""

    node: int
    site: int

    def to_dict(self) -> Dict[str, int]:
        return {"node": self.node, "site": self.site}


@dataclass(frozen=True)
class ArgumentFlow:
    """An argument of a call flows into a parameter of a function it may call.
    `argument` indexes the site's arguments, or is -1 for the receiver (bound to
    `self`)."""

    call: CallRef
    argument: int
    callee: int
    parameter: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "call": self.call.to_dict(),
            "argument": self.argument,
            "callee": self.callee,
            "parameter": self.parameter,
        }


@dataclass(frozen=True)
class ReturnFlow:
    """A `return` node of a function flows into a call site that may call it."""

    return_node: int
    call: CallRef

    def to_dict(self) -> Dict[str, object]:
        return {"return_node": self.return_node, "call": self.call.to_dict()}


@dataclass(frozen=True)
class FreeVariableFlow:
    """A definition of `variable` in one function reaches a use of it in another.
    `scope` is "closure" (a nested function's enclosing function) or "global"."""

    variable: str
    definition: int
    use: int
    scope: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "variable": self.variable,
            "definition": self.definition,
            "use": self.use,
            "scope": self.scope,
        }


@dataclass
class InterproceduralResult:
    argument_flows: List[ArgumentFlow] = field(default_factory=list)
    return_flows: List[ReturnFlow] = field(default_factory=list)
    free_variable_flows: List[FreeVariableFlow] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "argument_flows": [f.to_dict() for f in self.argument_flows],
            "return_flows": [f.to_dict() for f in self.return_flows],
            "free_variable_flows": [f.to_dict() for f in self.free_variable_flows],
        }


def function_nodes(cfg: CFG) -> Dict[int, int]:
    """Map each node to the ENTRY node of its function: the node is reachable from
    that entry without following call or return edges."""
    owner: Dict[int, int] = {}
    for entry in cfg.entry_node_ids:
        stack = [entry]
        while stack:
            node_id = stack.pop()
            if node_id in owner:
                continue
            owner[node_id] = entry
            node = cfg.nodes[node_id]
            stack.extend(
                successor
                for successor in node.successors
                if node.edge_labels.get(successor) not in CALL_LABELS
            )
    return owner


def analyze_interprocedural(cfg: CFG) -> InterproceduralResult:
    """Argument, return and free-variable flows between the functions of a CFG."""
    owner = function_nodes(cfg)
    entries_by_name: Dict[str, List[int]] = {}
    for entry, name in cfg.context.function_definitions.items():
        entries_by_name.setdefault(name, []).append(entry)

    result = InterproceduralResult()
    returns_by_entry: Dict[int, List[int]] = {}
    for node_id, node in cfg.nodes.items():
        if node.node_type == NodeType.RETURN and node_id in owner:
            returns_by_entry.setdefault(owner[node_id], []).append(node_id)

    for node_id, node in cfg.nodes.items():
        for index, site in enumerate(node.metadata.call_sites):
            if site.callee is None:
                continue
            call = CallRef(node_id, index)
            for entry in entries_by_name.get(site.callee, []):
                info = cfg.nodes[entry].metadata.function
                if info is None:
                    continue
                result.argument_flows.extend(_argument_flows(call, site, entry, info))
                if not info.is_constructor:
                    result.return_flows.extend(
                        ReturnFlow(return_node, call)
                        for return_node in returns_by_entry.get(entry, [])
                    )

    result.free_variable_flows.extend(_free_variable_flows(cfg, owner))
    return result


def _argument_flows(
    call: CallRef, site: CallSite, entry: int, info: FunctionInfo
) -> Iterator[ArgumentFlow]:
    """Bind a call's arguments to a function's parameters, as Python does,
    over-approximating where it cannot tell."""
    parameters = info.parameters
    offset = 0
    if info.binds_receiver and (site.receiver is not None or info.is_constructor):
        offset = 1
        if site.receiver is not None and not info.is_constructor:
            yield ArgumentFlow(call, RECEIVER, entry, parameters[0].name)

    positional = [p for p in parameters[offset:] if p.kind == "positional"]
    var_positional = next((p for p in parameters if p.kind == "var_positional"), None)
    var_keyword = next((p for p in parameters if p.kind == "var_keyword"), None)
    named = {p.name for p in parameters if p.kind in ("positional", "keyword_only")}
    bound: Set[str] = set()

    def flow(argument: int, parameter: str) -> ArgumentFlow:
        bound.add(parameter)
        return ArgumentFlow(call, argument, entry, parameter)

    position = 0
    after_star = False
    for index, argument in enumerate(site.arguments):
        if argument.kind == "positional":
            if after_star:
                for parameter in positional:
                    yield flow(index, parameter.name)
                if var_positional is not None:
                    yield flow(index, var_positional.name)
            elif position < len(positional):
                yield flow(index, positional[position].name)
            elif var_positional is not None:
                yield flow(index, var_positional.name)
            position += 1
        elif argument.kind == "keyword":
            if argument.keyword in named:
                yield flow(index, argument.keyword or "")
            elif var_keyword is not None:
                yield flow(index, var_keyword.name)
        elif argument.kind == "star":
            for parameter in positional[position:]:
                yield flow(index, parameter.name)
            if var_positional is not None:
                yield flow(index, var_positional.name)
            after_star = True
        elif argument.kind == "double_star":
            for parameter in sorted(named - bound):
                yield flow(index, parameter)
            if var_keyword is not None:
                yield flow(index, var_keyword.name)


Scope = Tuple[Optional[int], str]


def _scope_of(
    variable: str, entry: int, infos: Dict[int, FunctionInfo]
) -> Optional[Scope]:
    """The scope a name used or defined in a function refers to, as (the ENTRY node
    of the function that owns it, kind), with owner None for the global scope.
    None if the function's scopes are not modeled (Java)."""
    info = infos[entry]
    if info.kind == "module":
        return (None, "global")
    if info.locals is None:
        return None
    if variable in info.globals:
        return (None, "global")
    if variable in info.locals:
        return (entry, "closure")
    current = info.parent
    while current is not None:
        scope = infos.get(current)
        if scope is None or scope.locals is None:
            break
        if variable in scope.globals:
            return (None, "global")
        if variable in scope.locals:
            return (current, "closure")
        current = scope.parent
    return (None, "global")


def _free_variable_flows(cfg: CFG, owner: Dict[int, int]) -> List[FreeVariableFlow]:
    infos: Dict[int, FunctionInfo] = {}
    for entry in cfg.entry_node_ids:
        info = cfg.nodes[entry].metadata.function
        if info is not None:
            infos[entry] = info

    definitions: Dict[Tuple[Scope, str], List[int]] = {}
    uses: Dict[Tuple[Scope, str], List[int]] = {}
    for node_id, node in cfg.nodes.items():
        entry = owner.get(node_id)
        if entry is None or entry not in infos:
            continue
        for variable in node.metadata.variable_definitions:
            scope = _scope_of(variable, entry, infos)
            if scope is not None:
                definitions.setdefault((scope, variable), []).append(node_id)
        for variable in node.metadata.variable_uses:
            scope = _scope_of(variable, entry, infos)
            if scope is not None:
                uses.setdefault((scope, variable), []).append(node_id)

    flows: List[FreeVariableFlow] = []
    for (scope, variable), definition_nodes in definitions.items():
        for use_node in uses.get((scope, variable), []):
            for definition_node in definition_nodes:
                if owner[definition_node] != owner[use_node]:
                    kind = "global" if scope[0] is None else "closure"
                    flows.append(
                        FreeVariableFlow(variable, definition_node, use_node, kind)
                    )
    return flows
