"""
Tests for Python exceptions and context managers: try/except/else/finally,
raise, with, and routing return/break/continue through finally.

Exception edges are labeled "exception" and leave from the state *before* a
statement that may raise, so they appear to come from the preceding node.
"""

import pytest
from cfg_helpers import build_cfg, def_use_chains, edges, node_by_text

from tree_climber.cfg.cfg_types import NodeType

ENTRY = "ENTRY:<module>"
EXIT = "EXIT:<module>"


class TestTryExcept:
    def test_handler_is_reached_from_the_state_before_the_raising_statement(self):
        cfg = build_cfg(
            "x = 0\n"
            "try:\n"
            "    x = int(s)\n"
            "except ValueError as e:\n"
            "    print(x)\n"
            "done = 1\n"
        )

        assert edges(cfg) == {
            (ENTRY, "x = 0", None),
            ("x = 0", "x = int(s)", None),
            ("x = 0", "except ValueError as e", "exception"),
            ("x = int(s)", "done = 1", None),
            ("except ValueError as e", "print(x)", "true"),
            ("except ValueError as e", EXIT, "false"),
            ("print(x)", "done = 1", None),
            ("done = 1", EXIT, None),
        }

    def test_handler_sees_the_old_definition_not_the_one_that_never_completed(self):
        code = "x = 0\ntry:\n    x = int(s)\nexcept ValueError:\n    print(x)\n"

        assert def_use_chains(code, "x") == {"x = 0": ["print(x)"]}

    def test_handler_sees_progress_made_before_the_failure(self):
        code = "try:\n    a = 1\n    b = f()\nexcept E:\n    use(a)\n"
        cfg = build_cfg(code)

        assert edges(cfg) == {
            (ENTRY, "a = 1", None),
            ("a = 1", "b = f()", None),
            (ENTRY, "except E", "exception"),
            ("a = 1", "except E", "exception"),
            ("b = f()", EXIT, None),
            ("except E", "use(a)", "true"),
            ("except E", EXIT, "false"),
            ("use(a)", EXIT, None),
        }
        assert def_use_chains(code, "a") == {"a = 1": ["use(a)"]}

    def test_else_runs_after_the_body_and_is_not_covered_by_the_handlers(self):
        cfg = build_cfg("try:\n    a = 1\nexcept E:\n    b = 2\nelse:\n    c = 3\n")

        assert edges(cfg) == {
            (ENTRY, "a = 1", None),
            (ENTRY, "except E", "exception"),
            ("a = 1", "c = 3", None),
            ("except E", "b = 2", "true"),
            ("except E", EXIT, "false"),
            ("b = 2", EXIT, None),
            ("c = 3", EXIT, None),
        }

    def test_handlers_are_a_chain_of_tests(self):
        cfg = build_cfg(
            "try:\n    a = f()\nexcept A:\n    p = 1\nexcept (B, C) as e:\n    q = 2\n"
        )

        assert edges(cfg) == {
            (ENTRY, "a = f()", None),
            (ENTRY, "except A", "exception"),
            ("a = f()", EXIT, None),
            ("except A", "p = 1", "true"),
            ("except A", "except (B, C) as e", "false"),
            ("except (B, C) as e", "q = 2", "true"),
            ("except (B, C) as e", EXIT, "false"),
            ("p = 1", EXIT, None),
            ("q = 2", EXIT, None),
        }
        assert node_by_text(cfg, "except A").node_type == NodeType.CONDITION

    def test_bare_except_catches_everything(self):
        cfg = build_cfg("try:\n    a = f()\nexcept:\n    b = 1\n")

        assert edges(cfg) == {
            (ENTRY, "a = f()", None),
            (ENTRY, "b = 1", "exception"),
            ("a = f()", EXIT, None),
            ("b = 1", EXIT, None),
        }

    def test_except_star_is_modeled_like_except(self):
        cfg = build_cfg("try:\n    a = f()\nexcept* ValueError as eg:\n    b = eg\n")

        header = node_by_text(cfg, "except* ValueError as eg")
        assert header.node_type == NodeType.CONDITION
        assert header.metadata.variable_definitions == ["eg"]
        assert ("except* ValueError as eg", "b = eg", "true") in edges(cfg)

    def test_handler_header_defines_the_name_and_uses_the_type(self):
        cfg = build_cfg("try:\n    a = f()\nexcept ValueError as e:\n    b = e\n")

        header = node_by_text(cfg, "except ValueError as e")
        assert header.metadata.variable_definitions == ["e"]
        assert header.metadata.variable_uses == ["ValueError"]

    def test_code_after_a_try_where_every_path_returns_is_unreachable(self):
        cfg = build_cfg(
            "def f():\n    try:\n        return 1\n    finally:\n        pass\n    x = 1\n"
        )

        assert node_by_text(cfg, "x = 1").predecessors == set()


