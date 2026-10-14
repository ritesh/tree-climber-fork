"""Control dependence from post-dominators, for each construct that branches."""

from typing import Dict, List, Tuple

from tree_climber.cfg.builder import CFGBuilder
from tree_climber.dataflow.control_dependence import control_dependence


def controllers(language: str, source: str) -> Dict[str, List[Tuple[str, str]]]:
    """Each node's first line, mapped to the (branch, label) pairs it depends on."""
    builder = CFGBuilder(language)
    builder.setup_parser()
    cfg = builder.build_cfg(source)
    result = control_dependence(cfg)

    def text(node_id: int) -> str:
        node = cfg.nodes[node_id]
        return (
            node.source_text.splitlines()[0]
            if node.source_text
            else node.node_type.name
        )

    found = {
        text(node): [(text(branch), label) for branch, label in pairs]
        for node, pairs in result.controllers.items()
    }
    for node, dependents in result.dependents.items():
        for dependent in dependents:
            assert any(b == node for b, _ in result.controllers[dependent])
    return found


class TestPython:
    def test_if_else_and_nesting(self):
        found = controllers(
            "python",
            "def f(x, c):\n"
            "    y = 0\n"
            "    if x:\n"
            "        y = 1\n"
            "        if c:\n"
            "            y = 2\n"
            "    else:\n"
            "        y = 3\n"
            "    return y\n",
        )

        assert found == {
            "y = 1": [("x", "true")],
            "c": [("x", "true")],
            "y = 2": [("c", "true")],
            "y = 3": [("x", "false")],
        }

    def test_an_early_return_decides_what_follows(self):
        found = controllers(
            "python",
            "def f(x):\n    if x:\n        return 1\n    y = 2\n    return y\n",
        )

        assert found == {
            "return 1": [("x", "true")],
            "y = 2": [("x", "false")],
            "return y": [("x", "false")],
        }

    def test_while_depends_on_itself(self):
        found = controllers(
            "python", "def f(n):\n    while n:\n        n = n - 1\n    return n\n"
        )

        assert found == {"n": [("n", "true")], "n = n - 1": [("n", "true")]}

    def test_for_else_and_break(self):
        found = controllers(
            "python",
            "def f(xs):\n"
            "    for i in xs:\n"
            "        if i:\n"
            "            break\n"
            "    else:\n"
            "        w = 2\n"
            "    return 1\n",
        )

        assert found == {
            "for i in xs": [("i", "false")],
            "i": [("for i in xs", "true")],
            "break": [("i", "true")],
            "w = 2": [("for i in xs", "false")],
        }

    def test_match_cases(self):
        found = controllers(
            "python",
            "def f(c):\n"
            "    match c:\n"
            "        case 1:\n"
            "            v = 1\n"
            "        case _:\n"
            "            v = 2\n"
            "    return v\n",
        )

        assert found == {
            "v = 1": [("case 1", "true")],
            "case _": [("case 1", "false")],
            "v = 2": [("case 1", "false")],
        }

    def test_try_finally_follows_exception_edges(self):
        found = controllers(
            "python",
            "def f(x):\n    try:\n        y = g(x)\n    finally:\n        z = 1\n    return y\n",
        )

        assert found == {
            "y = g(x)": [("f", "flow")],
            "return y": [("z = 1", "flow")],
        }

    def test_a_loop_that_never_exits(self):
        found = controllers("python", "def f():\n    while True:\n        g()\n")

        assert found == {"True": [("True", "true")], "g()": [("True", "true")]}

    def test_straight_line_code_has_none(self):
        assert controllers("python", "x = 1\ny = x\n") == {}

    def test_calls_do_not_branch(self):
        found = controllers(
            "python",
            "def g(a):\n    if a:\n        return 1\n    return 2\n\n\n"
            "def f():\n    y = g(1)\n    return y\n",
        )

        assert found == {"return 1": [("a", "true")], "return 2": [("a", "false")]}


class TestCAndJava:
    def test_c_switch_with_fall_through(self):
        found = controllers(
            "c",
            "int f(int c) { int v = 0; switch (c) { case 1: v = 1; break; "
            "case 2: v = 2; default: v = 3; } return v; }",
        )

        assert found == {
            "v = 1;": [("(c)", "1")],
            "break;": [("(c)", "1")],
            "v = 2;": [("(c)", "2")],
            "v = 3;": [("(c)", "2"), ("(c)", "default")],
        }

    def test_c_do_while(self):
        found = controllers("c", "int f(int v) { do { v--; } while (v); return v; }")

        assert found == {"v--;": [("(v)", "true")], "(v)": [("(v)", "true")]}

    def test_java_switch_and_for(self):
        found = controllers(
            "java",
            "class A { int f(int c) { int v = 0; switch (c) { case 1: v = 1; break; "
            "default: v = 3; } for (int i = 0; i < c; i++) { v++; } return v; } }",
        )

        assert found == {
            "v = 1;": [("(c)", "1")],
            "break;": [("(c)", "1")],
            "v = 3;": [("(c)", "default")],
            "i < c": [("i < c", "true")],
            "v++;": [("i < c", "true")],
            "i++": [("i < c", "true")],
        }
