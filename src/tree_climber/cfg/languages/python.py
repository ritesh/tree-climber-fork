"""
Control Flow Graph (CFG) generator for Python using py-tree-sitter.

Currently covers straight-line code and function definitions. Statements without
a dedicated handler become a single STATEMENT node, so unsupported constructs
never invent control flow; later work replaces them construct by construct.
"""

from typing import Iterable, Iterator, List, Optional

from tree_sitter import Node

from tree_climber.ast_utils import (
    dfs,
    get_required_child_by_field_name,
    get_source_text,
)
from tree_climber.cfg.cfg_types import CFGTraversalResult, NodeType
from tree_climber.cfg.languages.python_bindings import (
    collect_bindings,
    parameter_names,
)
from tree_climber.cfg.visitor import CFGVisitor


class PythonCFGVisitor(CFGVisitor):
    """Python-specific CFG visitor implementation"""

    MODULE_NAME = "<module>"

    # AST utilities
    def get_calls(self, ast_node: Node) -> List[str]:
        """Extract called function names under an AST node.

        `foo()` records `foo`; `obj.method()` and `pkg.fn()` record the final
        attribute name. Other callees, such as `f()()`, record nothing for the
        outer call.
        """

        def process_call(node: Node) -> Optional[str]:
            if node.type != "call":
                return None
            function = node.child_by_field_name("function")
            if function is None:
                return None
            if function.type == "identifier":
                return get_source_text(function)
            if function.type == "attribute":
                attribute = function.child_by_field_name("attribute")
                return get_source_text(attribute) if attribute else None
            return None

        return dfs(ast_node, process_call)

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
                    function_results.append(self.visit(child))
                else:
                    yield child

        if not has_module_flow:
            function_results = [self.visit(child) for child in children]
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
        """Visit a function definition (including `async def`)"""
        name_node = get_required_child_by_field_name(node, "name")
        parameters = get_required_child_by_field_name(node, "parameters")
        body_node = get_required_child_by_field_name(node, "body")
        function_name = get_source_text(name_node)

        self.cfg.function_name = function_name

        entry_id = self.create_node(
            NodeType.ENTRY, ast_node=name_node, source_text=function_name
        )
        self.cfg.nodes[entry_id].metadata.variable_definitions.extend(
            parameter_names(parameters)
        )
        self.cfg.entry_node_ids.append(entry_id)
        self.context.push_entry(entry_id)
        self.context.register_function_definition(entry_id, function_name)

        exit_id = self.create_node(NodeType.EXIT, source_text=function_name)
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
        self.cfg.add_edge(return_id, self.context.exit_node_ids[-1])

        return CFGTraversalResult(entry_node_id=return_id, exit_node_ids=[])