class TestRaise:
    def test_raise_is_caught_by_the_handler(self):
        cfg = build_cfg(
            'try:\n    raise ValueError("x")\nexcept ValueError as e:\n    h = e\n'
        )

        assert edges(cfg) == {
            (ENTRY, 'raise ValueError("x")', None),
            ('raise ValueError("x")', "except ValueError as e", "exception"),
            ("except ValueError as e", "h = e", "true"),
            ("except ValueError as e", EXIT, "false"),
            ("h = e", EXIT, None),
        }

    def test_uncaught_raise_goes_to_the_function_exit(self):
        cfg = build_cfg("def f():\n    raise E\n    x = 1\n")

        assert edges(cfg) == {
            ("ENTRY:f", "raise E", None),
            ("raise E", "EXIT:f", "exception"),
            ("x = 1", "EXIT:f", None),
        }
        assert node_by_text(cfg, "x = 1").predecessors == set()

    def test_unmatched_exception_propagates_to_the_outer_handler(self):
        cfg = build_cfg(
            "try:\n"
            "    try:\n"
            "        a = f()\n"
            "    except A:\n"
            "        pass\n"
            "except B:\n"
            "    b = 1\n"
        )

        assert edges(cfg) == {
            (ENTRY, "a = f()", None),
            (ENTRY, "except A", "exception"),
            ("a = f()", EXIT, None),
            ("except A", "pass", "true"),
            ("except A", "except B", "false"),
            ("pass", EXIT, None),
            ("except B", "b = 1", "true"),
            ("except B", EXIT, "false"),
            ("b = 1", EXIT, None),
        }

    def test_exception_in_a_handler_body_propagates_to_the_outer_handler(self):
        cfg = build_cfg(
            "try:\n"
            "    try:\n"
            "        a = f()\n"
            "    except A:\n"
            "        b = g()\n"
            "        d = h()\n"
            "except B:\n"
            "    c = 1\n"
        )

        assert ("b = g()", "except B", "exception") in edges(cfg)


class TestFinally:
    def test_try_finally_normal_flow(self):
        cfg = build_cfg("try:\n    a = 1\nfinally:\n    b = 2\nc = 3\n")

        assert edges(cfg) == {
            (ENTRY, "a = 1", None),
            (ENTRY, "b = 2", "exception"),
            ("a = 1", "b = 2", None),
            ("b = 2", "c = 3", None),
            ("b = 2", EXIT, "exception"),
            ("c = 3", EXIT, None),
        }

    def test_all_clauses_with_finally(self):
        cfg = build_cfg(
            "try:\n"
            "    a = 1\n"
            "except E:\n"
            "    b = 2\n"
            "else:\n"
            "    c = 3\n"
            "finally:\n"
            "    d = 4\n"
            "e = 5\n"
        )

        assert edges(cfg) == {
            (ENTRY, "a = 1", None),
            (ENTRY, "except E", "exception"),
            ("a = 1", "c = 3", None),
            ("a = 1", "d = 4", "exception"),
            ("except E", "b = 2", "true"),
            ("except E", "d = 4", "false"),
            ("b = 2", "d = 4", None),
            ("c = 3", "d = 4", None),
            ("d = 4", "e = 5", None),
            ("d = 4", EXIT, "exception"),
            ("e = 5", EXIT, None),
        }

    def test_return_in_try_runs_finally_first(self):
        cfg = build_cfg(
            "def f():\n    try:\n        return a()\n    finally:\n        cleanup()\n"
        )

        assert edges(cfg) == {
            ("ENTRY:f", "return a()", None),
            ("ENTRY:f", "cleanup()", "exception"),
            ("return a()", "cleanup()", None),
            ("cleanup()", "EXIT:f", "return"),
        }

    def test_return_in_a_handler_runs_finally_first(self):
        found = edges(
            build_cfg(
                "def f():\n"
                "    try:\n"
                "        a()\n"
                "    except E:\n"
                "        return 1\n"
                "    finally:\n"
                "        cleanup()\n"
            )
        )

        assert ("return 1", "cleanup()", None) in found
        assert ("cleanup()", "EXIT:f", "return") in found
        assert ("return 1", "EXIT:f", None) not in found

    def test_both_the_normal_path_and_a_return_pass_through_finally(self):
        found = edges(
            build_cfg(
                "def f(c):\n"
                "    try:\n"
                "        if c:\n"
                "            return 1\n"
                "        a()\n"
                "    finally:\n"
                "        cleanup()\n"
                "    b()\n"
            )
        )

        assert ("return 1", "cleanup()", None) in found
        assert ("a()", "cleanup()", None) in found
        assert ("cleanup()", "EXIT:f", "return") in found
        assert ("cleanup()", "b()", None) in found

    def test_return_passes_through_nested_finally_blocks_innermost_first(self):
        found = edges(
            build_cfg(
                "def f():\n"
                "    try:\n"
                "        try:\n"
                "            return 1\n"
                "        finally:\n"
                "            a()\n"
                "    finally:\n"
                "        b()\n"
            )
        )

        assert ("return 1", "a()", None) in found
        assert ("a()", "b()", "return") in found
        assert ("b()", "EXIT:f", "return") in found
        assert ("return 1", "EXIT:f", None) not in found
        assert ("a()", "EXIT:f", "return") not in found

    def test_break_in_try_runs_finally_then_leaves_the_loop(self):
        cfg = build_cfg(
            "for x in xs:\n"
            "    try:\n"
            "        break\n"
            "    finally:\n"
            "        cleanup()\n"
            "done = 1\n"
        )

        found = edges(cfg)
        assert ("break", "cleanup()", None) in found
        assert ("cleanup()", "done = 1", "break") in found
        assert ("break", "done = 1", None) not in found

    def test_continue_in_try_runs_finally_then_loops_back(self):
        found = edges(
            build_cfg(
                "for x in xs:\n"
                "    try:\n"
                "        continue\n"
                "    finally:\n"
                "        cleanup()\n"
            )
        )

        assert ("continue", "cleanup()", None) in found
        assert ("cleanup()", "for x in xs", "continue") in found

    def test_a_loop_inside_try_finally_does_not_route_break_through_finally(self):
        found = edges(
            build_cfg(
                "def f(xs):\n"
                "    try:\n"
                "        for x in xs:\n"
                "            break\n"
                "    finally:\n"
                "        cleanup()\n"
            )
        )

        assert not any(label == "break" for _, _, label in found)
        assert ("break", "cleanup()", None) in found

    def test_break_with_handlers_but_no_finally_goes_straight_to_the_loop_exit(self):
        found = edges(
            build_cfg(
                "for x in xs:\n"
                "    try:\n"
                "        break\n"
                "    except E:\n"
                "        pass\n"
                "done = 1\n"
            )
        )

        assert ("break", "done = 1", None) in found


