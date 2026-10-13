from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set, Tuple

from tree_sitter import Node


class NodeType(Enum):
    """Types of CFG nodes"""

    ENTRY = auto()
    EXIT = auto()
    STATEMENT = auto()
    CONDITION = auto()
    LOOP_HEADER = auto()
    BREAK = auto()
    CONTINUE = auto()
    RETURN = auto()
    SWITCH_HEAD = auto()
    CASE = auto()
    DEFAULT = auto()
    LABEL = auto()
    GOTO = auto()


@dataclass
class CallArgument:
    """One argument of a call.

    `kind` is "positional", "keyword" (`key=value`, with `keyword` set), "star"
    (`*args`) or "double_star" (`**kwargs`); the last two are Python only.
    """

    text: str
    uses: List[str] = field(default_factory=list)
    keyword: Optional[str] = None
    kind: str = "positional"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "uses": self.uses,
            "keyword": self.keyword,
            "kind": self.kind,
        }


@dataclass
class CallFlow:
    """Where a call's result goes when it is part of another call.

    `call` is an index into the same node's `call_sites`. `role` is "argument"
    (with `position` the argument's index), "receiver" (`a.b(c).d()`: `b(c)`
    feeds `d` as its receiver) or "callee" (`f()()`).
    """

    call: int
    role: str
    position: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"call": self.call, "role": self.role, "position": self.position}


@dataclass
class CallSite:
    """One call expression: what was called, with what, and where the result goes.

    `callee` is the name used to link the call to a function definition, or None
    when the callee has no name we can use (`(*fp)(x)`, `f()()`, `s->cb(x)`);
    `callee_text` is always the whole callee expression (`os.system`). `receiver`
    is the text of the object in `obj.f()`. `assigned_to` lists the variables that
    receive the result when the call is the whole right-hand side of an
    assignment; `feeds` links a call nested in another call. The span is the
    whole call expression.
    """

    callee: Optional[str]
    callee_text: str
    receiver: Optional[str] = None
    arguments: List[CallArgument] = field(default_factory=list)
    assigned_to: List[str] = field(default_factory=list)
    feeds: Optional[CallFlow] = None
    start_byte: int = 0
    end_byte: int = 0
    start_point: Tuple[int, int] = (0, 0)
    end_point: Tuple[int, int] = (0, 0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "callee": self.callee,
            "callee_text": self.callee_text,
            "receiver": self.receiver,
            "arguments": [argument.to_dict() for argument in self.arguments],
            "assigned_to": self.assigned_to,
            "feeds": self.feeds.to_dict() if self.feeds else None,
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "start_point": list(self.start_point),
            "end_point": list(self.end_point),
        }


@dataclass
class ParameterInfo:
    """One parameter of a function.

    `kind` is "positional", "keyword_only" (after `*` in Python), "var_positional"
    (`*args`) or "var_keyword" (`**kwargs`).
    """

    name: str
    kind: str = "positional"
    has_default: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "has_default": self.has_default,
        }


@dataclass
class FunctionInfo:
    """What the interprocedural analysis needs to know about a function, kept on
    its ENTRY node.

    `call_name` is the name calls reach it by (`__init__` is registered under its
    class). `binds_receiver` is true for a Python instance method, whose first
    parameter receives the object in `obj.method(...)`. `parent` is the ENTRY node
    of the lexically enclosing function (class bodies are not scopes), or of the
    `<module>` flow. `locals`, `globals` and `nonlocals` are the names the function
    binds itself and the names it declares `global` / `nonlocal`; `locals` is None
    for a language whose free variables are not modeled.
    """

    call_name: str
    parameters: List[ParameterInfo] = field(default_factory=list)
    kind: str = "function"
    binds_receiver: bool = False
    is_constructor: bool = False
    parent: Optional[int] = None
    locals: Optional[List[str]] = None
    globals: List[str] = field(default_factory=list)
    nonlocals: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_name": self.call_name,
            "parameters": [p.to_dict() for p in self.parameters],
            "kind": self.kind,
            "binds_receiver": self.binds_receiver,
            "is_constructor": self.is_constructor,
            "parent": self.parent,
            "locals": self.locals,
            "globals": self.globals,
            "nonlocals": self.nonlocals,
        }


@dataclass
class CFGNodeMetadata:
    """Metadata for a CFG node, used for debugging and analysis

    `function_calls` holds the names of the calls that have one, in the same order
    as `call_sites`, which describes every call. `function` is set on ENTRY nodes.
    """

    function_calls: List[str] = field(default_factory=list)
    variable_definitions: List[str] = field(default_factory=list)
    variable_uses: List[str] = field(default_factory=list)
    call_sites: List[CallSite] = field(default_factory=list)
    function: Optional[FunctionInfo] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary for JSON serialization"""
        return {
            "function_calls": self.function_calls,
            "variable_definitions": self.variable_definitions,
            "variable_uses": self.variable_uses,
            "call_sites": [site.to_dict() for site in self.call_sites],
            "function": self.function.to_dict() if self.function else None,
        }


@dataclass
class CFGNode:
    """Represents a node in the Control Flow Graph"""

    id: int
    node_type: NodeType
    ast_node: Optional[Node] = None
    source_text: str = ""
    successors: Set[int] = field(default_factory=set)
    predecessors: Set[int] = field(default_factory=set)
    edge_labels: Dict[int, str] = field(default_factory=dict)
    metadata: CFGNodeMetadata = field(default_factory=CFGNodeMetadata)

    def add_successor(self, node_id: int, label: Optional[str] = None):
        """Add a successor node with an optional label"""
        self.successors.add(node_id)
        if label is not None:
            self.edge_labels[node_id] = label

    def add_predecessor(self, node_id: int):
        """Add a predecessor node"""
        self.predecessors.add(node_id)

    def get_edge_label(self, successor_id: int) -> Optional[str]:
        """Get the label for an edge to a successor, if it exists"""
        return self.edge_labels.get(successor_id)

    def to_dict(self) -> Dict[str, Any]:
        """Convert CFG node to dictionary for JSON serialization"""
        return {
            "id": self.id,
            "node_type": self.node_type.name,
            "source_text": self.source_text,
            "start_index": self.ast_node.start_byte if self.ast_node else None,
            "end_index": self.ast_node.end_byte if self.ast_node else None,
            "successors": list(self.successors),
            "predecessors": list(self.predecessors),
            "edge_labels": self.edge_labels,
            "metadata": self.metadata.to_dict(),
        }


@dataclass
class CFGTraversalResult:
    """Represents the result of traversing a CFG node or subtree"""

    entry_node_id: int  # ID of the entry node of the traversed subtree
    exit_node_ids: List[int]  # IDs of the exit nodes of the traversed subtree
