"""
Tests for the Python `match` statement.

Expected graphs are edge sets over node text. A case is a test node (`case ...`)
whose `true` edge enters the body, through a `capture` node when the pattern binds
names, and through an `if ...` guard node when there is a guard. Its `false` edge
tries the next case, or skips the match when no case is irrefutable.
"""

import pytest
from cfg_helpers import (
    build_cfg,
    def_use_chains,
    edges,
    node_by_text,
    reachable_from,
)

from tree_climber.ast_utils import parse_source_to_ast
from tree_climber.cfg.cfg_types import NodeType
from tree_climber.cfg.languages.python_bindings import (
    collect_pattern_bindings,
    is_irrefutable_pattern,
)

ENTRY = "ENTRY:<module>"
EXIT = "EXIT:<module>"


class TestShape:
    def test_cases_without_an_irrefutable_one_can_skip_the_match(self):
        cfg = build_cfg(
            "match x:\n    case 1:\n        a = 1\n    case 2:\n        a = 2\nz = 0\n"
        )

        assert edges(cfg) == {
            (ENTRY, "match x", None),
            ("match x", "case 1", None),
            ("case 1", "a = 1", "true"),
            ("case 1", "case 2", "false"),
            ("case 2", "a = 2", "true"),
            ("case 2", "z = 0", "false"),
            ("a = 1", "z = 0", None),
            ("a = 2", "z = 0", None),
            ("z = 0", EXIT, None),
        }

    def test_a_wildcard_case_catches_everything(self):
        cfg = build_cfg(
            "match x:\n    case 1:\n        a = 1\n    case _:\n        a = 2\nz = 0\n"
        )

        assert edges(cfg) == {
            (ENTRY, "match x", None),
            ("match x", "case 1", None),
            ("case 1", "a = 1", "true"),
            ("case 1", "case _", "false"),
            ("case _", "a = 2", "true"),
            ("a = 1", "z = 0", None),
            ("a = 2", "z = 0", None),
            ("z = 0", EXIT, None),
        }

    def test_the_subject_is_evaluated_once_by_the_head(self):
        cfg = build_cfg(
            "match f(x):\n    case 1:\n        pass\n    case 2:\n        pass\n"
        )

        head = node_by_text(cfg, "match f(x)")
        assert head.node_type == NodeType.SWITCH_HEAD
        assert head.metadata.function_calls == ["f"]
        assert head.metadata.variable_uses == ["f", "x"]
        assert len(cfg.nodes[min(head.successors)].predecessors) == 1

    def test_cases_do_not_fall_through(self):
        cfg = build_cfg(
            "match x:\n    case 1:\n        a = 1\n    case _:\n        a = 2\n"
        )

        assert not any(
            source == "a = 1" and target in ("case _", "a = 2")
            for source, target, _ in edges(cfg)
        )

    def test_multi_statement_bodies_and_nesting(self):
        cfg = build_cfg(
            "match x:\n"
            "    case 1:\n"
            "        match y:\n"
            "            case 2:\n"
            "                a = 1\n"
            "        b = 2\n"
            "    case _:\n"
            "        b = 3\n"
        )

        found = edges(cfg)
        assert ("case 2", "a = 1", "true") in found
        assert ("case 2", "b = 2", "false") in found
        assert ("a = 1", "b = 2", None) in found
        assert ("case 1", "match y", "true") in found

    def test_the_test_node_for_several_patterns_keeps_their_text(self):
        cfg = build_cfg("match p:\n    case 1, 2:\n        pass\n")

        assert ("match p", "case 1, 2", None) in edges(cfg)

    def test_comments_between_cases_are_skipped(self):
        cfg = build_cfg(
            "match x:\n    # first\n    case 1:\n        pass\n    # last\n    case _:\n        pass\n"
        )

        assert ("case 1", "case _", "false") in edges(cfg)