class TestWith:
    def test_with_has_an_exit_node_on_the_normal_path(self):
        cfg = build_cfg("with open(f) as fh:\n    data = fh.read()\ndone = 1\n")

        assert edges(cfg) == {
            (ENTRY, "with open(f) as fh", None),
            ("with open(f) as fh", "data = fh.read()", None),
            ("with open(f) as fh", "__exit__", "exception"),
            ("data = fh.read()", "__exit__", None),
            ("__exit__", "done = 1", None),
            ("__exit__", EXIT, "exception"),
            ("done = 1", EXIT, None),
        }

    def test_return_in_with_runs_the_exit_first(self):
        cfg = build_cfg("def f():\n    with lock:\n        return x\n")

        assert edges(cfg) == {
            ("ENTRY:f", "with lock", None),
            ("with lock", "return x", None),
            ("with lock", "__exit__", "exception"),
            ("return x", "__exit__", None),
            ("__exit__", "EXIT:f", "return"),
        }

    def test_break_in_with_runs_the_exit_first(self):
        found = edges(
            build_cfg("for x in xs:\n    with lock:\n        break\ndone = 1\n")
        )

        assert ("break", "__exit__", None) in found
        assert ("__exit__", "done = 1", "break") in found

    def test_async_with_and_multiple_items(self):
        cfg = build_cfg("async def f():\n    async with a as x, b():\n        pass\n")

        assert (
            node_by_text(cfg, "async with a as x, b()").node_type == NodeType.STATEMENT
        )

    def test_async_with_exits_through_aexit(self):
        cfg = build_cfg("async def f():\n    async with a:\n        x = 1\n    y = 2\n")

        found = edges(cfg)
        assert ("x = 1", "__aexit__", None) in found
        assert ("__aexit__", "y = 2", None) in found
        assert not any("__exit__" in (s, t) for s, t, _ in found)

    def test_with_target_is_defined_by_the_header(self):
        code = (
            "def f(p):\n"
            "    with open(p) as fh:\n"
            "        data = fh.read()\n"
            "    return data\n"
        )

        assert def_use_chains(code, "fh") == {
            "with open(p) as fh": ["data = fh.read()"]
        }
        assert def_use_chains(code, "data") == {"data = fh.read()": ["return data"]}
        assert def_use_chains(code, "p") == {"ENTRY:f": ["with open(p) as fh"]}

    def test_exception_in_the_body_runs_the_exit_before_the_handler(self):
        found = edges(
            build_cfg("try:\n    with lock:\n        a = f()\nexcept E:\n    b = 1\n")
        )

        assert ("__exit__", "except E", "exception") in found


class TestNoMarkersRemain:
    @pytest.mark.parametrize(
        "code",
        [
            "try:\n    a = 1\nexcept E:\n    b = 2\nelse:\n    c = 3\nfinally:\n    d = 4\n",
            "def f():\n    try:\n        return 1\n    finally:\n        pass\n",
            "with a:\n    pass\n",
        ],
    )
    def test_try_and_finally_marker_nodes_are_spliced_out(self, code):
        cfg = build_cfg(code)

        assert not any(
            node.source_text.startswith(("ENTRY: ", "EXIT: "))
            for node in cfg.nodes.values()
        )
