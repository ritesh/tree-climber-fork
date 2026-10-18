# Extending Tree Climber to Support New Languages

This guide provides step-by-step instructions for adding support for a new programming language to Tree Climber. The process involves creating language-specific configuration files, implementing AST node handling, and setting up test files.

## Prerequisites

1. Tree-sitter grammar for the target language
2. Node types JSON file describing the AST structure for the language

## Steps Overview

1. Add node types configuration
2. Create the visitor
3. Register the language
4. Set up test files
5. Implement and test

## Detailed Steps

### 1. Add Node Types Configuration

1. Create a new directory under `docs/grammars/<language>/`
2. Add `node-types.json` file containing the AST node type definitions from tree-sitter
   - This file should be obtained from the tree-sitter grammar repository for your language
   - Ensure it contains all node types and their field definitions

### 2. Create the Visitor

Create `src/tree_climber/cfg/languages/<language>.py` with a subclass of `CFGVisitor` (`src/tree_climber/cfg/visitor.py`). [Building the CFG](../architecture.md#42-building-the-cfg) in the architecture document explains the design. In short:

- `visit(node)` calls `visit_<node type>(node)`, or `generic_visit(node)` when there is no such method. `generic_visit` makes a leaf one `STATEMENT` node and chains the named children of any other node in order.
- Each visit method returns a `CFGTraversalResult`: the subtree's entry node and its exit nodes. The caller connects the exits to whatever comes next. An empty exit list means control does not fall through (`break`, `return`).
- `self.create_node(node_type, ast_node, source_text)` adds a node and fills its metadata (calls, definitions, uses) from the three methods below. `self.cfg.add_edge(a, b, label)` adds an edge; branches use the labels `"true"` and `"false"`.
- `self.context` keeps the targets of jumps. `push_loop_context(exit, header)` sets where `break` and `continue` go; `push_switch_context` does the same for `switch`. Pop them when the construct ends.
- Helper nodes such as a loop's exit are `EXIT` nodes that are not in `cfg.exit_node_ids`. `postprocess_cfg` removes them, and `CASE` and `DEFAULT` nodes, connecting their predecessors to their successors. It also links calls to functions by name, so a call can reach a function defined later in the file.

A visitor must implement three methods. `create_node` calls them on the new node's AST node:

- `get_call_sites(ast_node)`: one `CallSite` per call, in source order, with its arguments. `callee` is the name used to link the call, or `None` when there is no usable name. `assigned_to` names the variables that receive the result; the query layer and taint use it.
- `get_definitions(ast_node)`: the variables it writes.
- `get_uses(ast_node)`: the variables it reads.

Optionally, set `MUTATING_METHODS` (`append`, `put`) so that `items.append(x)` is a weak update of `items`; this needs `receiver` and `receiver_uses` on the call site. Implement `get_direct_uses` (the uses outside any call) so that taint can tell `x` apart from `escape(x)`. `src/tree_climber/cfg/call_sites.py` has helpers the existing visitors share.

A function needs more than its body:

- an `ENTRY` node and an `EXIT` node, appended to `cfg.entry_node_ids` and `cfg.exit_node_ids` in the same order;
- the parameters as the ENTRY's definitions;
- a `FunctionInfo` on the ENTRY's `metadata.function`, which the interprocedural analysis reads;
- `context.register_function_definition(entry, name)`, so calls get linked.

Give the ENTRY an AST node: the data-flow analyses skip the definitions of nodes without one. A `return` connects to `self.cfg.exit_node_ids[-1]`, the current function's EXIT.

Here is a small visitor. It handles functions, `while`, `break` and expression statements. The node types are those of the C grammar, so you can try it on C code.

```python
from typing import List, Optional

from tree_sitter import Node

from tree_climber.ast_utils import get_required_child_by_field_name, get_source_text
from tree_climber.cfg.call_sites import preorder, with_span
from tree_climber.cfg.cfg_types import (
    CallArgument,
    CallSite,
    CFGTraversalResult,
    FunctionInfo,
    NodeType,
    ParameterInfo,
)
from tree_climber.cfg.visitor import CFGVisitor


class MyLangCFGVisitor(CFGVisitor):
    def get_call_sites(self, ast_node: Node) -> List[CallSite]:
        sites = []
        for node in preorder(ast_node):
            if node.type == "call_expression":
                callee = get_required_child_by_field_name(node, "function")
                name = get_source_text(callee) if callee.type == "identifier" else None
                arguments = [
                    CallArgument(get_source_text(argument), self.get_uses(argument))
                    for argument in get_required_child_by_field_name(
                        node, "arguments"
                    ).named_children
                ]
                site = CallSite(name, get_source_text(callee), arguments=arguments)
                sites.append(with_span(site, node))
        return sites

    def get_definitions(self, ast_node: Node) -> List[str]:
        return [
            get_source_text(get_required_child_by_field_name(node, "left"))
            for node in preorder(ast_node)
            if node.type == "assignment_expression"
        ]

    def get_uses(self, ast_node: Node) -> List[str]:
        skipped = set()
        for node in preorder(ast_node):
            if node.type == "assignment_expression":
                skipped.add(get_required_child_by_field_name(node, "left").id)
            elif node.type == "call_expression":
                skipped.add(get_required_child_by_field_name(node, "function").id)
        return [
            get_source_text(node)
            for node in preorder(ast_node)
            if node.type == "identifier" and node.id not in skipped
        ]

    def visit_translation_unit(self, node: Node) -> Optional[CFGTraversalResult]:
        for child in node.named_children:
            if child.type == "function_definition":
                self.visit(child)
        return None

    def visit_expression_statement(self, node: Node) -> CFGTraversalResult:
        node_id = self.create_node(NodeType.STATEMENT, node, get_source_text(node))
        return CFGTraversalResult(entry_node_id=node_id, exit_node_ids=[node_id])

    def visit_while_statement(self, node: Node) -> CFGTraversalResult:
        condition = get_required_child_by_field_name(node, "condition")
        header_id = self.create_node(
            NodeType.LOOP_HEADER, condition, get_source_text(condition)
        )
        exit_id = self.create_node(NodeType.EXIT, source_text="EXIT: while loop")

        self.context.push_loop_context(exit_id, header_id)
        body = self.visit(get_required_child_by_field_name(node, "body"))
        self.context.pop_loop_context()

        self.cfg.add_edge(header_id, body.entry_node_id, "true")
        for body_exit in body.exit_node_ids:
            self.cfg.add_edge(body_exit, header_id)
        self.cfg.add_edge(header_id, exit_id, "false")
        return CFGTraversalResult(entry_node_id=header_id, exit_node_ids=[exit_id])

    def visit_break_statement(self, node: Node) -> CFGTraversalResult:
        break_id = self.create_node(NodeType.BREAK, node, get_source_text(node))
        target = self.context.get_break_target()
        if target is None:
            return CFGTraversalResult(entry_node_id=break_id, exit_node_ids=[break_id])
        self.cfg.add_edge(break_id, target)
        return CFGTraversalResult(entry_node_id=break_id, exit_node_ids=[])

    def visit_function_definition(self, node: Node) -> CFGTraversalResult:
        declarator = get_required_child_by_field_name(node, "declarator")
        name = get_source_text(
            get_required_child_by_field_name(declarator, "declarator")
        )
        parameters = [
            get_source_text(get_required_child_by_field_name(p, "declarator"))
            for p in get_required_child_by_field_name(
                declarator, "parameters"
            ).named_children
        ]

        entry_id = self.create_node(NodeType.ENTRY, declarator, name)
        metadata = self.cfg.nodes[entry_id].metadata
        metadata.variable_definitions = parameters
        metadata.variable_uses = []
        metadata.function = FunctionInfo(
            call_name=name, parameters=[ParameterInfo(p) for p in parameters]
        )
        exit_id = self.create_node(NodeType.EXIT, source_text=name)
        self.cfg.entry_node_ids.append(entry_id)
        self.cfg.exit_node_ids.append(exit_id)
        self.context.register_function_definition(entry_id, name)

        body = self.visit(get_required_child_by_field_name(node, "body"))
        self.cfg.add_edge(entry_id, body.entry_node_id)
        for body_exit in body.exit_node_ids:
            self.cfg.add_edge(body_exit, exit_id)
        return CFGTraversalResult(entry_node_id=entry_id, exit_node_ids=[exit_id])
```

The root needs its own visit method, as here. Otherwise `generic_visit` would chain one function's EXIT to the next function's ENTRY. On a small C file with loops, a `break` and calls, this visitor gives the same graph, node metadata, def-use chains and argument flows as the C visitor (`test/test_extending_languages_doc.py` checks this). Return flows need a `visit_return_statement`.

### 3. Register the Language

Add one `LanguageSpec` to `LANGUAGES` in `src/tree_climber/language_registry.py`:

```python
LanguageSpec(
    name="python",  # registry key and tree-sitter grammar name
    display_name="Python",
    extensions=(".py", ".pyi"),
    visitor="tree_climber.cfg.languages.python:PythonCFGVisitor",
)
```

The CFG builder, CLI (supported-language list, `--language` validation, file extension detection), and web API (request validation and OpenAPI schema) all derive from the registry. The only other manual step is the label in `src/tree_climber/viz/frontend/src/LanguageSelector.tsx`. `test/test_language_registry.py` checks every registered language's grammar, visitor, and builder automatically.

### 4. Set Up Test Files

1. Create `test/<language>_cfg/` with fixture files and `test_<language>_cfg.py`, modeled after `test/c_cfg/` and `test/python_cfg/`
2. Describe what each fixture covers in its own header comment (keep the directory README minimal)
3. Add def/use tests next to them (see `test/python_cfg/test_python_bindings.py`), and a sample file to the CLI tests in `test/cli/test_cli.py`

### 5. Implementation Process

1. Start with basic control flow structures:
   - If statements
   - Loops (while, for)
   - Function definitions
   - Basic blocks (sequences of statements)

2. Add support for language-specific features:
   - Switch/case statements
   - Exception handling
   - Break/continue statements
   - Return statements

3. Follow existing language implementations (Python, C, Java) as reference
   - Look at how similar constructs are handled
   - Maintain consistent patterns for similar structures

4. Test incrementally:
   - Write tests for each new feature
   - Visualize CFGs to verify correctness
   - Ensure edge cases are covered

## Common Pitfalls

1. **Node Type Mismatches**: Ensure node types in your handlers exactly match those in node-types.json
2. **Missing Fields**: Verify all required node fields are accessed correctly
3. **Edge Connections**: Double-check that all blocks are properly connected
4. **Block Ordering**: Maintain correct execution order in the CFG

## Resources

1. Refer to existing implementations:
   - `src/tree_climber/cfg/languages/python.py`
   - `src/tree_climber/cfg/languages/c.py`
   - `src/tree_climber/cfg/languages/java.py`
2. Tree-sitter documentation for your language
3. Language specification for control flow semantics

## Troubleshooting

1. If tests fail:
   - Check node type names match exactly
   - Verify field access paths
   - Compare with working implementations
   - Use visualization to spot structural issues

2. If visualization looks wrong:
   - Check edge connections
   - Verify block creation order
   - Ensure all paths are connected
   - Look for disconnected components

3. Common errors:
   - AttributeError: Usually means incorrect field name
   - KeyError: Missing node field
   - TypeError: Wrong node type handling

## Current Implementation Limitations

These are the known gaps in the existing languages. A construct without a visit method becomes a generic statement: its named children run in order, as plain statements.

### Cross-Language
- A statement is one CFG node. It is not split into separate assignments.
- Aliasing is not modelled, within a function or between functions.
- Calls are linked by name within one file. A function is analysed once for all its callers.
- A write through a field or subscript is a weak update: the root name is both defined and used. (C pointer writes and Java field writes are not tracked at all; see below.)

### C (`c.py`)

**Modelled:** functions, `if`, `while`, `do`, `for`, `switch` with fall-through between cases, `break`, `continue`, `goto` and labels, `return`, and `#if`/`#ifdef` groups inside a function.

**Not modelled:**
- Pointer writes: `p->f = v` and `*q = v` define nothing.
- Calls through function pointers (`(*fp)(x)`, `s->cb(x)`): they have no callee name, so they are not linked.
- Statements without a visit method: `attributed_statement` (so `[[fallthrough]];` is a plain statement) and the Windows `seh_try_statement` and `seh_leave_statement`.
- GCC statement expressions (`({ ... })`) and computed `goto *p`: the bundled grammar does not parse them.
- Free variables: any name not declared in a function is a global.

### Java (`java.py`)

**Modelled:** classes and methods, `if`, `while`, `do`, `for`, enhanced `for`, `switch` with `case ... :` groups, `break`, `continue`, `return`, and `MUTATING_METHODS` (`list.add(x)` is a weak update of `list`).

**Not modelled:**
- Exceptions: `try`, `catch`, `finally`, `throw` and try-with-resources have no visit methods. Their parts run in order, and no exception edges exist.
- Arrow `switch` rules (`case 1 -> ...`) run one after another. A `switch` expression used as a value is one statement, with its `yield`s inside.
- `assert` and `synchronized` are plain statements.
- Field and array writes: `o.f = v`, `this.f = v` and `a[i] = v` define nothing.
- Lambdas and anonymous classes stay inside their statement. Their calls count as calls of that statement.
- Free variables (captured locals and fields) are not connected between methods. Arguments and returns are.

### Python (`python.py`, `python_bindings.py`)

See `docs/python-guide.md` for worked examples of each point.

**Modelled:** module and function graphs (every function and method is its own subgraph, at any depth), `if`/`elif`/`else`, `while`, `for` and loop `else`, `break`/`continue`, `match`, `try`/`except`/`except*`/`else`/`finally`, `raise`, `with`, async forms, classes, decorators, and def/use for every binding construct.

**Approximations:**
- Calls are resolved by name only, across the whole file: `obj.f()` links to every function named `f`, and `self.step()` to every method named `step` in any class. `Class(...)` links to `Class.__init__`. Calling a generator or coroutine function links to its entry even though the body runs later.
- Each function's def-use chains stay separate. Free-variable flows connect closure reads and `global`/`nonlocal` writes to the other scope's definitions, but they ignore order: every definition reaches every such use.
- Writes through attributes and subscripts (`a.b = v`, `a[i] = v`) are weak updates: the root name is defined and used.
- Exceptions: `with` suppression by `__exit__` is not modeled; a `finally` block is shared by all paths and does not remember which one entered it; one edge carries one label, so a `finally` exit that both returns and re-raises to the same target shows only the first; handler headers, `case` tests and `__exit__` nodes are treated as non-raising; exceptions that escape a callee leave through its EXIT, so return edges also appear on exception paths.
- `match`: a pattern that fails after binding some names is treated as binding none; the bundled grammar parses `(name)` as a one-element tuple pattern.

**Statements that stay whole:**
- A class body is one statement (its calls count; the names it binds are not tracked and its own control flow is not modeled).
- Lambdas, comprehensions, `yield` and `await` stay inside their statement.
- A plain module-level `def` has no statement in the module flow, so a file of only `def`s has no `<module>` graph.

**Grammar:** the bundled tree-sitter grammar predates some recent syntax (`type` statements, PEP 695 generics on classes, PEP 701 f-strings). Such code parses but may be one opaque statement without its bindings.

### Recommendations for New Languages

- Plan for exceptions from the start. Python's visitor shows one way to model them.
- Decide early what a write through a field, subscript or pointer defines.
- Fill in `FunctionInfo` fully (`locals`, `globals`, `nonlocals`, `parent`), so free-variable flows work.
- Test each construct with a fixture, and compare the CFG with what the language's semantics say.
