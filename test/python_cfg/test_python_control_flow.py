"""
Tests for Python control flow: if/elif/else, while, for, break, continue, and
loop else clauses.

Expected graphs are written as edge sets over node text. Join and loop-exit
nodes are spliced out by post-processing, so branches connect directly to the
next statement.
"""

import pytest
from cfg_helpers import (
    build_cfg,
    def_use_chains,
    edges,
    entry_names,
    node_by_text,
)

from tree_climber.cfg.cfg_types import NodeType

ENTRY = "ENTRY:<module>"
EXIT = "EXIT:<module>"


class TestIf:
    def test_if_without_else(self):
        cfg = build_cfg("x = 1\nif x > 0:\n    y = 2\nz = 3\n")

        assert edges(cfg) == {
            (ENTRY, "x = 1", None),
            ("x = 1", "x > 0", None),
            ("x > 0", "y = 2", "true"),
            ("x > 0", "z = 3", "false"),
            ("y = 2", "z = 3", None),
            ("z = 3", EXIT, None),
        }

    def test_if_else(self):
        cfg = build_cfg("if a:\n    b = 1\nelse:\n    b = 2\nc = b\n")

        assert edges(cfg) == {
            (ENTRY, "a", None),
            ("a", "b = 1", "true"),
            ("a", "b = 2", "false"),
            ("b = 1", "c = b", None),
            ("b = 2", "c = b", None),
            ("c = b", EXIT, None),
        }

    def test_elif_chain_with_else(self):
        cfg = build_cfg(
            "if a:\n    p = 1\nelif b:\n    p = 2\nelse:\n    p = 3\nq = p\n"
        )

        assert edges(cfg) == {
            (ENTRY, "a", None),
            ("a", "p = 1", "true"),
            ("a", "b", "false"),
            ("b", "p = 2", "true"),
            ("b", "p = 3", "false"),
            ("p = 1", "q = p", None),
            ("p = 2", "q = p", None),
            ("p = 3", "q = p", None),
            ("q = p", EXIT, None),
        }

    def test_elif_chain_without_else_falls_through_to_the_next_statement(self):
        cfg = build_cfg("if a:\n    p = 1\nelif b:\n    p = 2\nq = 3\n")

        assert edges(cfg) == {
            (ENTRY, "a", None),
            ("a", "p = 1", "true"),
            ("a", "b", "false"),
            ("b", "p = 2", "true"),
            ("b", "q = 3", "false"),
            ("p = 1", "q = 3", None),
            ("p = 2", "q = 3", None),
            ("q = 3", EXIT, None),
        }

    def test_nested_if(self):
        cfg = build_cfg("if a:\n    if b:\n        x = 1\n    y = 2\nz = 3\n")

        assert edges(cfg) == {
            (ENTRY, "a", None),
            ("a", "b", "true"),
            ("a", "z = 3", "false"),
            ("b", "x = 1", "true"),
            ("b", "y = 2", "false"),
            ("x = 1", "y = 2", None),
            ("y = 2", "z = 3", None),
            ("z = 3", EXIT, None),
        }

    def test_condition_and_branches_are_typed(self):
        cfg = build_cfg("if a:\n    x = 1\n")

        assert node_by_text(cfg, "a").node_type == NodeType.CONDITION

    def test_conditional_expression_stays_inside_its_statement(self):
        cfg = build_cfg("x = a if b else c\nelsewhere = x\n")

        assert edges(cfg) == {
            (ENTRY, "x = a if b else c", None),
            ("x = a if b else c", "elsewhere = x", None),
            ("elsewhere = x", EXIT, None),
        }


