"""
Variable definitions and uses for Python AST subtrees.

Python has no declarations, so definitions come from binding constructs
(assignment, `for`/`with`/`except` targets, imports, `def`, `class`, walrus)
and uses from names read in expression position. The extractor works on any
subtree, so it can be applied to a whole statement or to part of one.

Decisions worth knowing:
- Writing to an attribute or subscript (`a.b = 1`, `a[i] = 2`) defines *and*
  uses the root name. The reaching-definitions framework only supports strong
  updates, so this keeps earlier definitions of `a` flowing through the write.
- Callees are uses: `callback(x)` depends on `callback`.
- `del x` is a use, not a kill.
- `global`/`nonlocal` declarations produce nothing.
- `def`/`class` bodies are skipped; lambda bodies are included minus the
  lambda's parameters; names bound by a comprehension are local to it.
"""

from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Optional, Tuple, Union

from tree_sitter import Node

from tree_climber.ast_utils import get_source_text
from tree_climber.cfg.cfg_types import ParameterInfo

SEQUENCE_TARGETS = frozenset(
    {
        "pattern_list",
        "tuple_pattern",
        "list_pattern",
        "tuple",
        "list",
        "expression_list",
        "parenthesized_expression",
        "list_splat_pattern",
        "list_splat",
        "as_pattern_target",
    }
)


@dataclass
class Bindings:
    definitions: List[str] = field(default_factory=list)
    uses: List[str] = field(default_factory=list)


def collect_bindings(node: Node) -> Bindings:
    """Collect de-duplicated definitions and uses under an AST node."""
    collector = _Collector()
    collector.run((node, frozenset()))
    return collector.bindings


def collect_for_header_bindings(node: Node) -> Bindings:
    """Bindings of a `for` statement's header only: the target(s) it defines and
    the iterable it uses, not the body."""
    collector = _Collector()
    left = node.child_by_field_name("left")
    if left is not None:
        collector.run(collector.target(left, frozenset()))
    right = node.child_by_field_name("right")
    if right is not None:
        collector.run((right, frozenset()))
    return collector.bindings


def collect_uses(node: Node, cache: Optional[Dict[int, List[str]]] = None) -> List[str]:
    """The uses under an AST node, same as `collect_bindings(node).uses`.

    With a `cache` of earlier results, keyed by node id, a node found in it is
    not walked again, so the uses of a nested call cost once instead of once per
    enclosing call. A cached list was computed with no enclosing scope; replaying
    it through `use` drops the names an enclosing comprehension or lambda binds,
    which is what walking the node there would do.
    """
    collector = _Collector(cache)
    collector.run((node, frozenset()))
    return collector.bindings.uses


def target_names(node: Node) -> List[str]:
    """Names an assignment-like target defines: `a`, `a, (b, *c)`, and the root
    name of `a.b` / `a[i]` (a weak update)."""
    collector = _Collector()
    collector.run(collector.target(node, frozenset()))
    return collector.bindings.definitions


def collect_pattern_bindings(patterns: Iterable[Node]) -> Bindings:
    """Bindings of the `case` patterns of one clause: the names they capture, and
    the names they read (classes and dotted value patterns such as `Color.RED`).

    A bare name captures; a dotted name is a value to compare against.
    """
    collector = _Collector()
    for pattern in patterns:
        collector.run(collector.pattern(pattern))
    return collector.bindings


def is_irrefutable_pattern(pattern: Node) -> bool:
    """True if a `case` pattern matches any subject: `_`, a capture name, a
    parenthesized one, or an `as` / `|` pattern containing one."""
    named = pattern.named_children
    match pattern.type:
        case "case_pattern":
            if not named:
                return get_source_text(pattern) == "_"
            return len(named) == 1 and is_irrefutable_pattern(named[0])
        case "dotted_name":
            return len(named) == 1
        case "tuple_pattern":
            is_group = len(named) == 1 and all(c.type != "," for c in pattern.children)
            return is_group and is_irrefutable_pattern(named[0])
        case "as_pattern":
            return any(is_irrefutable_pattern(child) for child in named[:1])
        case "union_pattern":
            return any(is_irrefutable_pattern(child) for child in named)
    return False


