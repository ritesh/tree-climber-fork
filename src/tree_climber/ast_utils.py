from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from tree_sitter import Node, Tree
from tree_sitter_languages import get_parser


def parse_source_to_ast(source_code: str, language: str) -> Tree:
    """Parse source code and return the AST tree.

    Args:
        source_code: The source code to parse
        language: The programming language (e.g., 'c', 'java')

    Returns:
        Tree: The parsed AST tree

    Raises:
        ValueError: If the language is not supported or parsing fails
    """
    try:
        parser = get_parser(language)
        tree = parser.parse(bytes(source_code, "utf8"))
        if not tree:
            raise ValueError(f"Failed to parse {language} source code")
        return tree
    except Exception as e:
        raise ValueError(f"Error parsing {language} source code: {e}")


def get_source_text(node: Node) -> str:
    """Extract source text for a node"""
    return node.text.decode("utf-8") if node.text else ""


def _postorder(node: Node) -> Iterator[Tuple[Node, bool]]:
    """Yield (node, children_done) pairs: each node once before and once after
    its children, without recursion (expressions can nest thousands deep)."""
    stack = [(node, False)]
    while stack:
        current, children_done = stack.pop()
        yield current, children_done
        if not children_done:
            stack.append((current, True))
            stack.extend((child, False) for child in reversed(current.children))


def ast_to_json(node: Node) -> Dict[str, Any]:
    """The AST as nested plain dictionaries, for the web API, built without
    recursion."""
    built: Dict[int, Dict[str, Any]] = {}
    for current, children_done in _postorder(node):
        if not children_done:
            continue
        built[current.id] = {
            "id": current.id,
            "node_type": current.type,
            "start_point": {
                "row": current.start_point[0],
                "column": current.start_point[1],
            },
            "end_point": {"row": current.end_point[0], "column": current.end_point[1]},
            "start_byte": current.start_byte,
            "end_byte": current.end_byte,
            "text": get_source_text(current),
            "is_named": current.is_named,
            "children": [built.pop(child.id) for child in current.children],
        }
    return built[node.id]


def iter_ast_edges(node: Node, named_only: bool) -> Iterator[Tuple[Node, Node]]:
    """Yield (parent, child) pairs depth-first, without recursion: each child's
    pair comes right before the pairs of its own subtree."""

    def children(parent: Node) -> List[Node]:
        return [c for c in parent.children if c.is_named or not named_only]

    stack = [(node, child) for child in reversed(children(node))]
    while stack:
        parent, child = stack.pop()
        yield parent, child
        stack.extend((child, grandchild) for grandchild in reversed(children(child)))


def find_nodes_containing_position(
    node: Node, row: int, column: int, results: Optional[List[Node]] = None
) -> List[Node]:
    """Find all AST nodes that contain the given cursor position.

    Args:
        node: Root AST node to search from
        row: 0-based row number of cursor position
        column: 0-based column number of cursor position
        results: List to append results to

    Returns:
        List of AST nodes that contain the cursor position, in depth-first order
        from the root
    """
    if results is None:
        results = []

    stack = [node]
    while stack:
        current = stack.pop()
        start_row, start_col = current.start_point
        end_row, end_col = current.end_point
        if (row > start_row or (row == start_row and column >= start_col)) and (
            row < end_row or (row == end_row and column <= end_col)
        ):
            results.append(current)
            stack.extend(reversed(current.children))

    return results


def get_child_by_field_name(node: Node, *field_names: str) -> Optional[Node]:
    """Get the first child node with the specified field name."""
    child = None
    for part in field_names:
        child = node.child_by_field_name(part)
        if child is None:
            break
        node = child
    return child


def get_required_child_by_field_name(node: Node, *field_names: str) -> Node:
    """Get the first child node with the specified field name."""
    child = get_child_by_field_name(node, *field_names)
    if child is None:
        raise ValueError(f"Child with field names '{'.'.join(field_names)}' not found")
    return child


def get_child_by_type(node: Node, *field_names: str) -> Optional[Node]:
    """Get the first child node with the specified field name."""
    child = None
    for part in field_names:
        for current_child in node.children:
            if current_child.type == part:
                child = current_child
        if child is None:
            break
        node = child
    return child


def get_required_child_by_type(node: Node, *field_names: str) -> Node:
    """Get the first child node with the specified field name."""
    child = get_child_by_type(node, *field_names)
    if child is None:
        raise ValueError(f"Child with type '{'.'.join(field_names)}' not found")
    return child


def dfs(ast_node: Node, callback: Callable[[Node], Optional[str]]) -> List[str]:
    """Generic DFS traversal with a callback for AST node processing."""
    results = []
    if not ast_node:
        return results

    stack = [ast_node]
    while stack:
        current = stack.pop()

        result = callback(current)
        if result is not None:
            results.append(result)

        # Add children in reverse order for left-to-right traversal
        for child in reversed(current.children):
            stack.append(child)

    return results