class TestWhile:
    def test_while(self):
        cfg = build_cfg("while n > 0:\n    n -= 1\ndone = n\n")

        assert edges(cfg) == {
            (ENTRY, "n > 0", None),
            ("n > 0", "n -= 1", "true"),
            ("n -= 1", "n > 0", None),
            ("n > 0", "done = n", "false"),
            ("done = n", EXIT, None),
        }
        assert node_by_text(cfg, "n > 0").node_type == NodeType.LOOP_HEADER

    def test_while_else_runs_when_the_condition_fails(self):
        cfg = build_cfg("while n > 0:\n    n -= 1\nelse:\n    e = 1\ndone = n\n")

        assert edges(cfg) == {
            (ENTRY, "n > 0", None),
            ("n > 0", "n -= 1", "true"),
            ("n -= 1", "n > 0", None),
            ("n > 0", "e = 1", "false"),
            ("e = 1", "done = n", None),
            ("done = n", EXIT, None),
        }

    def test_break_skips_the_else_clause(self):
        cfg = build_cfg(
            "while n > 0:\n"
            "    if n == 5:\n"
            "        break\n"
            "    n -= 1\n"
            "else:\n"
            "    e = 1\n"
            "done = n\n"
        )

        assert edges(cfg) == {
            (ENTRY, "n > 0", None),
            ("n > 0", "n == 5", "true"),
            ("n == 5", "break", "true"),
            ("n == 5", "n -= 1", "false"),
            ("n -= 1", "n > 0", None),
            ("break", "done = n", None),
            ("n > 0", "e = 1", "false"),
            ("e = 1", "done = n", None),
            ("done = n", EXIT, None),
        }

    def test_continue_returns_to_the_header(self):
        cfg = build_cfg("while a:\n    if b:\n        continue\n    c = 1\n")

        assert ("continue", "a", None) in edges(cfg)
        assert node_by_text(cfg, "continue").node_type == NodeType.CONTINUE


class TestFor:
    def test_for_with_tuple_target(self):
        cfg = build_cfg("for k, v in d.items():\n    s = k\n")

        header = node_by_text(cfg, "for k, v in d.items()")
        assert header.node_type == NodeType.LOOP_HEADER
        assert header.metadata.variable_definitions == ["k", "v"]
        assert header.metadata.variable_uses == ["d"]
        assert edges(cfg) == {
            (ENTRY, "for k, v in d.items()", None),
            ("for k, v in d.items()", "s = k", "true"),
            ("s = k", "for k, v in d.items()", None),
            ("for k, v in d.items()", EXIT, "false"),
        }

    def test_async_for_header_text(self):
        cfg = build_cfg("async def f(xs):\n    async for x in xs:\n        pass\n")

        assert node_by_text(cfg, "async for x in xs").node_type == NodeType.LOOP_HEADER

    def test_for_else_with_break_and_continue(self):
        cfg = build_cfg(
            "for x in xs:\n"
            "    if x:\n"
            "        continue\n"
            "    found = x\n"
            "    break\n"
            "else:\n"
            "    missing = 1\n"
        )

        assert edges(cfg) == {
            (ENTRY, "for x in xs", None),
            ("for x in xs", "x", "true"),
            ("x", "continue", "true"),
            ("x", "found = x", "false"),
            ("continue", "for x in xs", None),
            ("found = x", "break", None),
            ("break", EXIT, None),
            ("for x in xs", "missing = 1", "false"),
            ("missing = 1", EXIT, None),
        }

    def test_calls_in_the_iterable_link_to_the_function(self):
        cfg = build_cfg("def gen():\n    return []\n\nfor x in gen():\n    pass\n")

        assert ("for x in gen()", "ENTRY:gen", "function_call") in edges(cfg)


