"""
Control Flow Graph (CFG) generator for Python using py-tree-sitter.

Covers straight-line code, function definitions, structured control flow
(`if`/`elif`/`else`, `while`, `for`, loop `else`, `break`, `continue`, `match`),
exceptions (`try`/`except`/`else`/`finally`, `raise`, `with`), and definitions
(nested functions, classes and their methods, decorators). Every function, at any
depth, and every method is its own ENTRY/EXIT subgraph; where it is defined, the
enclosing flow gets one statement that binds the name and runs decorators, default
values and annotations. Lambdas stay inside their statement. Statements without
a dedicated handler become a single STATEMENT node, so unsupported constructs
never invent control flow; later work replaces them construct by construct.

Exception edges, labeled `exception`, leave from the state *before* a statement
(the predecessors of each statement that may raise), because the raising
statement never completes. A `finally` block, or the `__exit__` node of a `with`,
is shared: normal flow, exceptions, `return`, `break`, and `continue` all pass
through it and continue to their own targets.
"""

from dataclasses import dataclass, field
from contextlib import contextmanager
from typing import Iterable, Iterator, List, Optional, Set, Tuple

from tree_sitter import Node

from tree_climber.ast_utils import (
    get_required_child_by_field_name,
    get_source_text,
)
from tree_climber.cfg.cfg_types import CFGTraversalResult, NodeType
from tree_climber.cfg.languages.python_bindings import (
    collect_bindings,
    collect_for_header_bindings,
    collect_pattern_bindings,
    is_irrefutable_pattern,
    parameter_names,
)
from tree_climber.cfg.visitor import CFGVisitor


NON_RAISING_STATEMENTS = frozenset(
    {"pass_statement", "global_statement", "nonlocal_statement"}
)


@dataclass
class _Region:
    """Nodes and explicit raise sources that share one exception target."""

    nodes: List[int] = field(default_factory=list)
    raisers: List[Tuple[int, str]] = field(default_factory=list)


@dataclass
class _Finally:
    """A `finally` block, or a `with` exit, that jumps and exceptions pass through."""

    entry_id: int
    function_depth: int
    loop_depth: int
    pending: List[Tuple[int, str]] = field(default_factory=list)
    reached_by_exception: bool = False


