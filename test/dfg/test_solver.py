"""
The worklist solver against the round-robin solver it replaced, which stays as
the oracle: equal IN and OUT sets on every test input file, and on small
programs that exercise loops, unreachable code, call edges and initial facts.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Set, cast

import pytest

from tree_climber.cfg.builder import CFGBuilder
from tree_climber.cfg.cfg_types import CFGNode, NodeType
from tree_climber.cfg.visitor import CFG
from tree_climber.dataflow.analyses.reaching_definitions import (
    ReachingDefinition,
    ReachingDefinitionsGenKill,
    ReachingDefinitionsProblem,
    Union,
)
from tree_climber.dataflow.dataflow_types import (
    DataflowFact,
    DataflowInitializer,
    DataflowProblem,
    TransferFunction,
)
from tree_climber.dataflow.solver import (
    RoundRobinSolver,
    WorklistSolver,
    reverse_postorder,
)
from tree_climber.language_registry import language_for_extension

TEST_ROOT = Path(__file__).parent.parent
INPUTS = sorted(
    path
    for path in TEST_ROOT.rglob("*")
    if path.is_file()
    and language_for_extension(path.suffix) is not None
    and "__pycache__" not in path.parts
)


def build(language: str, source: str) -> CFG:
    builder = CFGBuilder(language)
    builder.setup_parser()
    return builder.build_cfg(source)


def assert_same_as_round_robin(cfg: CFG, problem_factory=ReachingDefinitionsProblem):
    expected = RoundRobinSolver().solve(cfg, problem_factory())
    actual = WorklistSolver().solve(cfg, problem_factory())
    assert actual.in_facts == expected.in_facts
    assert actual.out_facts == expected.out_facts
    return actual


def node_with_text(cfg: CFG, text: str) -> CFGNode:
    return next(node for node in cfg.nodes.values() if node.source_text == text)


def defs(facts: Set[DataflowFact], cfg: CFG):
    return {
        (fact.variable_name, cfg.nodes[fact.node_id].source_text)
        for fact in facts
        if isinstance(fact, ReachingDefinition)
    }


def test_there_are_inputs_in_every_language():
    languages = {language_for_extension(path.suffix) for path in INPUTS}
    assert languages == {"c", "java", "python"}


@pytest.mark.parametrize(
    "path", [pytest.param(p, id=str(p.relative_to(TEST_ROOT))) for p in INPUTS]
)
def test_every_test_input_gives_the_same_result(path):
    language = language_for_extension(path.suffix)
    assert language is not None
    assert_same_as_round_robin(build(language, path.read_text(errors="replace")))


def test_a_definition_reaches_around_a_loop():
    cfg = build("python", "x = 0\nwhile c:\n    x = x + 1\nprint(x)\n")

    result = assert_same_as_round_robin(cfg)

    increment = node_with_text(cfg, "x = x + 1")
    assert defs(result.in_facts[increment.id], cfg) == {
        ("x", "x = 0"),
        ("x", "x = x + 1"),
    }


def test_unreachable_code_is_solved_too():
    cfg = build("python", "def f():\n    return 1\n    y = 2\n    print(y)\n")

    result = assert_same_as_round_robin(cfg)

    unreachable = node_with_text(cfg, "y = 2")
    assert not unreachable.predecessors
    assert defs(result.out_facts[unreachable.id], cfg) == {("y", "y = 2")}
    assert defs(result.in_facts[node_with_text(cfg, "print(y)").id], cfg) == {
        ("y", "y = 2")
    }


def test_facts_do_not_cross_call_and_return_edges():
    cfg = build("python", "def f(a):\n    b = a\n    return b\nx = 1\ny = f(x)\n")
    labels = {
        label for node in cfg.nodes.values() for label in node.edge_labels.values()
    }
    assert {"function_call", "function_return"} <= labels

    result = assert_same_as_round_robin(cfg)

    inside = node_with_text(cfg, "b = a")
    assert ("x", "x = 1") not in defs(result.in_facts[inside.id], cfg)


class Mark(DataflowFact):
    def __init__(self, node_id: int):
        self.node_id = node_id

    def __repr__(self) -> str:
        return f"Mark({self.node_id})"


class SeedEven(DataflowInitializer):
    def __call__(self, node: CFGNode) -> Set[DataflowFact]:
        return {Mark(node.id)} if node.id % 2 == 0 else set()


class MarkConditions(TransferFunction):
    def __call__(self, node: CFGNode, in_facts: Set[DataflowFact]) -> Set[DataflowFact]:
        if node.node_type in (NodeType.CONDITION, NodeType.LOOP_HEADER):
            return set(in_facts) | {Mark(node.id)}
        return set(in_facts)


def marking_problem() -> DataflowProblem:
    return DataflowProblem(
        meet=Union(), transfer=MarkConditions(), in_init=SeedEven(), out_init=SeedEven()
    )


def test_a_problem_with_initial_facts_reaches_the_same_fixpoint():
    cfg = build(
        "python",
        "for i in xs:\n    if i:\n        continue\n    while j:\n        j = j - 1\n",
    )

    result = assert_same_as_round_robin(cfg, marking_problem)

    assert any(result.out_facts.values())


def test_reverse_postorder_lists_every_node_once_and_follows_forward_edges():
    cfg = build("python", "a = 1\nif a:\n    b = 2\nelse:\n    b = 3\nprint(b)\n")
    successors = {
        node_id: sorted(node.successors) for node_id, node in cfg.nodes.items()
    }

    order = reverse_postorder(cfg, successors)

    assert sorted(order) == sorted(cfg.nodes)
    rank = {node_id: index for index, node_id in enumerate(order)}
    for node_id, targets in successors.items():
        for target in targets:
            assert rank[node_id] < rank[target]


def test_reverse_postorder_enters_a_loop_where_the_entry_reaches_it():
    cfg = cast(CFG, SimpleNamespace(nodes={0: None, 1: None, 2: None}))

    order = reverse_postorder(cfg, {0: [1], 1: [0], 2: [1]})

    assert order == [2, 1, 0]


def test_gen_facts_are_built_once_per_node():
    cfg = build("python", "x = 1\n")
    node = node_with_text(cfg, "x = 1")
    transfer = ReachingDefinitionsGenKill()

    first = transfer(node, set())
    second = transfer(node, set())

    assert first == second == {ReachingDefinition("x", node.id)}
    assert next(iter(first)) is next(iter(second))


def test_gen_facts_belong_to_the_node_not_its_id():
    first = node_with_text(build("python", "x = 1\n"), "x = 1")
    second = node_with_text(build("python", "y = 1\n"), "y = 1")
    assert first.id == second.id
    transfer = ReachingDefinitionsGenKill()

    transfer(first, set())

    assert transfer(second, set()) == {ReachingDefinition("y", second.id)}


def test_a_node_that_defines_nothing_passes_its_facts_through_as_a_copy():
    cfg = build("python", "x = 1\nprint(x)\n")
    node = node_with_text(cfg, "print(x)")
    facts: Set[DataflowFact] = {ReachingDefinition("x", 0)}

    out = ReachingDefinitionsGenKill()(node, facts)

    assert out == facts
    assert out is not facts
