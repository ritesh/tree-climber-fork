"""Helpers shared by the language visitors that build `CallSite`s."""

from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Dict, FrozenSet, Iterator, List, Optional, Tuple

from tree_sitter import Node

from tree_climber.cfg.cfg_types import CallFlow, CallSite


@dataclass
class CallRegions:
    """The parts of a call expression that other calls can sit in."""

    arguments: List[Node] = field(default_factory=list)
    receiver: Optional[Node] = None


def preorder(node: Node) -> Iterator[Node]:
    """Every node under `node`, itself first, parents before children, in source order."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def with_span(site: CallSite, node: Node) -> CallSite:
    site.start_byte = node.start_byte
    site.end_byte = node.end_byte
    site.start_point = (node.start_point[0], node.start_point[1])
    site.end_point = (node.end_point[0], node.end_point[1])
    return site


def _contains(outer: Node, inner: Node) -> bool:
    return outer.start_byte <= inner.start_byte and inner.end_byte <= outer.end_byte


def link_call_flows(
    calls: List[Tuple[CallSite, Node]],
    regions: Callable[[Node], CallRegions],
    boundaries: FrozenSet[str],
) -> None:
    """Fill `feeds` for calls nested in other calls of the same list.

    A call feeds the nearest enclosing call it sits inside: as an argument when
    it is anywhere within an argument expression, as the receiver when it is
    within the object being called on, otherwise as the callee. The link stops at
    a node type in `boundaries` (a lambda: its result, not the nested call's, is
    what the argument receives).
    """
    index: Dict[int, int] = {node.id: i for i, (_, node) in enumerate(calls)}
    for site, node in calls:
        parent = node.parent
        while parent is not None:
            if parent.type in boundaries:
                break
            enclosing = index.get(parent.id)
            if enclosing is not None:
                site.feeds = _flow(node, enclosing, regions(parent))
                break
            parent = parent.parent


def _flow(node: Node, enclosing: int, regions: CallRegions) -> CallFlow:
    for position, argument in enumerate(regions.arguments):
        if _contains(argument, node):
            return CallFlow(call=enclosing, role="argument", position=position)
    if regions.receiver is not None and _contains(regions.receiver, node):
        return CallFlow(call=enclosing, role="receiver")
    return CallFlow(call=enclosing, role="callee")


def outermost(node: Node, types: FrozenSet[str]) -> Iterator[Node]:
    """The nodes of the given types under `node` (itself included) that are not
    inside another one."""
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type in types:
            yield current
        else:
            stack.extend(reversed(current.children))


def uses_outside_calls(
    node: Node, uses: Callable[[Node], List[str]], calls: FrozenSet[str]
) -> List[str]:
    """The uses under `node` that are not inside a call, for a `uses` function
    that lists every occurrence: all the uses, minus those of the outermost
    calls."""
    names = uses(node)
    counts = Counter(names)
    for call in outermost(node, calls):
        counts.subtract(uses(call))
    return [name for name in dict.fromkeys(names) if counts[name] > 0]
