# Extending Tree Climber to Support New Languages

This guide provides step-by-step instructions for adding support for a new programming language to Tree Climber. The process involves creating language-specific configuration files, implementing AST node handling, and setting up test files.

## Prerequisites

1. Tree-sitter grammar for the target language
2. Node types JSON file describing the AST structure for the language

## Steps Overview

1. Add node types configuration
2. Create language configuration module
3. Register the language
4. Set up test files
5. Implement and test

## Detailed Steps

### 1. Add Node Types Configuration

1. Create a new directory under `docs/grammars/<language>/`
2. Add `node-types.json` file containing the AST node type definitions from tree-sitter
   - This file should be obtained from the tree-sitter grammar repository for your language
   - Ensure it contains all node types and their field definitions

### 2. Create Language Configuration Module

1. Create a new Python module at `src/tree_climber/cfg/languages/<language>.py`
2. Implement the following components:

```python
from tree_climber.cfg.cfg_types import Block, Edge, EdgeType
from tree_climber.cfg.visitor import CFGVisitor

class LanguageVisitor(CFGVisitor):
    """Visitor class for building CFG from language-specific AST nodes."""
    
    def __init__(self):
        super().__init__()
        # Add any language-specific initialization
        
    def handles_type(self, node_type: str) -> bool:
        """Define which node types this visitor handles."""
        # Return True for any node types that have handler methods
        return node_type in [
            'if_statement',
            'while_statement',
            # Add other handled node types
        ]

    def handle_if_statement(self, node, **kwargs):
        """Handle if statement nodes.
        
        Required components:
        1. Extract condition from the node
        2. Create condition block
        3. Process true branch
        4. Process false branch if exists
        5. Create merge block if needed
        6. Connect blocks with appropriate edges
        """
        # Implementation

    def handle_while_statement(self, node, **kwargs):
        """Handle while loop nodes.
        
        Required components:
        1. Create loop header block
        2. Extract and process condition
        3. Process loop body
        4. Connect blocks with appropriate edges
        5. Handle continue/break statements
        """
        # Implementation
```

Key implementation notes:

a. Node Creation:
```python
# Create new CFG nodes using:
node = CFGNode(
    id=self.next_id(),  # Get unique node ID
    node_type=NodeType.STATEMENT,  # From NodeType enum
    ast_node=node,  # Original AST node
    source_text=self.get_text(node)  # Source code text
)
```

b. Edge Creation:
```python
# Connect nodes using successors:
source_node.add_successor(target_node.id, label="true")  # Optional label for conditional edges

# Or for more complex cases:
source_node.successors.add(target_node.id)
source_node.edge_labels[target_node.id] = "true"  # For conditional branches
```

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

3. Follow existing language implementations (e.g., Java, C) as reference
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
   - `src/tree_climber/cfg/languages/java.py`
   - `src/tree_climber/cfg/languages/c.py`
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

This section documents known limitations in existing language implementations that could be addressed when extending support.

### Cross-Language
- Statements are represented by individual CFG nodes, but should be broken up into independent assignments for more granular analysis.
- Interprocedural aliasing is not supported.

### C Language Implementation Limitations (`c.py`)

**Missing Statement Types:**
- `attributed_statement` - Statements with attributes/annotations 
- `seh_leave_statement` - Structured Exception Handling (Windows-specific)
- `seh_try_statement` - SEH try blocks (Windows-specific)

**Missing Expression Handling:**
- Complex pointer dereferencing patterns
- Struct/union field access beyond basic cases
- Function pointers and their invocations
- Variadic function calls (`...` parameters)

**Missing Advanced Control Flow:**
- Computed `goto` statements (GCC extension)
- Nested function definitions (GCC extension)
- Statement expressions (GCC extension)

**Variable Analysis Gaps:**
- Array subscript handling in def/use analysis
- Field member access (struct.field) in variable tracking
- Pointer arithmetic effects on variable state

### Java Language Implementation Limitations (`java.py`)

**Missing Statement Types:**
- `assert_statement` - Java assertions
- `synchronized_statement` - Synchronized blocks 
- `yield_statement` - Switch expression yield
- Exception handling
   - `throw_statement` - Exception throwing
   - `try_statement` - Try-catch-finally blocks
   - `try_with_resources_statement` - Try-with-resources

