"""
Tests built on the Python fixture files next to this one.

Each fixture documents its scenarios in its own header:
- nested_structures.py: control structures inside each other
- edge_cases.py: boundary conditions and unusual but valid code
- data_flow_patterns.py: def-use patterns, some shaped like source-to-sink flows
- basic_constructs.py is covered in test_python_cfg.py

Edges are compared by the first line of each node's text, restricted to one function
(see function_edges in cfg_helpers).
"""

from pathlib import Path
from typing import Set

import pytest
from cfg_helpers import (
    build_cfg,
    entry_names,
    function_chains,
    function_edges,
    reachable_from,
)

from tree_climber.cfg.visitor import CFG

HERE = Path(__file__).parent
FIXTURES = ["nested_structures", "edge_cases", "data_flow_patterns", "basic_constructs"]


def load(name: str) -> CFG:
    return build_cfg((HERE / f"{name}.py").read_text())


@pytest.fixture(scope="module")
def nested() -> CFG:
    return load("nested_structures")


@pytest.fixture(scope="module")
def cases() -> CFG:
    return load("edge_cases")


@pytest.fixture(scope="module")
def flows() -> CFG:
    return load("data_flow_patterns")


@pytest.mark.parametrize("name", FIXTURES)
class TestEveryFixture:
    def test_the_fixture_is_valid_python(self, name):
        compile((HERE / f"{name}.py").read_text(), name, "exec")

    def test_every_function_exit_is_reachable_from_its_entry(self, name):
        cfg = load(name)

        for entry_id, exit_id in zip(cfg.entry_node_ids, cfg.exit_node_ids):
            assert exit_id in reachable_from(cfg, entry_id)

    def test_entry_and_exit_lists_pair_up(self, name):
        cfg = load(name)

        assert len(cfg.entry_node_ids) == len(cfg.exit_node_ids)


