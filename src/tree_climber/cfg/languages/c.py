"""
Control Flow Graph (CFG) Generator Framework using py-tree-sitter for C language.
This framework uses the visitor pattern with depth-first traversal to build CFGs.
"""

from typing import List, Optional, Tuple

from tree_sitter import Node

from tree_climber.ast_utils import (
    dfs,
    get_child_by_field_name,
    get_required_child_by_field_name,
    get_required_child_by_type,
    get_source_text,
)
from tree_climber.cfg.call_sites import (
    CallRegions,
    link_call_flows,
    preorder,
    with_span,
)
from tree_climber.cfg.cfg_types import (
    CallArgument,
    CallSite,
    CFGTraversalResult,
    FunctionInfo,
    NodeType,
    ParameterInfo,
)
from tree_climber.cfg.visitor import CFGVisitor


class CCFGVisitor(CFGVisitor):
    """C-specific CFG visitor implementation"""

    # Helper methods
    def _create_condition_node(self, condition_node: Node, node_type: NodeType) -> int:
        """Create a condition/header node with proper text."""
        condition_text = get_source_text(condition_node)
        return self.create_node(node_type, condition_node, condition_text)

    def _create_body_node(
        self,
        body_node: Node,
        cfg_predecessor: int,
        cfg_successor: int,
        edge_label: Optional[str] = None,
    ) -> CFGTraversalResult:
        visit_result = self.visit(body_node)

        # Connect entry to body entry
        self.cfg.add_edge(cfg_predecessor, visit_result.entry_node_id, label=edge_label)

        # Connect body exits to function exit
        for exit_node in visit_result.exit_node_ids:
            self.cfg.add_edge(exit_node, cfg_successor)
        return visit_result

    def _visit_linear_statement(self, node: Node) -> CFGTraversalResult:
        # If the node is a linear statement, create a statement node
        node_id = self.create_node(NodeType.STATEMENT, node, get_source_text(node))
        return CFGTraversalResult(entry_node_id=node_id, exit_node_ids=[node_id])

    # AST utilities
    @staticmethod
    def _argument_nodes(call: Node) -> List[Node]:
        arguments = call.child_by_field_name("arguments")
        if arguments is None:
            return []
        return [c for c in arguments.named_children if c.type != "comment"]

    @staticmethod
    def _receiver(call: Node) -> Optional[Node]:
        function = call.child_by_field_name("function")
        if function is not None and function.type == "field_expression":
            return function.child_by_field_name("argument")
        return None

    def _assigned_names(self, call: Node) -> List[str]:
        """Variables that receive the call's result when the call is the whole
        right-hand side: `T x = f();`, `x = f();`, `a = b = f();`, `x += f();`,
        through parentheses and casts."""
        names: List[str] = []
        node = call
        while node.parent is not None:
            parent = node.parent
            if parent.type in ("parenthesized_expression", "cast_expression"):
                pass
            elif parent.type == "init_declarator":
                value = parent.child_by_field_name("value")
                if value is not None and value.id == node.id:
                    name = self._declared_identifier(
                        parent.child_by_field_name("declarator")
                    )
                    if name is not None:
                        names.append(get_source_text(name))
                break
            elif parent.type == "assignment_expression":
                right = parent.child_by_field_name("right")
                if right is None or right.id != node.id:
                    break
                written = self._written_variable(parent.child_by_field_name("left"))
                if written is not None:
                    names.insert(0, written)
            else:
                break
            node = parent
        return list(dict.fromkeys(names))

    def get_call_sites(self, ast_node: Node) -> List[CallSite]:
        """Describe every call under an AST node. Only a plain `name(...)` call has
        a callee name; `(*fp)(x)` and `s->cb(x)` are sites without one."""
        pairs: List[Tuple[CallSite, Node]] = []
        for call in preorder(ast_node):
            if call.type != "call_expression":
                continue
            function = call.child_by_field_name("function")
            receiver = self._receiver(call)
            site = CallSite(
                callee=get_source_text(function)
                if function is not None and function.type == "identifier"
                else None,
                callee_text=get_source_text(function) if function else "",
                receiver=get_source_text(receiver) if receiver else None,
                arguments=[
                    CallArgument(text=get_source_text(a), uses=self.get_uses(a))
                    for a in self._argument_nodes(call)
                ],
                assigned_to=self._assigned_names(call),
            )
            pairs.append((with_span(site, call), call))
        link_call_flows(
            pairs,
            lambda call: CallRegions(
                arguments=self._argument_nodes(call), receiver=self._receiver(call)
            ),
            frozenset(),
        )
        return [site for site, _ in pairs]

    DECLARATOR_WRAPPERS = (
        "pointer_declarator",
        "array_declarator",
        "parenthesized_declarator",
        "function_declarator",
    )

    @staticmethod
    def _wrapped_declarator(wrapper: Node) -> Optional[Node]:
        """The declarator inside `*p`, `a[n]`, `f(...)`, or `(...)`.

        A parenthesized declarator has no field name for its content.
        """
        if wrapper.type == "parenthesized_declarator":
            return wrapper.named_children[0] if wrapper.named_children else None
        return wrapper.child_by_field_name("declarator")

    @classmethod
    def _declared_identifier(cls, declarator: Optional[Node]) -> Optional[Node]:
        """The name declared by a declarator, through `*p`, `a[n]`, and `(*fp)(...)`."""
        node = declarator
        while node is not None and node.type != "identifier":
            if node.type not in cls.DECLARATOR_WRAPPERS:
                return None
            node = cls._wrapped_declarator(node)
        return node

    @classmethod
    def _is_declared_name(cls, node: Node) -> bool:
        """True if an identifier is the name being declared, not a use."""
        current = node
        parent = current.parent
        while parent is not None and parent.type in cls.DECLARATOR_WRAPPERS:
            declarator = cls._wrapped_declarator(parent)
            if declarator is None or declarator.id != current.id:
                return False
            current, parent = parent, parent.parent
        if parent is None or parent.type not in (
            "init_declarator",
            "declaration",
            "parameter_declaration",
        ):
            return False
        declarator = parent.child_by_field_name("declarator")
        return declarator is not None and declarator.id == current.id

    @staticmethod
    def _written_variable(target: Optional[Node]) -> Optional[str]:
        """The variable an assignment target writes to.

        A name, `s.f`, and `a[i]` write to the root variable (the last two are
        weak updates: the variable is also used). A write through a pointer,
        `p->f` or `*p`, changes the pointee and not `p`, so it writes nothing.
        """
        node = target
        while node is not None:
            if node.type == "identifier":
                return get_source_text(node)
            if node.type == "subscript_expression" or (
                node.type == "field_expression"
                and not any(child.type == "->" for child in node.children)
            ):
                node = node.child_by_field_name("argument")
            else:
                return None
        return None

    def get_definitions(self, ast_node: Node) -> List[str]:
        """Extract variable definitions under an AST node."""

        def process_definition(node: Node) -> Optional[str]:
            if node.type == "init_declarator":
                name = self._declared_identifier(node.child_by_field_name("declarator"))
                return get_source_text(name) if name else None
            elif node.type == "assignment_expression":
                return self._written_variable(node.child_by_field_name("left"))
            elif node.type == "update_expression":
                # Handle increment/decrement operators like a++, ++a, a--, --a
                return self._written_variable(node.child_by_field_name("argument"))
            return None

        return dfs(ast_node, process_definition)

    def get_uses(self, ast_node: Node) -> List[str]:
        """Extract variable uses under an AST node."""

        def process_use(node: Node) -> Optional[str]:
            if node.type == "identifier":
                if self._is_declared_name(node):
                    return None
                # Skip identifiers in assignment left-hand side or function definition
                if node.parent:
                    # Skip identifiers in various contexts where they're not "uses"
                    if node.parent.type in [
                        "call_expression",  # Function names in calls
                        "function_definition",  # Function names in definitions
                        "parameter_declaration",  # Parameter declarations
                        "function_declarator",  # Function declarations
                    ]:
                        return None
                    if node.parent.type == "init_declarator":
                        # Only the declared name is skipped; the initializer is a use
                        if node == node.parent.child_by_field_name("declarator"):
                            return None
                    if node.parent.type == "assignment_expression":
                        is_target = node == node.parent.child_by_field_name("left")
                        is_compound = node.parent.children[1].type in (
                            "-=",
                            "+=",
                            "*=",
                            "/=",
                        )
                        if is_target and not is_compound:
                            # A plain assignment target is a definition, not a use
                            return None
                    if node.parent.type == "update_expression":
                        # Increment/decrement operations are both uses and definitions
                        return node.text.decode()
                return node.text.decode()
            return None

        return dfs(ast_node, process_use)

    def is_linear_statement(self, node: Node) -> bool:
        """Check if a node represents a simple linear statement"""
        # Control flow statements that create branches or edges
        non_linear_types = [
            "if_statement",
            "for_statement",
            "while_statement",
            "do_statement",
            "switch_statement",
            "break_statement",
            "continue_statement",
            "return_statement",
            "goto_statement",
            "compound_statement",
        ]

        # Check if node type isn't one of the non-linear types
        return node.type.endswith("_statement") and node.type not in non_linear_types

    # Visitor methods
    def visit_comment(self, node: Node) -> None:
        """Skip comment nodes entirely"""
        # Return None to indicate that this node should be ignored
        # node parameter required by visitor interface but not used
        return None

    def visit_expression_statement(self, node: Node) -> CFGTraversalResult:
        return self._visit_linear_statement(node)

    def visit_declaration(self, node: Node) -> CFGTraversalResult:
        return self._visit_linear_statement(node)

    def visit_translation_unit(self, node: Node) -> Optional[CFGTraversalResult]:
        """Visit the root translation unit node; None if it has no functions"""
        first_entry = None
        last_exits = None
        for child in node.children:
            if child.type == "function_definition":
                result = self.visit(child)
                if first_entry is None:
                    first_entry = result.entry_node_id
                last_exits = result.exit_node_ids

        if first_entry is None or last_exits is None:
            return None
        return CFGTraversalResult(
            entry_node_id=first_entry,
            exit_node_ids=last_exits,
        )

    def _declared_local_names(self, body: Node) -> List[str]:
        """Names declared in a function body, in any block: `int a, *b = p;`."""
        names: List[str] = []
        for node in preorder(body):
            if node.type != "declaration":
                continue
            for declarator in node.children_by_field_name("declarator"):
                if declarator.type == "init_declarator":
                    declarator = declarator.child_by_field_name("declarator")
                name = self._declared_identifier(declarator)
                if name is not None:
                    names.append(get_source_text(name))
        return names

    @classmethod
    def _inner_declarator(cls, node: Node) -> Optional[Node]:
        if node.type in cls.DECLARATOR_WRAPPERS:
            return cls._wrapped_declarator(node)
        if node.type == "attributed_declarator" and node.named_children:
            return node.named_children[0]
        return None

    @classmethod
    def _function_declarator(cls, declarator: Node) -> Node:
        """The declarator of the function itself, the innermost function
        declarator: `f(...)` in `int *f(...)` and in `int (*f(int x))(int)`, where
        the outer `(int)` belongs to the returned function pointer."""
        found: Optional[Node] = None
        node: Optional[Node] = declarator
        while node is not None:
            if node.type == "function_declarator":
                found = node
            node = cls._inner_declarator(node)
        if found is None:
            raise ValueError(
                f"No function declarator in {get_source_text(declarator)!r}"
            )
        return found

    @classmethod
    def _function_name(cls, function_declarator: Node) -> Node:
        """The name in a function declarator, through `(f)` and `f [[attr]]`."""
        node = function_declarator.child_by_field_name("declarator")
        while node is not None and node.type != "identifier":
            node = cls._inner_declarator(node)
        if node is None:
            raise ValueError(
                f"No function name in {get_source_text(function_declarator)!r}"
            )
        return node

    def visit_function_definition(self, node: Node) -> CFGTraversalResult:
        """Visit a function definition"""
        # Get components via named fields
        declarator = self._function_declarator(
            get_required_child_by_field_name(node, "declarator")
        )
        body_node = get_required_child_by_field_name(node, "body")

        # Extract function name and parameters from the declarator
        function_name = ""
        parameters = []
        closing_brace = None

        # Look for identifier (function name) and parameter_list in declarator
        function_name = get_source_text(self._function_name(declarator))
        parameter_list = get_required_child_by_field_name(declarator, "parameters")
        parameter_infos: List[ParameterInfo] = []
        for param in parameter_list.children:
            match param.type:
                case "parameter_declaration":
                    name = self._declared_identifier(
                        get_child_by_field_name(param, "declarator")
                    )
                    if name:
                        parameters.append(get_source_text(name))
                        parameter_infos.append(ParameterInfo(get_source_text(name)))
                case _:
                    # Skip punctuation and other non-parameter elements
                    if param.is_named and not param.type == "comment":
                        parameters.append(get_source_text(param))
                        parameter_infos.append(
                            ParameterInfo(get_source_text(param), "var_positional")
                        )

        # Find closing brace in body for exit node location
        for child in body_node.children:
            if child.type == "}":
                closing_brace = child

        self.cfg.function_name = function_name

        # Create entry node with function name and parameters
        param_info = function_name
        entry_id = self.create_node(
            NodeType.ENTRY, source_text=param_info, ast_node=declarator
        )
        metadata = self.cfg.nodes[entry_id].metadata
        metadata.variable_definitions.extend(parameters)
        metadata.function = FunctionInfo(
            call_name=function_name,
            parameters=parameter_infos,
            locals=list(
                dict.fromkeys(
                    [p.name for p in parameter_infos if p.kind == "positional"]
                    + self._declared_local_names(body_node)
                )
            ),
        )
        self.cfg.entry_node_ids.append(entry_id)
        self.context.push_entry(entry_id)
        self.context.register_function_definition(entry_id, function_name)

        # Create exit node
        exit_id = self.create_node(
            NodeType.EXIT, source_text=function_name, ast_node=closing_brace
        )
        self.cfg.exit_node_ids.append(exit_id)
        self.context.push_exit(exit_id)

        self._create_body_node(body_node, entry_id, exit_id)

        self.context.pop_entry()
        self.context.pop_exit()

        return CFGTraversalResult(entry_node_id=entry_id, exit_node_ids=[exit_id])

    def visit_compound_statement(self, node: Node) -> CFGTraversalResult:
        """Visit a compound statement (block)"""
        first_entry = None
        current_exits = []

        # Process each statement in the block
        for child in node.children:
            # Skip unnamed nodes and comments
            if not child.is_named or child.type == "comment":
                continue

            child_result = self.visit(child)

            if first_entry is None:
                # First statement becomes the entry point for the block
                first_entry = child_result.entry_node_id
            else:
                # Connect previous statement exits to this statement's entry
                for exit_node in current_exits:
                    self.cfg.add_edge(exit_node, child_result.entry_node_id)

            # Update current exits to this statement's exits
            current_exits = child_result.exit_node_ids

        # If the block is empty, create a placeholder node
        if first_entry is None:
            placeholder_id = self.create_node(
                NodeType.STATEMENT, source_text="empty block"
            )
            first_entry = placeholder_id
            current_exits = [placeholder_id]

        return CFGTraversalResult(
            entry_node_id=first_entry, exit_node_ids=current_exits
        )

    def visit_if_statement(self, node: Node) -> CFGTraversalResult:
        """Visit an if statement"""
        # Get components via named fields
        condition_node = get_required_child_by_field_name(node, "condition")
        then_stmt = get_required_child_by_field_name(node, "consequence")
        else_clause = get_child_by_field_name(node, "alternative")

        # Create condition node
        cond_id = self._create_condition_node(condition_node, NodeType.CONDITION)

        # Create an explicit exit node for the if statement
        if_exit_id = self.create_node(NodeType.EXIT, source_text="EXIT: if stmt")

        # Process then branch with "true" label
        self._create_body_node(then_stmt, cond_id, if_exit_id, edge_label="true")

        # Process else branch with "false" label
        if else_clause:
            self._create_body_node(else_clause, cond_id, if_exit_id, edge_label="false")
        else:
            # No else branch, direct false path to the exit node
            self.cfg.add_edge(cond_id, if_exit_id, "false")

        return CFGTraversalResult(entry_node_id=cond_id, exit_node_ids=[if_exit_id])

    def visit_while_statement(self, node: Node) -> CFGTraversalResult:
        """Visit a while loop"""
        # Get components via named fields
        condition_node = get_required_child_by_field_name(node, "condition")
        body_stmt = get_required_child_by_field_name(node, "body")

        # Create loop header node
        loop_header_id = self._create_condition_node(
            condition_node, NodeType.LOOP_HEADER
        )

        # Create exit node for the loop
        loop_exit_id = self.create_node(NodeType.EXIT, source_text="EXIT: while loop")

        # Set up loop context
        self.context.push_loop_context(loop_exit_id, loop_header_id)

        # Process loop body
        self._create_body_node(
            body_stmt, loop_header_id, loop_header_id, edge_label="true"
        )

        # Connect condition to exit (false branch) with "false" label
        self.cfg.add_edge(loop_header_id, loop_exit_id, "false")

        # Clean up loop context
        self.context.pop_loop_context()

        return CFGTraversalResult(
            entry_node_id=loop_header_id, exit_node_ids=[loop_exit_id]
        )

    def visit_for_statement(self, node: Node) -> CFGTraversalResult:
        """Visit a for loop"""
        # Get components via named fields
        init_expr = get_required_child_by_field_name(node, "initializer")
        condition_expr = get_required_child_by_field_name(node, "condition")
        update_expr = get_required_child_by_field_name(node, "update")
        body_stmt = get_required_child_by_field_name(node, "body")

        # Create initialization node with actual initialization code
        init_text = get_source_text(init_expr)
        init_id = self.create_node(NodeType.STATEMENT, init_expr, init_text)

        # Create condition node
        condition_text = get_source_text(condition_expr)
        condition_id = self.create_node(
            NodeType.LOOP_HEADER, condition_expr, condition_text
        )

        # Create update node with actual update code
        update_text = get_source_text(update_expr)
        update_id = self.create_node(NodeType.STATEMENT, update_expr, update_text)

        # Create exit node
        exit_id = self.create_node(NodeType.EXIT, source_text="EXIT: for loop")

        # Connect init to condition
        self.cfg.add_edge(init_id, condition_id)

        # Set up loop context
        self.context.push_loop_context(exit_id, update_id)

        # Process body
        self._create_body_node(body_stmt, condition_id, update_id, edge_label="true")

        # Connect update back to condition
        self.cfg.add_edge(update_id, condition_id)

        # Connect condition to exit (false branch) with "false" label
        self.cfg.add_edge(condition_id, exit_id, "false")

        # Clean up loop context
        self.context.pop_loop_context()

        return CFGTraversalResult(entry_node_id=init_id, exit_node_ids=[exit_id])

    def visit_break_statement(self, node: Node) -> CFGTraversalResult:
        """Visit a break statement"""
        break_id = self.create_node(NodeType.BREAK, node, get_source_text(node))

        # Connect to break target if available
        break_target = self.context.get_break_target()
        assert break_target is not None, "Break statement must have a target"
        self.cfg.add_edge(break_id, break_target)

        # The break statement terminates the current control flow.
        # No normal successors, and an empty exit node list indicates
        # that control flow doesn't continue within the current block
        return CFGTraversalResult(
            entry_node_id=break_id, exit_node_ids=[]
        )  # Break statements don't have normal successors within their context

    def visit_continue_statement(self, node: Node) -> CFGTraversalResult:
        """Visit a continue statement"""
        continue_id = self.create_node(NodeType.CONTINUE, node, get_source_text(node))

        # Connect to continue target if available
        continue_target = self.context.get_continue_target()
        assert continue_target is not None, "Continue statement must have a target"
        self.cfg.add_edge(continue_id, continue_target)

        return CFGTraversalResult(
            entry_node_id=continue_id, exit_node_ids=[]
        )  # Continue statements don't have normal successors

    def visit_return_statement(self, node: Node) -> CFGTraversalResult:
        """Visit a return statement"""
        return_id = self.create_node(NodeType.RETURN, node, get_source_text(node))

        # Connect to function exit
        assert len(self.cfg.exit_node_ids) > 0, (
            "Return statement must have an exit node"
        )
        self.cfg.add_edge(return_id, self.cfg.exit_node_ids[-1])

        return CFGTraversalResult(
            entry_node_id=return_id, exit_node_ids=[]
        )  # Return statements don't have normal successors

    def visit_do_statement(self, node: Node) -> CFGTraversalResult:
        """Visit a do-while loop"""
        # Get components via named fields
        condition_node = get_required_child_by_field_name(node, "condition")
        body_stmt = get_required_child_by_field_name(node, "body")

        # Create loop header (condition) with actual condition text
        condition_text = get_source_text(condition_node)
        loop_header_id = self.create_node(
            NodeType.LOOP_HEADER, condition_node, condition_text
        )

        # Create exit node for the loop
        loop_exit_id = self.create_node(
            NodeType.EXIT, source_text="EXIT: do-while loop"
        )

        # Create entry node for do-while loop
        do_entry_id = self.create_node(
            NodeType.ENTRY, source_text="ENTRY: do-while loop"
        )

        # Set up loop context for break/continue
        self.context.push_loop_context(loop_exit_id, loop_header_id)

        # Process loop body
        body_entry_id = None
        body_result = self._create_body_node(body_stmt, do_entry_id, loop_header_id)
        body_entry_id = body_result.entry_node_id

        # Connect condition back to body entry with "true" label (looping back)
        self.cfg.add_edge(loop_header_id, body_entry_id, "true")

        # Connect condition to exit with "false" label
        self.cfg.add_edge(loop_header_id, loop_exit_id, "false")

        # Clean up loop context
        self.context.pop_loop_context()

        return CFGTraversalResult(
            entry_node_id=do_entry_id, exit_node_ids=[loop_exit_id]
        )

    def visit_switch_statement(self, node: Node) -> CFGTraversalResult:
        """Visit a switch statement"""
        # Get components via named fields
        condition_node = get_required_child_by_field_name(node, "condition")
        body_node = get_required_child_by_field_name(node, "body")

        # Create switch head node
        switch_head_id = self._create_condition_node(
            condition_node, NodeType.SWITCH_HEAD
        )

        # Create exit node for the switch
        switch_exit_id = self.create_node(NodeType.EXIT, source_text="EXIT: switch")

        # Set up switch context for break statements
        self.context.push_switch_context(switch_exit_id, switch_head_id)

        # Process switch body, which should contain case statements
        self._create_body_node(body_node, switch_head_id, switch_exit_id)
        # Note: We don't add edge labels here as the individual case statements
        # will connect to the switch head with appropriate case value labels

        # Clean up switch context
        self.context.pop_switch_context()

        return CFGTraversalResult(
            entry_node_id=switch_head_id, exit_node_ids=[switch_exit_id]
        )

    def visit_case_statement(self, node: Node) -> CFGTraversalResult:
        """Visit a case statement within a switch"""
        # Get value via named field
        value_expr = get_child_by_field_name(node, "value")

        # Create case node with the case value
        if value_expr:
            value_text = get_source_text(value_expr)
            case_id = self.create_node(NodeType.CASE, value_expr, f"CASE: {value_text}")
        else:
            # Default case without value
            value_text = "default"
            default_label = get_required_child_by_type(node, "default")
            case_id = self.create_node(
                NodeType.CASE,
                source_text=get_source_text(default_label),
                ast_node=default_label,
            )

        # Connect case to switch head if available
        switch_head = self.context.get_switch_head()
        if switch_head is not None:
            # Add edge with case value as label
            value_label = value_text
            self.cfg.add_edge(switch_head, case_id, value_label)

        exit_nodes = [case_id]  # Default exit is case node itself for fall-through

        # Process all body statements in sequence if present
        # Remaining statements after the value become the body
        body_stmts = []
        for child in node.children:
            if child.type == "default":
                continue
            # Skip case, value expr, and colons
            if child.type == "case" or child == value_expr or child.type == ":":
                continue
            body_stmts.append(child)

        if body_stmts:
            last_exits = [case_id]  # Start with the case node

            # Process each statement in the body sequentially
            for body_stmt in body_stmts:
                stmt_result = self.visit(body_stmt)
                if stmt_result:  # Make sure we got a valid result
                    # Connect last statement's exits to this statement's entry
                    for exit_id in last_exits:
                        self.cfg.add_edge(exit_id, stmt_result.entry_node_id)

                    # Update the current exits
                    last_exits = stmt_result.exit_node_ids

                    # If it's a break or other control flow statement (like return/goto)
                    if not last_exits:  # Empty exit nodes list
                        # No fall-through to the next case
                        exit_nodes = []
                        break

            # If we went through all statements and still have exit nodes,
            # those become the exit nodes for the whole case
            if last_exits:
                exit_nodes = last_exits

        return CFGTraversalResult(entry_node_id=case_id, exit_node_ids=exit_nodes)

    def visit_labeled_statement(self, node: Node) -> CFGTraversalResult:
        """Visit a labeled statement - target for goto statements"""
        # Get components via named fields
        label_node = get_required_child_by_field_name(node, "label")
        label_name = get_source_text(label_node)

        # Get the statement after label (assuming it's the first non-label child)
        body_stmt = None
        for child in node.children:
            if child != label_node and child.type != ":":
                body_stmt = child
                break

        # Create label node
        label_id = self.create_node(NodeType.LABEL, source_text=label_name)

        # Register label in context
        goto_refs = self.context.add_label(label_name, label_id)
        # Connect any forward goto references to this label
        for goto_id in goto_refs:
            self.cfg.add_edge(goto_id, label_id)

        # Process body statement
        if body_stmt:
            body_result = self.visit(body_stmt)
            self.cfg.add_edge(label_id, body_result.entry_node_id)
            return CFGTraversalResult(
                entry_node_id=label_id, exit_node_ids=body_result.exit_node_ids
            )

        return CFGTraversalResult(entry_node_id=label_id, exit_node_ids=[label_id])

    def visit_goto_statement(self, node: Node) -> CFGTraversalResult:
        """Visit a goto statement - unconditional jump to a label"""
        # Get label via named field
        label_node = get_required_child_by_field_name(node, "label")
        target_label = get_source_text(label_node)

        # Create goto node
        goto_id = self.create_node(NodeType.GOTO, node, target_label)

        # Try to connect to label if it exists
        target_id = self.context.add_goto_ref(target_label, goto_id)
        if target_id:
            # If label already defined, connect goto to label
            self.cfg.add_edge(goto_id, target_id)

        # Goto statements don't have normal successors (control flow is transferred)
        return CFGTraversalResult(entry_node_id=goto_id, exit_node_ids=[])
