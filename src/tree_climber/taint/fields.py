"""Which first-level fields and constant keys a statement reads and writes.

A tag is `.name` for a field and `[key]` for a constant subscript; reading or
writing through a key that is not a literal has no tag, and calling a method
reads its object whole. Field accesses are
Python `attribute` / `subscript`, C `field_expression` / `subscript_expression`
and Java `field_access` / `array_access`.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Set, Tuple

from tree_sitter import Node

from tree_climber.ast_utils import get_source_text
from tree_climber.cfg.call_sites import preorder

ACCESSES: Dict[str, Tuple[str, str]] = {
    "attribute": ("object", "attribute"),
    "subscript": ("value", "subscript"),
    "field_expression": ("argument", "field"),
    "subscript_expression": ("argument", "index"),
    "field_access": ("object", "field"),
    "array_access": ("array", "index"),
}
FIELDS = frozenset({"attribute", "field_expression", "field_access"})
STRINGS = frozenset({"string", "string_literal", "char_literal", "character_literal"})
NUMBERS = frozenset(
    {"integer", "number_literal", "decimal_integer_literal", "true", "false", "none"}
)
ASSIGNMENTS = frozenset({"assignment", "augmented_assignment", "assignment_expression"})
GROUPS = frozenset(
    {
        "pattern_list",
        "tuple_pattern",
        "list_pattern",
        "tuple",
        "list",
        "parenthesized_expression",
    }
)


@dataclass
class Accesses:
    """`reads[v]`: the tags read on `v`, None for a read of the whole value.
    `writes[v]`: the tag written on `v` (None when the key is not constant);
    only writes into a field or element are recorded."""

    reads: Dict[str, Set[Optional[str]]] = field(default_factory=dict)
    writes: Dict[str, Optional[str]] = field(default_factory=dict)


def _key(node: Optional[Node]) -> Optional[str]:
    if node is None:
        return None
    text = get_source_text(node)
    if node.type in STRINGS:
        return text.lstrip("rbuRBUfF")[1:-1] if len(text) >= 2 else None
    if node.type in NUMBERS:
        return text
    return None


def _tag(access: Node) -> Optional[str]:
    _, member = ACCESSES[access.type]
    child = access.child_by_field_name(member)
    if access.type in FIELDS:
        return f".{get_source_text(child)}" if child is not None else None
    key = _key(child)
    return f"[{key}]" if key is not None else None


def _is_callee(access: Node) -> bool:
    """`obj.method` in `obj.method()`: the object is passed whole."""
    call = access.parent
    if call is None or call.type not in ("call", "call_expression"):
        return False
    function = call.child_by_field_name("function")
    return function is not None and function.id == access.id


def _assignment_target(node: Node) -> Optional[Node]:
    """The assignment whose left side `node` is, through tuples and parentheses."""
    current = node
    parent = current.parent
    while parent is not None and parent.type in GROUPS:
        current, parent = parent, parent.parent
    if parent is not None and parent.type in ASSIGNMENTS:
        left = parent.child_by_field_name("left")
        if left is not None and left.id == current.id:
            return parent
    return None


def _compound(assignment: Node) -> bool:
    operator = assignment.child_by_field_name("operator")
    return assignment.type == "augmented_assignment" or (
        operator is not None and get_source_text(operator) != "="
    )


def accesses(ast_node: Node) -> Accesses:
    result = Accesses()
    for node in preorder(ast_node):
        if node.type != "identifier":
            continue
        parent = node.parent
        name = get_source_text(node)
        tag: Optional[str] = None
        occurrence = node
        if parent is not None and parent.type in ACCESSES:
            container, member = ACCESSES[parent.type]
            member_node = parent.child_by_field_name(member)
            if member_node is not None and member_node.id == node.id:
                if parent.type in FIELDS:
                    continue
            container_node = parent.child_by_field_name(container)
            if (
                container_node is not None
                and container_node.id == node.id
                and not _is_callee(parent)
            ):
                tag = _tag(parent)
                occurrence = parent
        outermost = occurrence
        while outermost.parent is not None and outermost.parent.type in ACCESSES:
            container, _ = ACCESSES[outermost.parent.type]
            inner = outermost.parent.child_by_field_name(container)
            if inner is None or inner.id != outermost.id:
                break
            outermost = outermost.parent
        assignment = _assignment_target(outermost)
        if assignment is not None and occurrence is not node:
            result.writes[name] = tag
            if not _compound(assignment):
                continue
        elif assignment is not None and not _compound(assignment):
            continue
        result.reads.setdefault(name, set()).add(tag)
    return result