class TestNestedStructures:
    def test_entries(self, nested):
        assert entry_names(nested) == [
            "<module>",
            "if_in_while",
            "while_in_if",
            "nested_for",
            "break_in_inner_else",
            "try_in_loop",
            "loop_in_try",
            "return_through_two_finallys",
            "with_in_loop",
            "match_in_loop",
            "nested_match",
            "deep_nesting",
            "Outer.method",
            "Outer.Inner.method",
            "closure_factory",
            "advance",
        ]

    def test_every_node_is_reachable_from_some_entry(self, nested):
        reachable: Set[int] = set()
        for entry_id in nested.entry_node_ids:
            reachable |= reachable_from(nested, entry_id)

        assert reachable == set(nested.nodes)

    def test_if_in_while_returns_both_branches_to_the_header(self, nested):
        found = function_edges(nested, "if_in_while")

        assert found >= {
            ("n > 0", "n % 2 == 0", "true"),
            ("n > 0", "return total", "false"),
            ("n % 2 == 0", "total = total + n", "true"),
            ("n % 2 == 0", "total = total - n", "false"),
            ("total = total + n", "n = n - 1", None),
            ("total = total - n", "n = n - 1", None),
            ("n = n - 1", "n > 0", None),
        }

    def test_while_in_if(self, nested):
        found = function_edges(nested, "while_in_if")

        assert ("n > 0", "n > 0", "true") in found
        assert ("n > 0", "n = 0", "false") in found
        assert ("n > 0", "return n", "false") in found
        assert ("n = 0", "return n", None) in found

    def test_nested_for_continue_and_break_stay_in_the_inner_loop(self, nested):
        found = function_edges(nested, "nested_for")

        assert ("continue", "for cell in row", None) in found
        assert ("break", "for row in rows", None) in found
        assert ("for cell in row", "for row in rows", "false") in found
        assert ("for row in rows", "return count", "false") in found

    def test_a_break_in_an_inner_else_leaves_the_outer_loop(self, nested):
        found = function_edges(nested, "break_in_inner_else")

        assert ("for cell in row", "break", "false") in found
        assert ("found = cell", "break", None) in found
        assert ("break", "for row in rows", None) in found
        assert ("break", "return found", None) in found

    def test_try_in_a_loop_routes_jumps_through_the_shared_finally(self, nested):
        found = function_edges(nested, "try_in_loop")

        assert ("break", "done = done + 1", None) in found
        assert ("continue", "done = done + 1", None) in found
        assert ("done = done + 1", "return done", "break") in found
        assert ("done = done + 1", "for item in items", "continue") in found
        assert ("done = done + 1", "use(value)", None) in found
        assert ("done = done + 1", "EXIT:try_in_loop", "exception") in found

    def test_a_loop_in_a_try_reaches_the_handler(self, nested):
        found = function_edges(nested, "loop_in_try")

        assert ("use(item)", "except KeyError", "exception") in found
        assert ("except KeyError", "return None", "true") in found
        assert ("except KeyError", "EXIT:loop_in_try", "false") in found

    def test_a_return_passes_through_both_finally_blocks_innermost_first(self, nested):
        found = function_edges(nested, "return_through_two_finallys")

        assert ("return read(path)", "close(path)", None) in found
        assert ("close(path)", "log(path)", "return") in found
        assert ("log(path)", "EXIT:return_through_two_finallys", "return") in found

    def test_with_in_a_loop(self, nested):
        found = function_edges(nested, "with_in_loop")

        assert ("return path", "__exit__", None) in found
        assert ("__exit__", "EXIT:with_in_loop", "return") in found
        assert ("__exit__", "for path in paths", None) in found

    def test_break_and_continue_in_cases_target_the_loop(self, nested):
        found = function_edges(nested, "match_in_loop")

        assert ("break", "return len(events)", None) in found
        assert ("continue", "for event in events", None) in found
        assert ("handle(kind, payload)", "for event in events", None) in found
        assert ("if payload", "case _", "false") in found

    def test_a_match_in_a_case_body(self, nested):
        found = function_edges(nested, "nested_match")

        assert ("case 1", "match b", "true") in found
        assert ("case 1", "case _", "false") in found
        assert ("case 2", 'return "both"', "true") in found
        assert ("case 2", "case _", "false") in found

    def test_deep_nesting(self, nested):
        found = function_edges(nested, "deep_nesting")

        assert ("for row in data", "row", "true") in found
        assert ("row", "result = result - 1", "false") in found
        assert ("row", "result = result + 1", "false") in found
        assert ("except IndexError", "break", "true") in found
        assert ("except IndexError", "EXIT:deep_nesting", "false") in found
        assert ("break", "for row in data", None) in found
        assert ("result = result + 1", "for row in data", None) in found

    def test_methods_of_nested_classes_are_separate_subgraphs(self, nested):
        assert ("flag", "return 1", "true") in function_edges(nested, "Outer.method")
        assert ("item", "return item", "true") in function_edges(
            nested, "Outer.Inner.method"
        )

    def test_a_returned_nested_function_has_its_own_loop(self, nested):
        assert ("return advance", "EXIT:closure_factory", None) in function_edges(
            nested, "closure_factory"
        )
        assert ("value = value + step", "value < limit", None) in function_edges(
            nested, "advance"
        )