class PythonCFGVisitor(CFGVisitor):
    """Python-specific CFG visitor implementation"""

    MODULE_NAME = "<module>"

    def __init__(self) -> None:
        super().__init__()
        self._regions: List[_Region] = []
        self._finallys: List[_Finally] = []
        self._cannot_raise: Set[int] = set()

    def create_node(self, *args, **kwargs) -> int:
        node_id = super().create_node(*args, **kwargs)
        if self._regions:
            self._regions[-1].nodes.append(node_id)
        return node_id

    # AST utilities
    @staticmethod
    def _callee_name(call: Node) -> Optional[str]:
        function = call.child_by_field_name("function")
        if function is None:
            return None
        if function.type == "identifier":
            return get_source_text(function)
        if function.type == "attribute":
            attribute = function.child_by_field_name("attribute")
            return get_source_text(attribute) if attribute else None
        return None

    def get_calls(self, ast_node: Node) -> List[str]:
        """Extract called function names under an AST node.

        `foo()` records `foo`; `obj.method()` and `pkg.fn()` record the final
        attribute name. Other callees, such as `f()()`, record nothing for the
        outer call.

        Only calls that run when the node executes are counted. A function's
        body does not run when it is defined, so it is skipped; its decorators,
        default values, and annotations are evaluated then, so they count. A
        class body does run at definition time, so it counts, minus its methods'
        bodies. Lambda bodies count, since they usually run during the
        statement that creates them (`sorted(xs, key=lambda x: f(x))`).
        """
        calls: List[str] = []
        stack = [ast_node]
        while stack:
            node = stack.pop()
            if node.type == "call":
                name = self._callee_name(node)
                if name is not None:
                    calls.append(name)
            children = node.children
            if node.type == "function_definition":
                body = node.child_by_field_name("body")
                if body is not None:
                    children = [child for child in children if child.id != body.id]
            stack.extend(reversed(children))
        return calls

    def get_definitions(self, ast_node: Node) -> List[str]:
        """Extract variable definitions under an AST node."""
        return collect_bindings(ast_node).definitions

    def get_uses(self, ast_node: Node) -> List[str]:
        """Extract variable uses under an AST node."""
        return collect_bindings(ast_node).uses

    # Helpers
    @staticmethod
    def _named_statements(node: Node) -> List[Node]:
        return [
            child
            for child in node.children
            if child.is_named and child.type != "comment"
        ]

    def _visit_statement(self, node: Node) -> CFGTraversalResult:
        node_id = self.create_node(NodeType.STATEMENT, node, get_source_text(node))
        return CFGTraversalResult(entry_node_id=node_id, exit_node_ids=[node_id])

    def _visit_statements(
        self, statements: Iterable[Node]
    ) -> Optional[CFGTraversalResult]:
        """Visit statements in order, chaining each one's exits to the next entry."""
        first_entry = None
        current_exits: List[int] = []

        for statement in statements:
            result = self.visit(statement)
            if first_entry is None:
                first_entry = result.entry_node_id
            else:
                for exit_id in current_exits:
                    self.cfg.add_edge(exit_id, result.entry_node_id)
            current_exits = result.exit_node_ids

        if first_entry is None:
            return None
        return CFGTraversalResult(
            entry_node_id=first_entry, exit_node_ids=current_exits
        )

    def _may_raise(self, node_id: int) -> bool:
        node = self.cfg.nodes[node_id]
        if node_id in self._cannot_raise or node.ast_node is None:
            return False
        if node.node_type in (
            NodeType.ENTRY,
            NodeType.EXIT,
            NodeType.BREAK,
            NodeType.CONTINUE,
        ):
            return False
        return node.ast_node.type not in NON_RAISING_STATEMENTS

    def _link(self, source_id: int, target_id: int, label: Optional[str]) -> None:
        """Add an edge unless the two nodes are already connected or identical."""
        if source_id != target_id and (
            target_id not in self.cfg.nodes[source_id].successors
        ):
            self.cfg.add_edge(source_id, target_id, label)

    def _raise_from(self, source_id: int, label: str = "exception") -> None:
        """Send an exception from a node to the enclosing target.

        The target is the innermost region's, resolved when it closes, or the
        function exit when there is no enclosing region.
        """
        if self._regions:
            self._regions[-1].raisers.append((source_id, label))
        elif self.context.exit_node_ids:
            self._link(source_id, self.context.exit_node_ids[-1], label)

    def _close_region(self, region: _Region, target_id: int) -> bool:
        """Connect a region to its exception target; True if anything connects."""
        reached = bool(region.raisers)
        for source_id, label in region.raisers:
            self._link(source_id, target_id, label)
        for node_id in region.nodes:
            if not self._may_raise(node_id):
                continue
            for predecessor_id in list(self.cfg.nodes[node_id].predecessors):
                self._link(predecessor_id, target_id, "exception")
                reached = True
        return reached

    def _jump(self, source_id: int, kind: str, target_id: int) -> None:
        """Route a return/break/continue through the finally blocks it crosses."""
        function_depth = len(self.context.exit_node_ids)
        loop_depth = len(self.context.break_targets)
        crossed = [
            frame
            for frame in reversed(self._finallys)
            if frame.function_depth == function_depth
            and (kind == "return" or frame.loop_depth == loop_depth)
        ]
        if not crossed:
            self.cfg.add_edge(source_id, target_id)
            return

        self.cfg.add_edge(source_id, crossed[0].entry_id)
        for index, frame in enumerate(crossed):
            is_last = index + 1 == len(crossed)
            hop = target_id if is_last else crossed[index + 1].entry_id
            if (hop, kind) not in frame.pending:
                frame.pending.append((hop, kind))

    def _connect_finally_exits(
        self,
        frame: _Finally,
        exit_ids: List[int],
        join_id: int,
        falls_through: bool,
    ) -> None:
        for exit_id in exit_ids:
            if falls_through:
                self._link(exit_id, join_id, None)
            for hop, kind in frame.pending:
                self._link(exit_id, hop, kind)
            if frame.reached_by_exception:
                self._raise_from(exit_id, "exception")

    def _create_condition(self, condition: Node, node_type: NodeType) -> int:
        return self.create_node(node_type, condition, get_source_text(condition))

    def _visit_body(
        self,
        body: Node,
        predecessor: int,
        successor: int,
        edge_label: Optional[str] = None,
    ) -> None:
        """Visit a block, linking `predecessor` to its entry and its exits to `successor`."""
        result = self.visit(body)
        self.cfg.add_edge(predecessor, result.entry_node_id, edge_label)
        for exit_id in result.exit_node_ids:
            self.cfg.add_edge(exit_id, successor)

    def _connect_loop_exit(
        self, header_id: int, else_clause: Optional[Node], exit_id: int
    ) -> None:
        """Route the header's `false` edge to the loop `else` block, or the exit.

        Called after the loop context is popped, so a `break` or `continue` in
        the `else` block targets the enclosing loop.
        """
        if else_clause is None:
            self.cfg.add_edge(header_id, exit_id, "false")
        else:
            self._visit_body(
                get_required_child_by_field_name(else_clause, "body"),
                header_id,
                exit_id,
                "false",
            )

    @contextmanager
    def _function_scope(self) -> Iterator[None]:
        """Hide the surrounding try regions, finally frames and loops while a
        function body is built: nothing in it can raise to, jump to, or break out
        of the code that merely defines the function."""
        saved = (
            self._regions,
            self._finallys,
            self.context.break_targets,
            self.context.continue_targets,
        )
        self._regions, self._finallys = [], []
        self.context.break_targets, self.context.continue_targets = [], []
        try:
            yield
        finally:
            (
                self._regions,
                self._finallys,
                self.context.break_targets,
                self.context.continue_targets,
            ) = saved

    # Visitor methods
    def generic_visit(self, node: Node) -> CFGTraversalResult:
        """Treat any statement without a dedicated handler as one node."""
        return self._visit_statement(node)

    def visit_comment(self, node: Node) -> None:
        """Skip comment nodes entirely"""
        return None

    def visit_module(self, node: Node) -> CFGTraversalResult:
        """Visit the module.

        Functions are visited in source order as separate ENTRY/EXIT subgraphs:
        defining a function does not run its body. The remaining top-level
        statements run between a `<module>` ENTRY/EXIT pair, which exists only
        when there are such statements or the module is empty.
        """
        children = self._named_statements(node)
        has_module_flow = not children or any(
            child.type != "function_definition" for child in children
        )

        function_results: List[CFGTraversalResult] = []

        def top_level_statements() -> Iterator[Node]:
            for child in children:
                if child.type == "function_definition":
                    function_results.append(self._visit_function(child))
                else:
                    yield child

        if not has_module_flow:
            function_results = [self._visit_function(child) for child in children]
            return CFGTraversalResult(
                entry_node_id=function_results[0].entry_node_id,
                exit_node_ids=function_results[-1].exit_node_ids,
            )

        entry_id = self.create_node(NodeType.ENTRY, source_text=self.MODULE_NAME)
        exit_id = self.create_node(NodeType.EXIT, source_text=self.MODULE_NAME)
        self.cfg.entry_node_ids.append(entry_id)
        self.cfg.exit_node_ids.append(exit_id)
        self.context.push_entry(entry_id)
        self.context.push_exit(exit_id)

        body = self._visit_statements(top_level_statements())
        if body is None:
            self.cfg.add_edge(entry_id, exit_id)
        else:
            self.cfg.add_edge(entry_id, body.entry_node_id)
            for body_exit in body.exit_node_ids:
                self.cfg.add_edge(body_exit, exit_id)

        self.context.pop_entry()
        self.context.pop_exit()

        return CFGTraversalResult(entry_node_id=entry_id, exit_node_ids=[exit_id])

    def visit_function_definition(self, node: Node) -> CFGTraversalResult:
        """A `def` below module level: one statement in the enclosing flow, with
        the body built as its own subgraph."""
        return self._visit_definition(node, node)

    def visit_class_definition(self, node: Node) -> CFGTraversalResult:
        """A `class`: one statement in the enclosing flow, with a subgraph per method."""
        return self._visit_definition(node, node)

    def visit_decorated_definition(self, node: Node) -> CFGTraversalResult:
        """A decorated `def` or `class`: decorators run when it is defined."""
        definition = get_required_child_by_field_name(node, "definition")
        return self._visit_definition(node, definition)

    def _visit_definition(self, node: Node, definition: Node) -> CFGTraversalResult:
        """Build the statement that defines a function or class.

        It binds the name and runs what is evaluated at definition time:
        decorators (each is called with the new object), default values,
        annotations, base classes, and the class body (the body's own methods are
        separate subgraphs). Its text is the header only; `node` is the whole
        statement, `definition` the `def` or `class` inside it.
        """
        name_node = get_required_child_by_field_name(definition, "name")
        body = get_required_child_by_field_name(definition, "body")
        header = node.text[: body.start_byte - node.start_byte].decode().strip()
        header = header.removesuffix(":").rstrip()

        node_id = self.create_node(NodeType.STATEMENT, name_node, header)
        bindings = collect_bindings(node)
        metadata = self.cfg.nodes[node_id].metadata
        metadata.variable_definitions = bindings.definitions
        metadata.variable_uses = bindings.uses
        metadata.function_calls = self.get_calls(node) + self._decorator_calls(node)

        if definition.type == "function_definition":
            self._visit_function(definition)
        else:
            self._visit_methods(definition, get_source_text(name_node))
        return CFGTraversalResult(entry_node_id=node_id, exit_node_ids=[node_id])

    def _decorator_calls(self, node: Node) -> List[str]:
        """Names called by decorators that are not themselves calls: `@cache` and
        `@functools.cache` call `cache`. (`@route("/x")` records `route` already.)"""
        names = []
        for decorator in node.children:
            if decorator.type != "decorator":
                continue
            expression = next(iter(decorator.named_children), None)
            if expression is None:
                continue
            if expression.type == "identifier":
                names.append(get_source_text(expression))
            elif expression.type == "attribute":
                attribute = expression.child_by_field_name("attribute")
                if attribute is not None:
                    names.append(get_source_text(attribute))
        return names

    def _visit_methods(self, class_node: Node, qualifier: str) -> None:
        """Build a subgraph for each method of a class, and of classes nested in it."""
        body = class_node.child_by_field_name("body")
        if body is None:
            return
        for child in body.named_children:
            definition = child
            if child.type == "decorated_definition":
                inner = child.child_by_field_name("definition")
                if inner is None:
                    continue
                definition = inner
            if definition.type == "function_definition":
                self._visit_function(definition, qualifier)
            elif definition.type == "class_definition":
                nested_name = definition.child_by_field_name("name")
                if nested_name is not None:
                    self._visit_methods(
                        definition, f"{qualifier}.{get_source_text(nested_name)}"
                    )

    def _visit_function(
        self, node: Node, qualifier: Optional[str] = None
    ) -> CFGTraversalResult:
        """Build the ENTRY/EXIT subgraph of a function (including `async def`).

        A method is displayed as `Class.method`, but calls reach it by its plain
        name, so `self.method()` is linked to it. `__init__` is reached by the
        class name, since `Class(...)` runs it.
        """
        name_node = get_required_child_by_field_name(node, "name")
        parameters = get_required_child_by_field_name(node, "parameters")
        body_node = get_required_child_by_field_name(node, "body")
        function_name = get_source_text(name_node)
        display_name = f"{qualifier}.{function_name}" if qualifier else function_name
        call_name = function_name
        if qualifier and function_name == "__init__":
            call_name = qualifier.rsplit(".", 1)[-1]

        self.cfg.function_name = display_name

        with self._function_scope():
            entry_id = self.create_node(
                NodeType.ENTRY, ast_node=name_node, source_text=display_name
            )
            self.cfg.nodes[entry_id].metadata.variable_definitions.extend(
                parameter_names(parameters)
            )
            self.cfg.entry_node_ids.append(entry_id)
            self.context.push_entry(entry_id)
            self.context.register_function_definition(entry_id, call_name)

            exit_id = self.create_node(NodeType.EXIT, source_text=display_name)
            self.cfg.exit_node_ids.append(exit_id)
            self.context.push_exit(exit_id)

            body = self.visit(body_node)
            self.cfg.add_edge(entry_id, body.entry_node_id)
            for body_exit in body.exit_node_ids:
                self.cfg.add_edge(body_exit, exit_id)

            self.context.pop_entry()
            self.context.pop_exit()

        return CFGTraversalResult(entry_node_id=entry_id, exit_node_ids=[exit_id])

    def visit_block(self, node: Node) -> CFGTraversalResult:
        """Visit an indented block of statements"""
        result = self._visit_statements(self._named_statements(node))
        if result is not None:
            return result
        placeholder_id = self.create_node(NodeType.STATEMENT, source_text="empty block")
        return CFGTraversalResult(
            entry_node_id=placeholder_id, exit_node_ids=[placeholder_id]
        )

    def visit_return_statement(self, node: Node) -> CFGTraversalResult:
        """Visit a return statement"""
        return_id = self.create_node(NodeType.RETURN, node, get_source_text(node))

        assert self.context.exit_node_ids, "Return statement must have an exit node"
        self._jump(return_id, "return", self.context.exit_node_ids[-1])

        return CFGTraversalResult(entry_node_id=return_id, exit_node_ids=[])

    def visit_if_statement(self, node: Node) -> CFGTraversalResult:
        """Visit an if statement with its elif and else clauses"""
        condition = get_required_child_by_field_name(node, "condition")
        consequence = get_required_child_by_field_name(node, "consequence")

        cond_id = self._create_condition(condition, NodeType.CONDITION)
        join_id = self.create_node(NodeType.EXIT, source_text="EXIT: if stmt")
        self._visit_body(consequence, cond_id, join_id, "true")

        pending_cond: Optional[int] = cond_id
        for clause in node.children_by_field_name("alternative"):
            assert pending_cond is not None, "No clause can follow an else"
            if clause.type == "elif_clause":
                elif_id = self._create_condition(
                    get_required_child_by_field_name(clause, "condition"),
                    NodeType.CONDITION,
                )
                self.cfg.add_edge(pending_cond, elif_id, "false")
                self._visit_body(
                    get_required_child_by_field_name(clause, "consequence"),
                    elif_id,
                    join_id,
                    "true",
                )
                pending_cond = elif_id
            else:
                self._visit_body(
                    get_required_child_by_field_name(clause, "body"),
                    pending_cond,
                    join_id,
                    "false",
                )
                pending_cond = None

        if pending_cond is not None:
            self.cfg.add_edge(pending_cond, join_id, "false")

        return CFGTraversalResult(entry_node_id=cond_id, exit_node_ids=[join_id])

    def visit_while_statement(self, node: Node) -> CFGTraversalResult:
        """Visit a while loop with an optional else clause"""
        condition = get_required_child_by_field_name(node, "condition")
        body = get_required_child_by_field_name(node, "body")

        header_id = self._create_condition(condition, NodeType.LOOP_HEADER)
        exit_id = self.create_node(NodeType.EXIT, source_text="EXIT: while loop")

        self.context.push_loop_context(exit_id, header_id)
        self._visit_body(body, header_id, header_id, "true")
        self.context.pop_loop_context()

        self._connect_loop_exit(
            header_id, node.child_by_field_name("alternative"), exit_id
        )
        return CFGTraversalResult(entry_node_id=header_id, exit_node_ids=[exit_id])

    def visit_for_statement(self, node: Node) -> CFGTraversalResult:
        """Visit a for loop (including `async for`) with an optional else clause"""
        target = get_required_child_by_field_name(node, "left")
        iterable = get_required_child_by_field_name(node, "right")
        body = get_required_child_by_field_name(node, "body")

        is_async = any(child.type == "async" for child in node.children)
        header_text = (
            f"{'async ' if is_async else ''}for "
            f"{get_source_text(target)} in {get_source_text(iterable)}"
        )
        header_id = self.create_node(NodeType.LOOP_HEADER, iterable, header_text)
        bindings = collect_for_header_bindings(node)
        metadata = self.cfg.nodes[header_id].metadata
        metadata.variable_definitions = bindings.definitions
        metadata.variable_uses = bindings.uses

        exit_id = self.create_node(NodeType.EXIT, source_text="EXIT: for loop")

        self.context.push_loop_context(exit_id, header_id)
        self._visit_body(body, header_id, header_id, "true")
        self.context.pop_loop_context()

        self._connect_loop_exit(
            header_id, node.child_by_field_name("alternative"), exit_id
        )
        return CFGTraversalResult(entry_node_id=header_id, exit_node_ids=[exit_id])

    def visit_match_statement(self, node: Node) -> CFGTraversalResult:
        """Visit a `match` statement as a chain of case tests.

        The subject is evaluated once by a SWITCH_HEAD node. Each `case` is a
        CONDITION node holding its pattern: `true` enters the body and `false`
        tries the next case. Names a pattern captures are defined by a `capture`
        node on the `true` edge, so a failed match leaves them untouched. A guard
        is its own CONDITION node after the capture, and its `false` edge also
        tries the next case. No case falls through, and when no case is
        irrefutable the last `false` edge skips the match.
        """
        subject = get_required_child_by_field_name(node, "subject")
        body = get_required_child_by_field_name(node, "body")

        head_id = self.create_node(
            NodeType.SWITCH_HEAD, subject, f"match {get_source_text(subject)}"
        )
        join_id = self.create_node(NodeType.EXIT, source_text="EXIT: match stmt")

        pending: List[Tuple[int, Optional[str]]] = [(head_id, None)]
        for clause in body.children_by_field_name("alternative"):
            patterns = [c for c in clause.named_children if c.type == "case_pattern"]
            block = get_required_child_by_field_name(clause, "consequence")
            guard = clause.child_by_field_name("guard")

            pattern_text = clause.text[
                patterns[0].start_byte - clause.start_byte : patterns[-1].end_byte
                - clause.start_byte
            ].decode()
            case_id = self.create_node(
                NodeType.CONDITION, patterns[0], f"case {pattern_text}"
            )
            self._cannot_raise.add(case_id)
            bindings = collect_pattern_bindings(patterns)
            metadata = self.cfg.nodes[case_id].metadata
            metadata.variable_definitions = []
            metadata.variable_uses = bindings.uses
            metadata.function_calls = []
            for source_id, label in pending:
                self.cfg.add_edge(source_id, case_id, label)
            pending = []

            tail_id, tail_label = case_id, "true"
            if bindings.definitions:
                capture_id = self.create_node(
                    NodeType.STATEMENT,
                    patterns[0],
                    f"capture {', '.join(bindings.definitions)}",
                )
                self._cannot_raise.add(capture_id)
                metadata = self.cfg.nodes[capture_id].metadata
                metadata.variable_definitions = bindings.definitions
                metadata.variable_uses = []
                metadata.function_calls = []
                self.cfg.add_edge(case_id, capture_id, "true")
                tail_id, tail_label = capture_id, None

            if guard is not None:
                condition = guard.named_children[0]
                guard_id = self.create_node(
                    NodeType.CONDITION, condition, f"if {get_source_text(condition)}"
                )
                self.cfg.add_edge(tail_id, guard_id, tail_label)
                pending = [(case_id, "false"), (guard_id, "false")]
                tail_id, tail_label = guard_id, "true"
            elif not (len(patterns) == 1 and is_irrefutable_pattern(patterns[0])):
                pending = [(case_id, "false")]
            self._visit_body(block, tail_id, join_id, tail_label)

        for source_id, label in pending:
            self.cfg.add_edge(source_id, join_id, label)
        return CFGTraversalResult(entry_node_id=head_id, exit_node_ids=[join_id])

    def visit_break_statement(self, node: Node) -> CFGTraversalResult:
        """Visit a break statement; outside a loop it has no outgoing edge"""
        break_id = self.create_node(NodeType.BREAK, node, get_source_text(node))
        target = self.context.get_break_target()
        if target is not None:
            self._jump(break_id, "break", target)
        return CFGTraversalResult(entry_node_id=break_id, exit_node_ids=[])

    def visit_continue_statement(self, node: Node) -> CFGTraversalResult:
        """Visit a continue statement; outside a loop it has no outgoing edge"""
        continue_id = self.create_node(NodeType.CONTINUE, node, get_source_text(node))
        target = self.context.get_continue_target()
        if target is not None:
            self._jump(continue_id, "continue", target)
        return CFGTraversalResult(entry_node_id=continue_id, exit_node_ids=[])

    def visit_raise_statement(self, node: Node) -> CFGTraversalResult:
        """Visit a raise statement; it has no normal successor"""
        raise_id = self.create_node(NodeType.STATEMENT, node, get_source_text(node))
        self._cannot_raise.add(raise_id)
        self._raise_from(raise_id, "exception")
        return CFGTraversalResult(entry_node_id=raise_id, exit_node_ids=[])

    @staticmethod
    def _handler_parts(clause: Node) -> Tuple[Optional[Node], Node]:
        named = [c for c in clause.named_children if c.type != "comment"]
        block = next(c for c in reversed(named) if c.type == "block")
        test = next((c for c in named if c.id != block.id), None)
        return test, block

    def _visit_handlers(
        self, handlers: List[Node], frame: Optional[_Finally]
    ) -> Tuple[Optional[int], List[int]]:
        """Visit except clauses as a chain of tests: `true` enters the handler,
        `false` moves to the next test, and the last `false` propagates outward.
        A bare `except:` has no test and catches everything."""
        dispatch_entry: Optional[int] = None
        previous_header: Optional[int] = None
        exit_ids: List[int] = []

        for handler in handlers:
            test, block = self._handler_parts(handler)
            header_id: Optional[int] = None
            if test is not None:
                keyword = (
                    "except*" if handler.type == "except_group_clause" else "except"
                )
                header_id = self.create_node(
                    NodeType.CONDITION, test, f"{keyword} {get_source_text(test)}"
                )
                self._cannot_raise.add(header_id)

            body = self.visit(block)
            if header_id is not None:
                self.cfg.add_edge(header_id, body.entry_node_id, "true")
                entry_id = header_id
            else:
                entry_id = body.entry_node_id

            if previous_header is not None:
                self.cfg.add_edge(previous_header, entry_id, "false")
            elif dispatch_entry is None:
                dispatch_entry = entry_id
            exit_ids.extend(body.exit_node_ids)
            previous_header = header_id

        if previous_header is not None:
            if frame is not None:
                self._link(previous_header, frame.entry_id, "false")
                frame.reached_by_exception = True
            else:
                self._raise_from(previous_header, "false")
        return dispatch_entry, exit_ids

    def visit_try_statement(self, node: Node) -> CFGTraversalResult:
        """Visit try/except/else/finally"""
        body_node = get_required_child_by_field_name(node, "body")
        handlers = [
            child
            for child in node.children
            if child.type in ("except_clause", "except_group_clause")
        ]
        else_clause = next((c for c in node.children if c.type == "else_clause"), None)
        finally_clause = next(
            (c for c in node.children if c.type == "finally_clause"), None
        )

        entry_id = self.create_node(NodeType.ENTRY, source_text="ENTRY: try")
        join_id = self.create_node(NodeType.EXIT, source_text="EXIT: try stmt")
        frame: Optional[_Finally] = None
        if finally_clause is not None:
            frame = _Finally(
                entry_id=self.create_node(NodeType.ENTRY, source_text="ENTRY: finally"),
                function_depth=len(self.context.exit_node_ids),
                loop_depth=len(self.context.break_targets),
            )
            self._finallys.append(frame)

        body_region = _Region()
        self._regions.append(body_region)
        body = self.visit(body_node)
        self._regions.pop()
        self.cfg.add_edge(entry_id, body.entry_node_id)

        handler_region: Optional[_Region] = None
        if frame is not None:
            handler_region = _Region()
            self._regions.append(handler_region)

        dispatch_entry, handler_exits = self._visit_handlers(handlers, frame)
        normal_exits = body.exit_node_ids
        if else_clause is not None:
            else_body = self.visit(
                get_required_child_by_field_name(else_clause, "body")
            )
            for exit_id in body.exit_node_ids:
                self.cfg.add_edge(exit_id, else_body.entry_node_id)
            normal_exits = else_body.exit_node_ids

        if frame is not None:
            self._regions.pop()
            self._finallys.pop()

        body_target = dispatch_entry
        if body_target is None and frame is not None:
            body_target = frame.entry_id
        if body_target is not None:
            reached = self._close_region(body_region, body_target)
            if frame is not None and body_target == frame.entry_id:
                frame.reached_by_exception = frame.reached_by_exception or reached
        if frame is not None and handler_region is not None:
            reached = self._close_region(handler_region, frame.entry_id)
            frame.reached_by_exception = frame.reached_by_exception or reached

        after_id = frame.entry_id if frame is not None else join_id
        for exit_id in [*normal_exits, *handler_exits]:
            self.cfg.add_edge(exit_id, after_id)

        if frame is not None and finally_clause is not None:
            finally_block = next(
                c for c in finally_clause.named_children if c.type == "block"
            )
            finally_body = self.visit(finally_block)
            self.cfg.add_edge(frame.entry_id, finally_body.entry_node_id)
            self._connect_finally_exits(
                frame,
                finally_body.exit_node_ids,
                join_id,
                falls_through=bool(normal_exits or handler_exits),
            )

        return CFGTraversalResult(entry_node_id=entry_id, exit_node_ids=[join_id])

    def visit_with_statement(self, node: Node) -> CFGTraversalResult:
        """Visit with/async with as an implicit try/finally with one `__exit__` node"""
        clause = next(c for c in node.children if c.type == "with_clause")
        body_node = get_required_child_by_field_name(node, "body")

        is_async = any(child.type == "async" for child in node.children)
        header_text = f"{'async ' if is_async else ''}with {get_source_text(clause)}"
        header_id = self.create_node(NodeType.STATEMENT, clause, header_text)
        exit_id = self.create_node(NodeType.STATEMENT, source_text="__exit__")
        self._cannot_raise.add(exit_id)

        frame = _Finally(
            entry_id=exit_id,
            function_depth=len(self.context.exit_node_ids),
            loop_depth=len(self.context.break_targets),
        )
        region = _Region()
        self._finallys.append(frame)
        self._regions.append(region)
        body = self.visit(body_node)
        self._regions.pop()
        self._finallys.pop()

        self.cfg.add_edge(header_id, body.entry_node_id)
        for body_exit in body.exit_node_ids:
            self.cfg.add_edge(body_exit, exit_id)
        frame.reached_by_exception = self._close_region(region, exit_id)
        for hop, kind in frame.pending:
            self._link(exit_id, hop, kind)
        if frame.reached_by_exception:
            self._raise_from(exit_id, "exception")

        return CFGTraversalResult(entry_node_id=header_id, exit_node_ids=[exit_id])
