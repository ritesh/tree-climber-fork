"""
Call sites for Python AST subtrees.

Which calls run when a node executes is decided here, once, for everything built on
it (`get_calls`, `get_call_sites`): a function's body does not run when it is
defined, so it is skipped, but its decorators, default values, and annotations are
evaluated then, so they count. A class body does run at definition time, so it
counts, minus its methods' bodies. Lambda bodies count, since they usually run
during the statement that creates them (`sorted(xs, key=lambda x: f(x))`).
"""

from typing import Dict, Iterator, List, Optional, Tuple

from tree_sitter import Node

from tree_climber.ast_utils import get_source_text
from tree_climber.cfg.call_sites import CallRegions, link_call_flows, with_span
from tree_climber.cfg.cfg_types import CallArgument, CallSite
from tree_climber.cfg.languages.python_bindings import collect_uses, target_names

FLOW_BOUNDARIES = frozenset({"lambda"})


def call_nodes(ast_node: Node) -> Iterator[Node]:
    """The `call` nodes that run when the node executes, in source order (an outer
    call comes before the calls inside it)."""
    stack = [ast_node]
    while stack:
        node = stack.pop()
        if node.type == "call":
            yield node
        children = node.children
        if node.type == "function_definition":
            body = node.child_by_field_name("body")
            if body is not None:
                children = [child for child in children if child.id != body.id]
        stack.extend(reversed(children))


def callee_name(call: Node) -> Optional[str]:
    """`foo()` is `foo`; `obj.method()` and `pkg.fn()` are the final attribute
    name. Other callees, such as `f()()`, have no name."""
    function = call.child_by_field_name("function")
    if function is None:
        return None
    if function.type == "identifier":
        return get_source_text(function)
    if function.type == "attribute":
        attribute = function.child_by_field_name("attribute")
        return get_source_text(attribute) if attribute else None
    return None


def _argument_nodes(call: Node) -> List[Node]:
    arguments = call.child_by_field_name("arguments")
    if arguments is None:
        return []
    if arguments.type != "argument_list":
        return [arguments]  # f(x for x in xs): the generator is the argument
    return [child for child in arguments.named_children if child.type != "comment"]


def _receiver(call: Node) -> Optional[Node]:
    function = call.child_by_field_name("function")
    if function is not None and function.type == "attribute":
        return function.child_by_field_name("object")
    return None


def _regions(call: Node) -> CallRegions:
    return CallRegions(arguments=_argument_nodes(call), receiver=_receiver(call))


def _argument(node: Node, cache: Dict[int, List[str]]) -> CallArgument:
    def uses_of(expression: Node) -> List[str]:
        uses = collect_uses(expression, cache)
        cache[expression.id] = uses
        return uses

    if node.type == "keyword_argument":
        name = node.child_by_field_name("name")
        value = node.child_by_field_name("value")
        if name is not None and value is not None:
            return CallArgument(
                text=get_source_text(value),
                uses=uses_of(value),
                keyword=get_source_text(name),
                kind="keyword",
            )
    if node.type in ("list_splat", "dictionary_splat") and node.named_children:
        inner = node.named_children[0]
        return CallArgument(
            text=get_source_text(inner),
            uses=uses_of(inner),
            kind="star" if node.type == "list_splat" else "double_star",
        )
    return CallArgument(text=get_source_text(node), uses=uses_of(node))


def assigned_names(call: Node) -> List[str]:
    """Variables that receive the call's result when the call is the whole
    right-hand side: `x = f()`, `a, b = f()`, `x = y = f()`, `x += f()`,
    `with f() as h`, `(x := f())`, through parentheses and `await`."""
    groups: List[List[str]] = []
    node = call
    while node.parent is not None:
        parent = node.parent
        if parent.type in ("parenthesized_expression", "await"):
            pass
        elif parent.type in ("assignment", "augmented_assignment"):
            right = parent.child_by_field_name("right")
            left = parent.child_by_field_name("left")
            if right is None or right.id != node.id or left is None:
                break
            groups.append(target_names(left))
        elif parent.type == "named_expression":
            value = parent.child_by_field_name("value")
            name = parent.child_by_field_name("name")
            if value is None or value.id != node.id or name is None:
                break
            groups.append([get_source_text(name)])
        elif parent.type == "as_pattern" and (
            parent.parent is not None and parent.parent.type == "with_item"
        ):
            alias = parent.child_by_field_name("alias")
            if alias is not None and parent.named_children[0].id == node.id:
                groups.append(target_names(alias))
            break
        else:
            break
        node = parent
    names: List[str] = []
    for group in reversed(groups):
        names.extend(name for name in group if name not in names)
    return names


def call_sites(ast_node: Node) -> List[CallSite]:
    """One site per call that runs when the node executes, in source order.

    Each argument's uses are computed from the inside out (innermost call first),
    reusing the uses of nested calls, so a deeply nested `f(f(f(...)))` costs
    linear time, not quadratic.
    """
    calls = list(call_nodes(ast_node))
    cache: Dict[int, List[str]] = {}
    arguments: Dict[int, List[CallArgument]] = {}
    for call in reversed(calls):
        arguments[call.id] = [_argument(a, cache) for a in _argument_nodes(call)]

    pairs: List[Tuple[CallSite, Node]] = []
    for call in calls:
        function = call.child_by_field_name("function")
        receiver = _receiver(call)
        site = CallSite(
            callee=callee_name(call),
            callee_text=get_source_text(function) if function else "",
            receiver=get_source_text(receiver) if receiver else None,
            arguments=arguments[call.id],
            assigned_to=assigned_names(call),
        )
        pairs.append((with_span(site, call), call))
    link_call_flows(pairs, _regions, FLOW_BOUNDARIES)
    return [site for site, _ in pairs]


def decorator_call_sites(definition: Node) -> List[CallSite]:
    """Sites for decorators that are not calls themselves: `@cache` and
    `@functools.cache` call `cache` with the decorated function as the one,
    implicit, argument (`@route("/x")` is a call node, found by `call_nodes`)."""
    sites: List[CallSite] = []
    for decorator in definition.children:
        if decorator.type != "decorator" or not decorator.named_children:
            continue
        expression = decorator.named_children[0]
        if expression.type == "identifier":
            site = CallSite(
                callee=get_source_text(expression),
                callee_text=get_source_text(expression),
            )
        elif expression.type == "attribute":
            attribute = expression.child_by_field_name("attribute")
            owner = expression.child_by_field_name("object")
            if attribute is None:
                continue
            site = CallSite(
                callee=get_source_text(attribute),
                callee_text=get_source_text(expression),
                receiver=get_source_text(owner) if owner else None,
            )
        else:
            continue
        sites.append(with_span(site, expression))
    return sites