class TestEdgeCases:
    def test_entries(self, cases):
        assert entry_names(cases) == [
            "<module>",
            "only_pass",
            "only_docstring",
            "unreachable_after_return",
            "while_true",
            "one_line_compound",
            "bare_raise",
            "return_in_finally",
            "empty_loop_bodies",
            "many_handlers",
            "chained_and_unpacking",
            "conditional_expressions",
            "delete_and_scope",
            "inner",
            "decorator_stack",
            "Decorated.method",
            "generators_and_async",
            "Slots.total",
        ]

    def test_only_code_after_a_return_or_raise_is_unreachable(self, cases):
        reachable: Set[int] = set()
        for entry_id in cases.entry_node_ids:
            reachable |= reachable_from(cases, entry_id)

        unreachable = {
            cases.nodes[node_id].source_text for node_id in set(cases.nodes) - reachable
        }
        assert unreachable == {"dead = 2", "dead_too = 3"}

    def test_a_body_of_only_pass_or_a_docstring_is_one_statement(self, cases):
        assert function_edges(cases, "only_pass") == {
            ("ENTRY:only_pass", "pass", None),
            ("pass", "EXIT:only_pass", None),
        }
        assert len(function_edges(cases, "only_docstring")) == 2

    def test_a_raise_ends_the_flow_with_an_exception_edge(self, cases):
        found = function_edges(cases, "unreachable_after_return")

        assert ("x", "return 1", "true") in found
        assert ("x", "raise ValueError(x)", "false") in found
        assert (
            "raise ValueError(x)",
            "EXIT:unreachable_after_return",
            "exception",
        ) in found
        assert not any(
            source.startswith("dead") for source, _, _ in found if source != "x"
        )

    def test_while_true_keeps_its_false_edge(self, cases):
        found = function_edges(cases, "while_true")

        assert ("True", "n = n + 1", "true") in found
        assert ("True", "return n", "false") in found
        assert ("break", "return n", None) in found

    def test_the_fixture_keeps_its_one_line_statements(self):
        source = (HERE / "edge_cases.py").read_text()

        assert "    if x: return 1\n" in source
        assert "    a = 1; b = 2\n" in source

    def test_one_line_compound_statements_and_semicolons(self, cases):
        found = function_edges(cases, "one_line_compound")

        assert ("x", "return 1", "true") in found
        assert ("for i in x", "use(i)", "true") in found
        assert ("a = 1", "b = 2", None) in found
        assert ("b = 2", "return a + b", None) in found

    def test_a_bare_raise_re_raises_to_the_function_exit(self, cases):
        found = function_edges(cases, "bare_raise")

        assert ("log()", "raise", None) in found
        assert ("raise", "EXIT:bare_raise", "exception") in found
        assert ("except Exception", "EXIT:bare_raise", "false") in found

    def test_a_return_in_finally_wins(self, cases):
        found = function_edges(cases, "return_in_finally")

        assert ("return 1", "return 2", None) in found
        assert ("return 2", "EXIT:return_in_finally", None) in found
        assert ("return 1", "EXIT:return_in_finally", None) not in found

    def test_empty_loop_bodies(self, cases):
        found = function_edges(cases, "empty_loop_bodies")

        assert ("for x in xs", "pass", "true") in found
        assert ("pass", "for x in xs", None) in found
        assert ("xs", "continue", "true") in found
        assert ("continue", "xs", None) in found

    def test_a_bare_except_catches_everything_left_over(self, cases):
        found = function_edges(cases, "many_handlers")

        assert ("except ValueError as err", "y = -1", "true") in found
        assert ("except (TypeError, KeyError)", "y = -3", "false") in found
        assert not any(
            target == "EXIT:many_handlers" and source.startswith("except")
            for source, target, _ in found
        )
        assert ("y = int(x)", "y = y + 1", None) in found
        assert ("done()", "return y", None) in found
        assert ("done()", "EXIT:many_handlers", "exception") in found

    def test_chained_assignment_unpacking_and_the_walrus(self, cases):
        chains = function_chains(cases, "chained_and_unpacking")

        assert chains["a"] == {
            "a = b = 1": ["a += b"],
            "a += b": ["(h := a + f) > 2"],
        }
        assert chains["e"] == {"c, (d, *e) = 1, (2, 3, 4)": ["return c, d, e, g"]}
        assert chains["h"] == {"(h := a + f) > 2": ["return h"]}
        assert "g" not in chains

    def test_a_conditional_expression_is_one_statement(self, cases):
        assert function_edges(cases, "conditional_expressions") == {
            (
                "ENTRY:conditional_expressions",
                "elsewhere = a if b else (b if a else None)",
                None,
            ),
            ("elsewhere = a if b else (b if a else None)", "return elsewhere", None),
            ("return elsewhere", "EXIT:conditional_expressions", None),
        }

    def test_del_global_and_nested_definitions(self, cases):
        found = function_edges(cases, "delete_and_scope")

        assert ("global counter", "value = 1", None) in found
        assert ("value = 1", "del value", None) in found
        assert ("del value", "def inner()", None) in found
        assert ("def inner()", "return inner", None) in found

    def test_stacked_decorators_and_a_decorated_class(self, cases):
        assert function_edges(cases, "<module>") == {
            ("ENTRY:<module>", '"""', None),
            ('"""', "@first", None),
            ("@first", '@register("x")', None),
            ('@register("x")', "class Empty", None),
            ("class Empty", "class Slots", None),
            ("class Slots", "EXIT:<module>", None),
        }

    def test_decorators_are_calls_of_the_definition_statement(self, cases):
        stack = next(
            node
            for node in cases.nodes.values()
            if node.source_text.startswith("@first\n@second")
        )

        assert sorted(stack.metadata.function_calls) == ["first", "second"]
        assert stack.metadata.variable_definitions == ["decorator_stack"]

    def test_class_level_code_is_a_call_of_the_class_statement(self, cases):
        slots = next(
            node for node in cases.nodes.values() if node.source_text == "class Slots"
        )

        assert slots.metadata.function_calls == ["compute"]

    def test_an_async_generator(self, cases):
        found = function_edges(cases, "generators_and_async")

        assert (
            "async for item in session",
            "value = await item.get()",
            "true",
        ) in found
        assert ("value = await item.get()", "yield value", None) in found
        assert ("yield value", "async for item in session", None) in found


