"""Node lookup: by id, text, type, enclosing function, call, definition and use."""

import re

import pytest
from query_helpers import LANGUAGES, build, named, roles

from tree_climber.cfg.builder import CFGBuilder
from tree_climber.cfg.cfg_types import NodeType
from tree_climber.query import CodeGraph


@LANGUAGES
def test_nodes_are_sorted_and_complete(language):
    graph = build(language)

    assert [node.id for node in graph.nodes] == sorted(graph.cfg.nodes)
    assert len(graph.nodes) == len(graph.cfg.nodes)


@LANGUAGES
def test_node_by_id_or_node(language):
    graph = build(language)
    src = roles(graph)["src"]

    assert graph.node(src.id) is src
    assert graph.node(src) is src


@LANGUAGES
def test_unknown_node_id_is_a_key_error(language):
    graph = build(language)

    with pytest.raises(KeyError):
        graph.node(999)
    with pytest.raises(KeyError):
        graph.successors(999)


@LANGUAGES
def test_by_text_substring(language):
    graph = build(language)

    assert named(graph, graph.by_text("y = 0")) == ["reset"]
    assert named(graph, graph.by_text("total =")) == ["zero", "acc"]
    assert graph.by_text("no such text") == []


@LANGUAGES
def test_by_text_exact_needs_the_whole_text(language):
    graph = build(language)
    reset = roles(graph)["reset"]

    assert graph.by_text(reset.source_text, exact=True) == [reset]
    assert graph.by_text(reset.source_text[:-1], exact=True) == []
    assert graph.by_text(reset.source_text + " ", exact=True) == []


@LANGUAGES
def test_by_text_regex(language):
    graph = build(language)

    zero = graph.by_text(re.compile(r"^(int )?total = 0"))
    assert named(graph, zero) == ["zero"]
    assert named(graph, graph.by_text(re.compile(r"return"))) == [
        "helper_ret",
        "out",
    ]
    assert graph.by_text(re.compile(r"^total$")) == []
    assert named(graph, graph.by_text(re.compile(r"input\("))) == ["src"]


@LANGUAGES
def test_by_type(language):
    graph = build(language)

    assert named(graph, graph.by_type("ENTRY")) == ["helper_entry", "main_entry"]
    assert named(graph, graph.by_type("EXIT")) == ["helper_exit", "main_exit"]
    assert named(graph, graph.by_type("LOOP_HEADER")) == ["loop"]
    assert named(graph, graph.by_type("CONDITION")) == ["cond"]
    assert named(graph, graph.by_type("RETURN")) == ["helper_ret", "out"]


@LANGUAGES
def test_by_type_accepts_enum_names_in_any_case_and_several_types(language):
    graph = build(language)

    assert graph.by_type(NodeType.LOOP_HEADER) == graph.by_type("loop_header")
    both = graph.by_type("loop_header", NodeType.CONDITION)
    assert named(graph, both) == ["cond", "loop"]
    assert graph.by_type("goto") == []


@LANGUAGES
def test_calling_matches_the_callee_name(language):
    graph = build(language)

    assert named(graph, graph.calling("input")) == ["src"]
    assert named(graph, graph.calling("system")) == ["sink"]
    assert named(graph, graph.calling("helper")) == ["ret"]
    assert graph.calling("nobody") == []


@LANGUAGES
def test_calling_several_names_is_any_of(language):
    graph = build(language)

    assert named(graph, graph.calling("system", "input")) == ["src", "sink"]
    assert named(graph, graph.calling("input", "input")) == ["src"]
    assert graph.calling() == []


def test_calling_matches_the_whole_callee_expression_too():
    python = CodeGraph.from_source("python", "import os\nos.system(cmd)\n")
    java = CodeGraph.from_source(
        "java", "class A { void f(Runtime os) { os.exec(cmd); } }"
    )

    assert [node.source_text for node in python.calling("system")] == ["os.system(cmd)"]
    assert [node.source_text for node in python.calling("os.system")] == [
        "os.system(cmd)"
    ]
    assert python.calling("os") == []
    assert len(java.calling("exec")) == 1
    assert len(java.calling("os.exec")) == 1
    assert java.calling("os") == []


