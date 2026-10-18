"""Helpers shared by the language visitors that build `CallSite`s."""

from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Dict, FrozenSet, Iterator, List, Optional, Tuple, Union

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


class Occurrences:
    """The uses, definitions and calls under a node, from one walk of its subtree.

    `use_of` and `definition_of` name the variable a node uses or defines, or
    return None; they may look at the node's ancestors but not at the walk's
    root, so the occurrences under any node inside the subtree are a slice of the
    walk's. Each use remembers the nearest call around it, which tells whether
    it is outside every call of a smaller subtree.
    """

    def __init__(
        self,
        root: Node,
        use_of: Callable[[Node], Optional[str]],
        definition_of: Callable[[Node], Optional[str]],
        calls: FrozenSet[str],
        use_types: FrozenSet[str],
        definition_types: FrozenSet[str],
    ) -> None:
        """`use_of` is only asked about nodes of `use_types`, `definition_of`
        about nodes of `definition_types`."""
        self.calls: List[Node] = []
        self.definitions: List[str] = []
        self._spans: Dict[int, Tuple[int, int]] = {}
        self._use_at: List[int] = []
        self._use_name: List[str] = []
        self._use_call: List[int] = []

        index = 0
        stack: List[Union[Tuple[Node, int], Node]] = [(root, -1)]
        while stack:
            item = stack.pop()
            if not isinstance(item, tuple):
                self._spans[item.id] = (self._spans[item.id][0], index)
                continue
            node, call = item
            kind = node.type
            if kind in use_types:
                used = use_of(node)
                if used is not None:
                    self._use_at.append(index)
                    self._use_name.append(used)
                    self._use_call.append(call)
            if kind in definition_types:
                defined = definition_of(node)
                if defined is not None:
                    self.definitions.append(defined)
            if kind in calls:
                self.calls.append(node)
                call = index
            self._spans[node.id] = (index, index + 1)
            index += 1
            children = node.children
            if children:
                stack.append(node)
                stack.extend((child, call) for child in reversed(children))

    def _range(self, node: Node) -> Tuple[int, int, int]:
        start, end = self._spans[node.id]
        return start, bisect_left(self._use_at, start), bisect_left(self._use_at, end)

    def uses(self, node: Node) -> List[str]:
        """Every use under `node`, in source order, repeats included."""
        _, first, last = self._range(node)
        return self._use_name[first:last]

    def direct_uses(self, node: Node) -> List[str]:
        """The uses under `node` outside every call in it (`node` included),
        de-duplicated, in the order the names are first used anywhere under it."""
        start, first, last = self._range(node)
        names = self._use_name[first:last]
        outside = Counter(
            name
            for name, call in zip(names, self._use_call[first:last])
            if call < start
        )
        return [name for name in dict.fromkeys(names) if outside[name] > 0]