def parameter_infos(parameters: Node) -> List[ParameterInfo]:
    """The parameters of a `parameters` node with their kinds, in order."""
    infos: List[ParameterInfo] = []
    keyword_only = False
    for parameter in parameters.named_children:
        name = _parameter_name(parameter)
        match parameter.type:
            case "keyword_separator":
                keyword_only = True
            case "list_splat_pattern" if name:
                infos.append(ParameterInfo(name, "var_positional"))
                keyword_only = True
            case "dictionary_splat_pattern" if name:
                infos.append(ParameterInfo(name, "var_keyword"))
            case _ if name:
                has_default = parameter.type in (
                    "default_parameter",
                    "typed_default_parameter",
                )
                kind = "keyword_only" if keyword_only else "positional"
                infos.append(ParameterInfo(name, kind, has_default))
    return infos


def declared_scope_names(function: Node) -> Tuple[List[str], List[str]]:
    """The names a function declares `global` and `nonlocal` (not those of the
    functions and classes nested in it)."""
    declared: Dict[str, List[str]] = {"global_statement": [], "nonlocal_statement": []}
    body = function.child_by_field_name("body")
    stack = [body] if body is not None else []
    while stack:
        node = stack.pop()
        if node.type in declared:
            declared[node.type].extend(
                get_source_text(c)
                for c in node.named_children
                if c.type == "identifier"
            )
            continue
        if node.type in ("function_definition", "class_definition", "lambda"):
            continue
        stack.extend(reversed(node.children))
    return declared["global_statement"], declared["nonlocal_statement"]


def collect_local_names(function: Node) -> List[str]:
    """The names a function binds itself: its parameters and the names strongly
    bound in its body (assignment, `for`, `with`, `except`, import, `def`,
    `class`, walrus, `match` captures). Attribute and subscript writes read
    their root name, they do not bind it. Names declared `global` or `nonlocal`
    are not local."""
    collector = _Collector(strong_only=True)
    parameters = function.child_by_field_name("parameters")
    body = function.child_by_field_name("body")
    names = list(parameter_names(parameters)) if parameters is not None else []
    if body is not None:
        collector.run((body, frozenset()))
    names.extend(collector.bindings.definitions)
    globals_, nonlocals = declared_scope_names(function)
    excluded = set(globals_) | set(nonlocals)
    return [name for name in dict.fromkeys(names) if name not in excluded]


def parameter_names(parameters: Node) -> List[str]:
    """Names bound by a `parameters` or `lambda_parameters` node."""
    names = (_parameter_name(parameter) for parameter in parameters.named_children)
    return [name for name in names if name]


def _parameter_name(parameter: Node) -> Optional[str]:
    match parameter.type:
        case "identifier":
            return get_source_text(parameter)
        case "default_parameter" | "typed_default_parameter":
            name = parameter.child_by_field_name("name")
            return get_source_text(name) if name else None
        case "typed_parameter" | "list_splat_pattern" | "dictionary_splat_pattern":
            inner = next(
                (child for child in parameter.named_children if child.type != "type"),
                None,
            )
            return _parameter_name(inner) if inner else None
    return None


def _target_names(node: Optional[Node]) -> List[str]:
    if node is None:
        return []
    if node.type == "identifier":
        return [get_source_text(node)]
    if node.type in SEQUENCE_TARGETS:
        return [name for child in node.named_children for name in _target_names(child)]
    return []


Visit = Tuple[Node, frozenset[str]]
Task = Union[Visit, Iterator["Task"]]