class TestGuards:
    def test_a_guard_is_its_own_condition(self):
        cfg = build_cfg(
            "match x:\n    case n if n > 0:\n        a = n\n    case _:\n        a = 0\nz = a\n"
        )

        assert edges(cfg) == {
            (ENTRY, "match x", None),
            ("match x", "case n", None),
            ("case n", "capture n", "true"),
            ("case n", "case _", "false"),
            ("capture n", "if n > 0", None),
            ("if n > 0", "a = n", "true"),
            ("if n > 0", "case _", "false"),
            ("case _", "a = 0", "true"),
            ("a = n", "z = a", None),
            ("a = 0", "z = a", None),
            ("z = a", EXIT, None),
        }
        assert node_by_text(cfg, "if n > 0").node_type == NodeType.CONDITION

    def test_a_guarded_wildcard_is_not_irrefutable(self):
        cfg = build_cfg("match x:\n    case _ if ok():\n        a = 1\nz = 0\n")

        found = edges(cfg)
        assert ("case _", "if ok()", "true") in found
        assert ("case _", "z = 0", "false") in found
        assert ("if ok()", "a = 1", "true") in found
        assert ("if ok()", "z = 0", "false") in found

    def test_a_guard_can_call_functions(self):
        cfg = build_cfg("match x:\n    case n if big(n):\n        pass\n")

        assert node_by_text(cfg, "if big(n)").metadata.function_calls == ["big"]

    def test_a_guard_sees_the_captured_names(self):
        chains = def_use_chains(
            "match x:\n    case [a, b] if a > b:\n        pass\n", "a"
        )

        assert chains == {"capture a, b": ["if a > b"]}


class TestCaptures:
    def test_captures_define_names_for_the_body(self):
        chains = def_use_chains(
            "match cmd:\n    case [first, *rest]:\n        a = first\n        b = rest\n",
            "rest",
        )

        assert chains == {"capture first, rest": ["b = rest"]}

    def test_a_failed_match_does_not_kill_earlier_definitions(self):
        code = "x = 0\nmatch s:\n    case [x]:\n        pass\nprint(x)\n"

        assert def_use_chains(code, "x") == {
            "x = 0": ["print(x)"],
            "capture x": ["print(x)"],
        }

    def test_a_pattern_without_captures_has_no_capture_node(self):
        cfg = build_cfg("match x:\n    case 1 | 2:\n        pass\n")

        assert not any("capture" in node.source_text for node in cfg.nodes.values())

    def test_a_guard_failure_keeps_the_captured_value(self):
        code = (
            "match s:\n    case y if y > 0:\n        pass\n    case _:\n        w = y\n"
        )

        assert def_use_chains(code, "y") == {
            "capture y": ["if y > 0", "w = y"],
        }

    def test_the_subject_is_a_use(self):
        chains = def_use_chains("v = f()\nmatch v:\n    case 1:\n        pass\n", "v")

        assert chains == {"v = f()": ["match v"]}


class TestJumps:
    def test_break_and_continue_target_the_enclosing_loop(self):
        cfg = build_cfg(
            "for item in items:\n"
            "    match item:\n"
            "        case 1:\n"
            "            break\n"
            "        case 2:\n"
            "            continue\n"
            "        case _:\n"
            "            seen = item\n"
            "done = 1\n"
        )

        found = edges(cfg)
        assert ("break", "done = 1", None) in found
        assert ("continue", "for item in items", None) in found
        assert ("seen = item", "for item in items", None) in found

    def test_return_inside_a_case_leaves_the_function(self):
        cfg = build_cfg(
            "def f(x):\n"
            "    match x:\n"
            "        case 1:\n"
            "            return 1\n"
            "    return 0\n"
        )

        found = edges(cfg)
        assert ("return 1", "EXIT:f", None) in found
        assert ("case 1", "return 0", "false") in found

    def test_all_cases_returning_leaves_nothing_after_the_match(self):
        cfg = build_cfg(
            "def f(x):\n"
            "    match x:\n"
            "        case 1:\n"
            "            return 1\n"
            "        case _:\n"
            "            return 2\n"
            "    unreachable = 0\n"
        )

        reachable = reachable_from(cfg, cfg.entry_node_ids[0])
        assert node_by_text(cfg, "unreachable = 0").id not in reachable


