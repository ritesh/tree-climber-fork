"""
Control Flow Graph (CFG) Generator Framework using py-tree-sitter for C language.
This framework uses the visitor pattern with depth-first traversal to build CFGs.
"""

from typing import Iterator, List, Optional, Tuple

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
    uses_outside_calls,
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
                    CallArgument(
                        text=get_source_text(a),
                        uses=self.get_uses(a),
                        direct_uses=self.get_direct_uses(a),
                    )
                    for a in self._argument_nodes(call)
                ],
                assigned_to=self._assigned_names(call),
                receiver_uses=self.get_direct_uses(receiver) if receiver else None,
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

    CALLS = frozenset({"call_expression"})

    def get_direct_uses(self, ast_node: Node) -> List[str]:
        """Variable uses under an AST node outside any call."""
        return uses_outside_calls(ast_node, self.get_uses, self.CALLS)

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
        for child in self._top_level_functions(node):
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

    def visit_ERROR(self, node: Node) -> Optional[CFGTraversalResult]:
        """A file tree-sitter could not parse as a whole is an ERROR root: its
        functions are built one by one, as in a translation unit, not chained."""
        if node.parent is None:
            return self.visit_translation_unit(node)
        return self.generic_visit(node)

    PREPROCESSOR_GROUPS = (
        "preproc_if",
        "preproc_ifdef",
        "preproc_elif",
        "preproc_else",
        "ERROR",
    )

    @classmethod
    def _top_level_functions(cls, node: Node) -> Iterator[Node]:
        """Function definitions at file level, including those inside `#if`,
        `#ifdef` and their `#elif` and `#else` groups."""
        for child in node.children:
            if child.type == "function_definition":
                yield child
            elif child.type in cls.PREPROCESSOR_GROUPS:
                yield from cls._top_level_functions(child)

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
    def _function_declarator(cls, declarator: Node) -> Optional[Node]:
        """The declarator of the function itself, the innermost function
        declarator: `f(...)` in `int *f(...)` and in `int (*f(int x))(int)`, where
        the outer `(int)` belongs to the returned function pointer."""
        found: Optional[Node] = None
        node: Optional[Node] = declarator
        while node is not None:
            if node.type == "function_declarator":
                found = node
            node = cls._inner_declarator(node)
        return found

    def _parameters(self, parameter_list: Node) -> List[ParameterInfo]:
        parameters: List[ParameterInfo] = []
        for param in parameter_list.children:
            if param.type == "parameter_declaration":
                name = self._declared_identifier(
                    get_child_by_field_name(param, "declarator")
                )
                if name:
                    parameters.append(ParameterInfo(get_source_text(name)))
            elif param.is_named and param.type != "comment":
                parameters.append(
                    ParameterInfo(get_source_text(param), "var_positional")
                )
        return parameters

    def _macro_signature(
        self, definition: Node, declarator: Node
    ) -> Tuple[str, List[ParameterInfo]]:
        """The name and parameters of a definition whose signature macros write,
        so that it has no function declarator: `NAME(x) {` (a macro, K&R
        `main(c)`, or a return type on the line before) parses as type `NAME`
        and declarator `(x)`, and `int f PARAMS {` as the declarator `PARAMS`
        after an error holding `f`."""
        name = self._declared_identifier(declarator)
        for child in definition.children:
            if child.id == declarator.id:
                break
            if child.type == "ERROR" and [c.type for c in child.children] == [
                "identifier"
            ]:
                name = child.children[0]
        type_node = definition.child_by_field_name("type")
        if (
            declarator.type == "parenthesized_declarator"
            and type_node is not None
            and type_node.type == "type_identifier"
        ):
            parameters = []
            if name is not None and get_source_text(name) != "void":
                parameters.append(ParameterInfo(get_source_text(name)))
            return get_source_text(type_node), parameters
        if name is None:
            raise ValueError(f"No function name in {get_source_text(declarator)!r}")
        return get_source_text(name), []

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
        declarator_node = get_required_child_by_field_name(node, "declarator")
        body_node = get_required_child_by_field_name(node, "body")
        closing_brace = None

        declarator = self._function_declarator(declarator_node)
        if declarator is not None:
            function_name = get_source_text(self._function_name(declarator))
            parameter_infos = self._parameters(
                get_required_child_by_field_name(declarator, "parameters")
            )
        else:
            declarator = declarator_node
            function_name, parameter_infos = self._macro_signature(
                node, declarator_node
            )
        parameters = [p.name for p in parameter_infos]

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
        outer_labels = self.context.labels, self.context.forward_goto_refs
        self.context.labels, self.context.forward_goto_refs = {}, {}

        self._create_body_node(body_node, entry_id, exit_id)

        self.context.labels, self.context.forward_goto_refs = outer_labels
        self.context.pop_entry()
        self.context.pop_exit()

        return CFGTraversalResult(entry_node_id=entry_id, exit_node_ids=[exit_id])

    def _visit_sequence(self, nodes: List[Node]) -> Optional[CFGTraversalResult]:
        """Visit statements one after another; None when there are none."""
        first_entry = None
        current_exits: List[int] = []
        for child in nodes:
            if not child.is_named or child.type == "comment":
                continue
            child_result = self.visit(child)
            if first_entry is None:
                first_entry = child_result.entry_node_id
            else:
                for exit_node in current_exits:
                    self.cfg.add_edge(exit_node, child_result.entry_node_id)
            current_exits = child_result.exit_node_ids
        if first_entry is None:
            return None
        return CFGTraversalResult(
            entry_node_id=first_entry, exit_node_ids=current_exits
        )

    def visit_compound_statement(self, node: Node) -> CFGTraversalResult:
        """Visit a compound statement (block)"""
        result = self._visit_sequence(node.children)
        if result is not None:
            return result
        placeholder_id = self.create_node(NodeType.STATEMENT, source_text="empty block")
        return CFGTraversalResult(
            entry_node_id=placeholder_id, exit_node_ids=[placeholder_id]
        )

    def visit_preproc_if(self, node: Node) -> CFGTraversalResult:
        """`#if`, `#ifdef` and `#ifndef` in a function: a branch to each group
        (`#elif`, `#else`), or past the block when there is no `#else`."""
        return self._preproc_branch(node)

    visit_preproc_ifdef = visit_preproc_if

    def _preproc_branch(self, node: Node) -> CFGTraversalResult:
        test = node.child_by_field_name("condition") or node.child_by_field_name("name")
        directive = node.children[0].type
        head_id = self.create_node(
            NodeType.CONDITION,
            source_text=f"{directive} {get_source_text(test)}" if test else directive,
        )
        alternative = node.child_by_field_name("alternative")
        fields = {child.id for child in (test, alternative) if child is not None}

        exits: List[int] = []
        group = self._visit_sequence(
            [child for child in node.children if child.id not in fields]
        )
        if group is None:
            exits.append(head_id)
        else:
            self.cfg.add_edge(head_id, group.entry_node_id, "true")
            exits.extend(group.exit_node_ids)

        other = None
        if alternative is not None and alternative.type == "preproc_else":
            other = self._visit_sequence(alternative.children)
        elif alternative is not None:
            other = self._preproc_branch(alternative)
        if other is None:
            exits.append(head_id)
        else:
            self.cfg.add_edge(head_id, other.entry_node_id, "false")
            exits.extend(other.exit_node_ids)

        return CFGTraversalResult(
            entry_node_id=head_id, exit_node_ids=list(dict.fromkeys(exits))
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
        """Visit a for loop; each of its three clauses may be empty."""
        init_expr = get_child_by_field_name(node, "initializer")
        condition_expr = get_child_by_field_name(node, "condition")
        update_expr = get_child_by_field_name(node, "update")
        body_stmt = get_required_child_by_field_name(node, "body")

        init_id = None
        if init_expr is not None:
            init_id = self.create_node(
                NodeType.STATEMENT, init_expr, get_source_text(init_expr)
            )

        if condition_expr is not None:
            condition_id = self.create_node(
                NodeType.LOOP_HEADER, condition_expr, get_source_text(condition_expr)
            )
        else:
            condition_id = self.create_node(
                NodeType.LOOP_HEADER, source_text="(no condition)"
            )

        entry_id = condition_id
        if init_id is not None:
            entry_id = init_id
            self.cfg.add_edge(init_id, condition_id)

        continue_id = condition_id
        if update_expr is not None:
            continue_id = self.create_node(
                NodeType.STATEMENT, update_expr, get_source_text(update_expr)
            )

        exit_id = self.create_node(NodeType.EXIT, source_text="EXIT: for loop")

        self.context.push_loop_context(exit_id, continue_id)
        self._create_body_node(body_stmt, condition_id, continue_id, edge_label="true")
        if continue_id != condition_id:
            self.cfg.add_edge(continue_id, condition_id)
        self.cfg.add_edge(condition_id, exit_id, "false")
        self.context.pop_loop_context()

        return CFGTraversalResult(entry_node_id=entry_id, exit_node_ids=[exit_id])

    def visit_break_statement(self, node: Node) -> CFGTraversalResult:
        """Visit a break statement"""
        break_id = self.create_node(NodeType.BREAK, node, get_source_text(node))

        break_target = self.context.get_break_target()
        if break_target is None:
            return CFGTraversalResult(entry_node_id=break_id, exit_node_ids=[break_id])
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

        continue_target = self.context.get_continue_target()
        if continue_target is None:
            return CFGTraversalResult(
                entry_node_id=continue_id, exit_node_ids=[continue_id]
            )
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

        body_stmt = None
        for child in node.children:
            if child.is_named and child != label_node and child.type != "comment":
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