@LANGUAGES
def test_defining_and_using(language):
    graph = build(language)

    assert named(graph, graph.defining("y")) == ["clean", "reset"]
    assert named(graph, graph.defining("total")) == ["zero", "acc"]
    assert named(graph, graph.defining("n")) == ["helper_entry"]
    assert named(graph, graph.using("y")) == ["cond", "sink", "acc"]
    assert named(graph, graph.using("total")) == ["loop", "acc", "ret"]
    assert graph.defining("nothing") == []
    assert graph.using("nothing") == []


@LANGUAGES
def test_functions_are_their_entry_nodes(language):
    graph = build(language)

    assert named(graph, graph.functions()) == ["helper_entry", "main_entry"]


@LANGUAGES
def test_function_of_every_node(language):
    graph = build(language)
    found = roles(graph)
    inside_main = [
        "main_entry",
        "main_exit",
        "src",
        "clean",
        "cond",
        "sink",
        "reset",
        "zero",
        "loop",
        "acc",
        "ret",
        "out",
    ]

    for role in ("helper_entry", "helper_exit", "helper_ret"):
        assert graph.function_of(found[role]) is found["helper_entry"]
    for role in inside_main:
        assert graph.function_of(found[role]) is found["main_entry"]
    assert graph.function_of(found["ret"].id) is found["main_entry"]


@LANGUAGES
def test_function_nodes_by_name_and_by_entry(language):
    graph = build(language)
    found = roles(graph)

    helper = graph.function_nodes("helper")
    assert named(graph, helper) == ["helper_entry", "helper_exit", "helper_ret"]
    assert graph.function_nodes(found["helper_entry"]) == helper
    assert graph.function_nodes(found["helper_entry"].id) == helper
    main = graph.function_nodes("main")
    assert len(main) == 12
    assert set(node.id for node in main).isdisjoint(node.id for node in helper)
    assert graph.function_nodes("nobody") == []


def test_dead_code_belongs_to_no_function():
    graph = CodeGraph.from_source("python", "def f():\n    return 1\n    x = 2\n")
    dead = graph.by_text("x = 2")[0]

    assert graph.function_of(dead) is None
    assert dead not in graph.function_nodes("f")


def test_python_methods_and_the_module():
    source = "class K:\n    def m(self):\n        return 1\n\n\nx = K()\n"
    graph = CodeGraph.from_source("python", source)

    assert [entry.source_text for entry in graph.functions()] == ["<module>", "K.m"]
    assert [node.source_text for node in graph.function_nodes("K.m")] == [
        "K.m",
        "K.m",
        "return 1",
    ]
    module = graph.function_of(graph.by_text("x = K()")[0])
    method = graph.function_of(graph.by_text("return 1")[0])
    assert module is not None and module.source_text == "<module>"
    assert method is not None and method.source_text == "K.m"


def test_overloads_share_a_name_but_not_nodes():
    source = "class A { int f(int a) { return a; } int f(int a, int b) { return b; } }"
    graph = CodeGraph.from_source("java", source)
    first, second = graph.functions()

    assert first.source_text == second.source_text == "f"
    assert len(graph.function_nodes("f")) == 6
    assert len(graph.function_nodes(first)) == 3
    assert graph.function_nodes(first)[0] is first
    assert graph.function_of(graph.by_text("return b;")[0]) is second


def test_from_cfg_wraps_the_given_cfg():
    builder = CFGBuilder("c")
    builder.setup_parser()
    cfg = builder.build_cfg("int f() { return 1; }")
    graph = CodeGraph.from_cfg(cfg)

    assert graph.cfg is cfg
    assert [node.id for node in graph.nodes] == sorted(cfg.nodes)