class TestNestedLoops:
    def test_break_targets_the_innermost_loop(self):
        cfg = build_cfg(
            "for a in xs:\n"
            "    for b in ys:\n"
            "        break\n"
            "    after_inner = 1\n"
            "done = 1\n"
        )

        assert edges(cfg) == {
            (ENTRY, "for a in xs", None),
            ("for a in xs", "for b in ys", "true"),
            ("for b in ys", "break", "true"),
            ("break", "after_inner = 1", None),
            ("for b in ys", "after_inner = 1", "false"),
            ("after_inner = 1", "for a in xs", None),
            ("for a in xs", "done = 1", "false"),
            ("done = 1", EXIT, None),
        }

    def test_break_in_an_inner_else_targets_the_outer_loop(self):
        cfg = build_cfg(
            "for a in xs:\n"
            "    for b in ys:\n"
            "        pass\n"
            "    else:\n"
            "        break\n"
            "done = 1\n"
        )

        assert edges(cfg) == {
            (ENTRY, "for a in xs", None),
            ("for a in xs", "for b in ys", "true"),
            ("for b in ys", "pass", "true"),
            ("pass", "for b in ys", None),
            ("for b in ys", "break", "false"),
            ("break", "done = 1", None),
            ("for a in xs", "done = 1", "false"),
            ("done = 1", EXIT, None),
        }

    def test_break_in_a_while_else_targets_the_outer_loop(self):
        cfg = build_cfg(
            "for a in xs:\n"
            "    while b:\n"
            "        pass\n"
            "    else:\n"
            "        break\n"
            "done = 1\n"
        )

        assert edges(cfg) == {
            (ENTRY, "for a in xs", None),
            ("for a in xs", "b", "true"),
            ("b", "pass", "true"),
            ("pass", "b", None),
            ("b", "break", "false"),
            ("break", "done = 1", None),
            ("for a in xs", "done = 1", "false"),
            ("done = 1", EXIT, None),
        }

    def test_continue_in_an_inner_else_targets_the_outer_loop(self):
        cfg = build_cfg(
            "for a in xs:\n"
            "    for b in ys:\n"
            "        pass\n"
            "    else:\n"
            "        continue\n"
            "    unreachable = 1\n"
        )

        assert ("continue", "for a in xs", None) in edges(cfg)
        assert node_by_text(cfg, "unreachable = 1").predecessors == set()

    def test_return_inside_a_loop_jumps_to_the_function_exit(self):
        cfg = build_cfg(
            "def f(xs):\n"
            "    for x in xs:\n"
            "        if x:\n"
            "            return x\n"
            "    return None\n"
        )

        assert edges(cfg) == {
            ("ENTRY:f", "for x in xs", None),
            ("for x in xs", "x", "true"),
            ("x", "return x", "true"),
            ("x", "for x in xs", "false"),
            ("return x", "EXIT:f", None),
            ("for x in xs", "return None", "false"),
            ("return None", "EXIT:f", None),
        }


class TestJumpsOutsideLoops:
    @pytest.mark.parametrize("keyword", ["break", "continue"])
    def test_jump_outside_a_loop_does_not_raise_and_has_no_successor(self, keyword):
        cfg = build_cfg(f"{keyword}\nx = 1\n")

        assert edges(cfg) == {
            (ENTRY, keyword, None),
            ("x = 1", EXIT, None),
        }


class TestNestedFunctionDefinitions:
    def test_nested_def_is_one_statement_and_does_not_splice_its_body(self):
        cfg = build_cfg("def f():\n    def g():\n        pass\n    x = 1\n")

        nested = "def g():\n        pass"
        assert entry_names(cfg) == ["f"]
        assert edges(cfg) == {
            ("ENTRY:f", nested, None),
            (nested, "x = 1", None),
            ("x = 1", "EXIT:f", None),
        }

    def test_def_inside_a_conditional_is_not_a_function_entry(self):
        cfg = build_cfg("if a:\n    def g():\n        pass\n")

        assert entry_names(cfg) == ["<module>"]


class TestLoopCarriedDataflow:
    def test_accumulator_depends_on_itself_across_iterations(self):
        code = (
            "def f(xs):\n"
            "    total = 0\n"
            "    for x in xs:\n"
            "        total += x\n"
            "    return total\n"
        )

        assert def_use_chains(code, "total") == {
            "total = 0": ["return total", "total += x"],
            "total += x": ["return total", "total += x"],
        }
        assert def_use_chains(code, "x") == {"for x in xs": ["total += x"]}
        assert def_use_chains(code, "xs") == {"ENTRY:f": ["for x in xs"]}

    def test_while_counter(self):
        code = "def f(n):\n    while n > 0:\n        n -= 1\n    return n\n"

        assert def_use_chains(code, "n") == {
            "ENTRY:f": ["n -= 1", "n > 0", "return n"],
            "n -= 1": ["n -= 1", "n > 0", "return n"],
        }

    def test_branches_merge(self):
        code = (
            "def f(c):\n"
            "    if c:\n"
            "        v = 1\n"
            "    else:\n"
            "        v = 2\n"
            "    return v\n"
        )

        assert def_use_chains(code, "v") == {
            "v = 1": ["return v"],
            "v = 2": ["return v"],
        }
        assert def_use_chains(code, "c") == {"ENTRY:f": ["c"]}