class TestExceptions:
    def test_the_subject_may_raise_but_case_tests_do_not(self):
        cfg = build_cfg(
            "try:\n"
            "    match f():\n"
            "        case 1:\n"
            "            pass\n"
            "except ValueError:\n"
            "    h()\n"
        )

        found = edges(cfg)
        assert (ENTRY, "except ValueError", "exception") in found
        assert ("match f()", "except ValueError", "exception") not in found
        assert ("case 1", "except ValueError", "exception") not in found

    def test_a_capture_cannot_raise(self):
        cfg = build_cfg(
            "try:\n"
            "    match x:\n"
            "        case [n]:\n"
            "            pass\n"
            "except ValueError:\n"
            "    h()\n"
        )

        assert ("case [n]", "except ValueError", "exception") not in edges(cfg)

    def test_a_guard_may_raise(self):
        cfg = build_cfg(
            "try:\n"
            "    match x:\n"
            "        case n if f(n):\n"
            "            pass\n"
            "except ValueError:\n"
            "    h()\n"
        )

        assert ("capture n", "except ValueError", "exception") in edges(cfg)


class TestHalfTypedCode:
    @pytest.mark.parametrize(
        "source",
        [
            "match x:\n",
            "match x:\n    case\n",
            "match x:\n    case 1:\n",
            "match x:\n    case 1 if\n",
            "match\n",
        ],
    )
    def test_incomplete_matches_still_build_a_graph(self, source):
        cfg = build_cfg(source)

        assert cfg.entry_node_ids


def patterns_of(pattern: str):
    root = parse_source_to_ast(
        f"match s:\n    case {pattern}:\n        pass\n", "python"
    )
    match_statement = root.root_node.children[0]
    clause = match_statement.child_by_field_name("body").named_children[0]
    return [c for c in clause.named_children if c.type == "case_pattern"]


@pytest.mark.parametrize(
    "pattern, definitions, uses",
    [
        ("1", [], []),
        ("'s' | 4 | None", [], []),
        ("-1", [], []),
        ("_", [], []),
        ("name", ["name"], []),
        ("[a, *rest]", ["a", "rest"], []),
        ("[*_]", [], []),
        ("[a, _]", ["a"], []),
        ("[*_, x]", ["x"], []),
        ("{1: _}", [], []),
        ("(a, b)", ["a", "b"], []),
        ('{"k": v, **kw}', ["kw", "v"], []),
        ("{Key.K: v}", ["v"], ["Key"]),
        ("Point(x=px, y=0)", ["px"], ["Point"]),
        ("mod.Cls(a, b=Color.RED)", ["a"], ["Color", "mod"]),
        ("Color.RED", [], ["Color"]),
        ("a.b.c", [], ["a"]),
        ("[1, 2] as pair", ["pair"], []),
        ("Point(x=px) | Other(px) as pt", ["pt", "px"], ["Other", "Point"]),
        ("case_x", ["case_x"], []),
    ],
)
def test_pattern_bindings(pattern, definitions, uses):
    bindings = collect_pattern_bindings(patterns_of(pattern))

    assert sorted(bindings.definitions) == definitions
    assert sorted(bindings.uses) == uses


@pytest.mark.parametrize(
    "pattern, expected",
    [
        ("_", True),
        ("name", True),
        ("(name)", True),
        ("((name))", True),
        ("_ as other", True),
        ("1 | name", True),
        ("[a]", False),
        ("(name,)", False),
        ("1", False),
        ("Color.RED", False),
        ("Point()", False),
        ("1 | 2", False),
        ("{}", False),
    ],
)
def test_irrefutable_patterns(pattern, expected):
    (node,) = patterns_of(pattern)

    assert is_irrefutable_pattern(node) is expected


def test_case_test_nodes_define_nothing_and_use_only_what_the_pattern_reads():
    cfg = build_cfg("match s:\n    case [a, b]:\n        pass\n")

    test_node = node_by_text(cfg, "case [a, b]")
    assert test_node.metadata.variable_definitions == []
    assert test_node.metadata.variable_uses == []