class _Collector:
    """Walks a subtree and records definitions and uses.

    Expressions nest one level per operator (`a = b = c`, `x + y + z`), so a
    generated file can be thousands of levels deep. The walk therefore never
    recurses on the Python stack: a handler is a generator that yields the
    sub-walks it needs, either a node to visit or another generator, and `run`
    drives them with an explicit stack. A sub-walk finishes before its handler
    resumes, so the order of definitions and uses is the same as a recursive walk.
    """

    def __init__(
        self,
        uses_cache: Optional[Dict[int, List[str]]] = None,
        strong_only: bool = False,
    ) -> None:
        self.bindings = Bindings()
        self.uses_cache = uses_cache
        self.strong_only = strong_only

    def run(self, *tasks: Task) -> None:
        stack: List[Iterator[Task]] = [iter(tasks)]
        while stack:
            task = next(stack[-1], None)
            if task is None:
                stack.pop()
            elif isinstance(task, tuple):
                walk = self.visit(*task)
                if walk is not None:
                    stack.append(walk)
            else:
                stack.append(task)

    def define(self, name: str) -> None:
        if name not in self.bindings.definitions:
            self.bindings.definitions.append(name)

    def use(self, name: str, local: frozenset[str]) -> None:
        if name not in local and name not in self.bindings.uses:
            self.bindings.uses.append(name)

    def visit(self, node: Node, local: frozenset[str]) -> Optional[Iterator[Task]]:
        if self.uses_cache is not None:
            known = self.uses_cache.get(node.id)
            if known is not None:
                for name in known:
                    self.use(name, local)
                return None
        handler = getattr(self, f"_visit_{node.type}", None)
        if handler is not None:
            return handler(node, local)
        return self.visit_children(node, local)

    def visit_children(
        self,
        node: Node,
        local: frozenset[str],
        skip: Iterable[Optional[Node]] = (),
    ) -> Iterator[Task]:
        skipped = {child.id for child in skip if child is not None}
        for child in node.named_children:
            if child.id not in skipped:
                yield (child, local)

    def visit_field(
        self, node: Node, name: str, local: frozenset[str]
    ) -> Iterator[Task]:
        child = node.child_by_field_name(name)
        if child is not None:
            yield (child, local)

    def target(
        self, node: Node, local: frozenset[str], read: bool = False
    ) -> Iterator[Task]:
        """Handle an assignment-like target: names defined, expressions used."""
        if node.type == "identifier":
            name = get_source_text(node)
            self.define(name)
            if read:
                self.use(name, local)
        elif node.type in ("attribute", "subscript"):
            yield self.mutation_target(node, local)
        elif node.type in SEQUENCE_TARGETS:
            for child in node.named_children:
                yield self.target(child, local, read)
        else:
            yield (node, local)

    def mutation_target(self, node: Node, local: frozenset[str]) -> Iterator[Task]:
        current: Optional[Node] = node
        while current is not None and current.type in ("attribute", "subscript"):
            if current.type == "subscript":
                value = current.child_by_field_name("value")
                yield self.visit_children(current, local, skip=[value])
                current = value
            else:
                current = current.child_by_field_name("object")

        if current is None:
            return
        if current.type == "identifier":
            name = get_source_text(current)
            if not self.strong_only:
                self.define(name)
            self.use(name, local)
        else:
            yield (current, local)

    def pattern(self, node: Node) -> Iterator[Task]:
        """Handle a `case` pattern node: names captured, and names read."""
        match node.type:
            case "dotted_name":
                names = [get_source_text(child) for child in node.named_children]
                if len(names) == 1:
                    self.define(names[0])
                elif names:
                    self.use(names[0], frozenset())
            case "splat_pattern":
                for child in node.named_children:
                    if child.type == "identifier":
                        self.define(get_source_text(child))
            case "as_pattern":
                named = node.named_children
                for child in named[:-1]:
                    yield self.pattern(child)
                if len(named) > 1 and named[-1].type == "identifier":
                    self.define(get_source_text(named[-1]))
            case "class_pattern":
                named = node.named_children
                if named and named[0].type == "dotted_name":
                    root = named[0].named_children
                    if root:
                        self.use(get_source_text(root[0]), frozenset())
                for child in named[1:]:
                    yield self.pattern(child)
            case "keyword_pattern":
                for child in node.named_children[1:]:
                    yield self.pattern(child)
            case "dict_pattern":
                for key in node.children_by_field_name("key"):
                    if key.type == "dotted_name":
                        yield self.pattern(key)
                for child in node.named_children:
                    if child.type == "splat_pattern" or child.type == "case_pattern":
                        yield self.pattern(child)
            case "case_pattern" | "union_pattern" | "list_pattern" | "tuple_pattern":
                for child in node.named_children:
                    yield self.pattern(child)

    def parameter_expressions(
        self, parameters: Node, local: frozenset[str]
    ) -> Iterator[Task]:
        """Visit the expressions in parameters: defaults and annotations."""
        for parameter in parameters.named_children:
            if parameter.type in (
                "default_parameter",
                "typed_parameter",
                "typed_default_parameter",
            ):
                yield self.visit_field(parameter, "type", local)
                yield self.visit_field(parameter, "value", local)

    # Names and expressions
    def _visit_identifier(self, node: Node, local: frozenset[str]) -> None:
        parent = node.parent
        if parent is not None and parent.type in (
            "function_definition",
            "class_definition",
        ):
            name = parent.child_by_field_name("name")
            if name is not None and name.id == node.id:
                return
        self.use(get_source_text(node), local)

    def _visit_attribute(self, node: Node, local: frozenset[str]) -> Iterator[Task]:
        return self.visit_field(node, "object", local)

    def _visit_keyword_argument(
        self, node: Node, local: frozenset[str]
    ) -> Iterator[Task]:
        return self.visit_field(node, "value", local)

    def _visit_named_expression(
        self, node: Node, local: frozenset[str]
    ) -> Iterator[Task]:
        name = node.child_by_field_name("name")
        if name is not None:
            self.define(get_source_text(name))
        return self.visit_field(node, "value", local)

    # Assignments and other binding statements
    def _visit_assignment(self, node: Node, local: frozenset[str]) -> Iterator[Task]:
        left = node.child_by_field_name("left")
        has_value = node.child_by_field_name("right") is not None
        if left is not None:
            if has_value:
                yield self.target(left, local)
            elif left.type != "identifier":
                yield (left, local)
        yield self.visit_children(node, local, skip=[left])

    def _visit_augmented_assignment(
        self, node: Node, local: frozenset[str]
    ) -> Iterator[Task]:
        left = node.child_by_field_name("left")
        if left is not None:
            yield self.target(left, local, read=True)
        yield self.visit_children(node, local, skip=[left])

    def _visit_for_statement(self, node: Node, local: frozenset[str]) -> Iterator[Task]:
        left = node.child_by_field_name("left")
        if left is not None:
            yield self.target(left, local)
        yield self.visit_children(node, local, skip=[left])

    def _visit_case_clause(self, node: Node, local: frozenset[str]) -> Iterator[Task]:
        patterns = [c for c in node.named_children if c.type == "case_pattern"]
        for pattern in patterns:
            yield self.pattern(pattern)
        yield self.visit_children(node, local, skip=patterns)

    def _visit_as_pattern(self, node: Node, local: frozenset[str]) -> Iterator[Task]:
        alias = node.child_by_field_name("alias")
        if alias is not None:
            yield self.target(alias, local)
        yield self.visit_children(node, local, skip=[alias])

    def _visit_import_statement(self, node: Node, local: frozenset[str]) -> None:
        for imported in node.children_by_field_name("name"):
            if imported.type == "aliased_import":
                alias = imported.child_by_field_name("alias")
                if alias is not None:
                    self.define(get_source_text(alias))
            elif imported.named_children:
                self.define(get_source_text(imported.named_children[0]))

    _visit_import_from_statement = _visit_import_statement

    def _visit_global_statement(self, node: Node, local: frozenset[str]) -> None:
        return None

    _visit_nonlocal_statement = _visit_global_statement

    # Nested scopes
    def _visit_function_definition(
        self, node: Node, local: frozenset[str]
    ) -> Iterator[Task]:
        name = node.child_by_field_name("name")
        if name is not None:
            self.define(get_source_text(name))
        parameters = node.child_by_field_name("parameters")
        if parameters is not None:
            yield self.parameter_expressions(parameters, local)
        yield self.visit_field(node, "return_type", local)

    def _visit_class_definition(
        self, node: Node, local: frozenset[str]
    ) -> Iterator[Task]:
        name = node.child_by_field_name("name")
        if name is not None:
            self.define(get_source_text(name))
        return self.visit_field(node, "superclasses", local)

    def _visit_lambda(self, node: Node, local: frozenset[str]) -> Iterator[Task]:
        parameters = node.child_by_field_name("parameters")
        inner = local
        if parameters is not None:
            yield self.parameter_expressions(parameters, local)
            inner = local | frozenset(parameter_names(parameters))
        yield self.visit_field(node, "body", inner)

    def _visit_list_comprehension(
        self, node: Node, local: frozenset[str]
    ) -> Iterator[Task]:
        clauses = [c for c in node.named_children if c.type == "for_in_clause"]
        bound = {
            name
            for clause in clauses
            for name in _target_names(clause.child_by_field_name("left"))
        }
        inner = local | frozenset(bound)

        for child in node.named_children:
            if child.type != "for_in_clause":
                yield (child, inner)
                continue
            # Only the first iterable is evaluated in the enclosing scope
            scope = local if child.id == clauses[0].id else inner
            for right in child.children_by_field_name("right"):
                yield (right, scope)

    _visit_set_comprehension = _visit_list_comprehension
    _visit_dictionary_comprehension = _visit_list_comprehension
    _visit_generator_expression = _visit_list_comprehension