class TestDataFlowPatterns:
    def test_entries(self, flows):
        assert entry_names(flows)[1:] == [
            "straight_flow",
            "reassignment_kills",
            "branch_merge",
            "one_branch_defines",
            "loop_carried",
            "flow_through_try",
            "with_target",
            "comprehension_flow",
            "match_capture",
            "container_write",
            "attribute_write",
            "sanitizer_call",
            "argument_to_callee",
            "consume",
            "return_value",
            "fetch",
        ]

    def test_a_value_flows_from_a_source_to_a_sink_through_assignments(self, flows):
        chains = function_chains(flows, "straight_flow")

        assert chains["data"] == {"data = source()": ['command = "run " + data']}
        assert chains["command"] == {'command = "run " + data': ["sink(command)"]}

    def test_a_reassignment_kills_the_earlier_definition(self, flows):
        assert function_chains(flows, "reassignment_kills")["data"] == {
            'data = "constant"': ["sink(data)"]
        }

    def test_both_branch_definitions_reach_the_merge(self, flows):
        assert function_chains(flows, "branch_merge")["value"] == {
            'value = "default"': ["sink(value)"],
            "value = source()": ["sink(value)"],
        }

    def test_a_definition_in_one_branch_does_not_kill_the_other_path(self, flows):
        assert function_chains(flows, "one_branch_defines")["value"] == {
            'value = "default"': ["sink(value)"],
            "value = source()": ["sink(value)"],
        }

    def test_an_accumulator_depends_on_itself(self, flows):
        assert function_chains(flows, "loop_carried")["total"] == {
            'total = ""': ["sink(total)", "total = total + item"],
            "total = total + item": ["sink(total)", "total = total + item"],
        }

    def test_a_handler_sees_the_state_before_the_raising_statement(self, flows):
        assert function_chains(flows, "flow_through_try")["value"] == {
            'value = "safe"': ["sink(value)"],
            "value = source()": ["risky(value)", "sink(value)"],
        }

    def test_a_with_target_is_defined_by_the_header(self, flows):
        chains = function_chains(flows, "with_target")

        assert chains["handle"] == {
            "with open(source()) as handle": ["text = handle.read()"]
        }
        assert chains["text"] == {"text = handle.read()": ["sink(text)"]}

    def test_a_comprehension_variable_does_not_touch_an_outer_name(self, flows):
        chains = function_chains(flows, "comprehension_flow")

        assert chains["item"] == {'item = "outer"': ["sink(item)"]}
        assert chains["cleaned"] == {
            "cleaned = [piece.strip() for piece in items]": ["sink(cleaned)"]
        }
        assert "piece" not in chains

    def test_match_captures_flow_into_the_guard_and_the_body(self, flows):
        chains = function_chains(flows, "match_capture")

        assert chains["name"] == {"capture name, rest": ["if name", "sink(name)"]}
        assert chains["rest"] == {"capture name, rest": ["sink(rest)"]}

    def test_container_and_attribute_writes_keep_earlier_definitions_flowing(
        self, flows
    ):
        assert function_chains(flows, "container_write")["table"] == {
            "table = {}": ['table["key"] = source()'],
            'table["key"] = source()': ["sink(table)"],
        }
        assert function_chains(flows, "attribute_write")["obj"] == {
            "ENTRY:attribute_write": ["obj.value = source()"],
            "obj.value = source()": ["sink(obj)"],
        }

    def test_a_sanitizer_call_is_only_an_assignment_to_the_analysis(self, flows):
        chains = function_chains(flows, "sanitizer_call")

        assert chains["data"] == {"data = source()": ["clean = sanitize(data)"]}
        assert chains["clean"] == {"clean = sanitize(data)": ["sink(clean)"]}

    def test_dataflow_does_not_cross_a_call(self, flows):
        assert function_chains(flows, "argument_to_callee")["data"] == {
            "data = source()": ["consume(data)"]
        }
        assert function_chains(flows, "consume")["payload"] == {
            "ENTRY:consume": ["sink(payload)"]
        }
        assert function_chains(flows, "return_value")["data"] == {
            "data = fetch()": ["sink(data)"]
        }
        assert function_chains(flows, "fetch") == {}