**Missing Advanced Switch Constructs:**
- `switch_rule` - Modern switch expression rules (Java 14+)
- Pattern matching in switch statements
- `guard` expressions in switch cases

**Missing Lambda/Functional Constructs:**
- `lambda_expression` body analysis beyond basic cases
- Method references (`::` operator)
- Stream operations and functional interfaces

**Missing Exception Handling:**
- `catch_clause` processing
- `finally_clause` processing
- Exception propagation through CFG
- `throws` clause analysis

**Missing Modern Java Features:**
- Record pattern matching
- Template expressions (preview feature)
- Module system statements (`exports`, `requires`, etc.)

**Expression Analysis Gaps:**
- Generic type instantiation effects
- Method chaining in fluent interfaces
- Anonymous class instantiation
- Array initializer expressions

### Python Language Implementation Limitations (`python.py`, `python_bindings.py`)

See `docs/python-guide.md` for worked examples of each point.

**Modeled:** module and function graphs (every function and method is its own subgraph, at any depth), `if`/`elif`/`else`, `while`, `for` and loop `else`, `break`/`continue`, `match`, `try`/`except`/`except*`/`else`/`finally`, `raise`, `with`, async forms, classes, decorators, and def/use for every binding construct.

**Approximations:**
- Calls are resolved by name only, across the whole file: `obj.f()` links to every function named `f`, and `self.step()` to every method named `step` in any class. `Class(...)` links to `Class.__init__`. Calling a generator or coroutine function links to its entry even though the body runs later.
- Dataflow does not cross function calls, so closure reads and `global`/`nonlocal` writes are not connected to the other scope's definitions (#42).
- Writes through attributes and subscripts (`a.b = v`, `a[i] = v`) are weak updates: the root name is defined and used.
- Exceptions: `with` suppression by `__exit__` is not modeled; a `finally` block is shared by all paths and does not remember which one entered it; one edge carries one label, so a `finally` exit that both returns and re-raises to the same target shows only the first; handler headers, `case` tests and `__exit__` nodes are treated as non-raising; exceptions that escape a callee leave through its EXIT, so return edges also appear on exception paths.
- `match`: a pattern that fails after binding some names is treated as binding none; the bundled grammar parses `(name)` as a one-element tuple pattern.

**Statements that stay whole:**
- A class body is one statement (its calls count; the names it binds are not tracked and its own control flow is not modeled).
- Lambdas, comprehensions, `yield` and `await` stay inside their statement.
- A plain module-level `def` has no statement in the module flow, so a file of only `def`s has no `<module>` graph.

**Grammar:** the bundled tree-sitter grammar predates some recent syntax (`type` statements, PEP 695 generics on classes, PEP 701 f-strings). Such code parses but may be one opaque statement without its bindings.

### General Architecture Limitations

**AST Node Coverage:**
- Both implementations handle only a subset of available grammar nodes
- Missing visitor methods for many node types means they're treated as generic statements

**Control Flow Edge Cases:**
- Fall-through behavior in switch statements not fully modeled
- Exception control flow paths missing
- Resource management (try-with-resources) lifecycle not tracked

**Variable Analysis Depth:**
- Limited handling of complex expressions in def/use analysis  
- No support for aliasing through pointers/references
- Missing analysis of field modifications vs local variables

**Language Feature Support:**
- Modern language features (Java 17+, C23) not covered
- Compiler-specific extensions (GCC, MSVC) not handled
- Platform-specific constructs missing

### Recommendations for New Language Implementations

When implementing support for new languages, consider addressing these common gaps:

1. **Exception Handling**: Plan for exception control flow from the start
2. **Modern Language Features**: Include support for recent language additions
3. **Complex Expressions**: Handle nested and chained expressions properly
4. **Variable Analysis**: Implement comprehensive def/use tracking
5. **Platform Extensions**: Consider compiler-specific or platform-specific features
6. **Resource Management**: Model resource lifecycle (RAII, try-with-resources, etc.)

This analysis reveals that while both implementations cover core imperative control flow constructs well (if/while/for/switch), they lack support for many advanced language features available in their respective grammars.
