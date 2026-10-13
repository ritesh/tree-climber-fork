"""
Tests for interprocedural data flow (`analyze_interprocedural`).

The solver keeps each function's flow separate; these edges connect them: arguments to
parameters, return values to call sites, and free variables (closures, `global`,
`nonlocal`, C globals) to the functions that read them.

Flows are compared by the first line of each node's text. A call is written
`(node text, site index)`; an argument index of -1 is the receiver.
"""

from typing import Dict, List, Set, Tuple


from tree_climber.cfg.builder import CFGBuilder
from tree_climber.cfg.cfg_types import NodeType
from tree_climber.cfg.visitor import CFG
from tree_climber.dataflow.analyses.def_use import DefUseSolver
from tree_climber.dataflow.analyses.reaching_definitions import (
    ReachingDefinitionsProblem,
)
from tree_climber.dataflow.interprocedural import (
    InterproceduralResult,
    analyze_interprocedural,
)
from tree_climber.dataflow.solver import RoundRobinSolver


def build(language: str, source: str) -> CFG:
    builder = CFGBuilder(language)
    builder.setup_parser()
    return builder.build_cfg(source)


def text(cfg: CFG, node_id: int) -> str:
    node = cfg.nodes[node_id]
    first = node.source_text.splitlines()[0] if node.source_text else ""
    return first if node.node_type != NodeType.ENTRY else f"ENTRY:{first}"


def arguments(language: str, source: str) -> Set[Tuple[str, int, str, str]]:
    """(call node, argument index, callee, parameter) for every argument flow."""
    cfg = build(language, source)
    return {
        (text(cfg, f.call.node), f.argument, text(cfg, f.callee), f.parameter)
        for f in analyze_interprocedural(cfg).argument_flows
    }


def py_args(source: str, call: str = "") -> Set[Tuple[int, str, str]]:
    return {
        (index, callee, parameter)
        for node, index, callee, parameter in arguments("python", source)
        if node.startswith(call)
    }


def returns(language: str, source: str) -> Set[Tuple[str, str]]:
    cfg = build(language, source)
    return {
        (text(cfg, f.return_node), text(cfg, f.call.node))
        for f in analyze_interprocedural(cfg).return_flows
    }


def free(language: str, source: str) -> Set[Tuple[str, str, str, str]]:
    """(scope, variable, definition, use) for every free-variable flow."""
    cfg = build(language, source)
    return {
        (f.scope, f.variable, text(cfg, f.definition), text(cfg, f.use))
        for f in analyze_interprocedural(cfg).free_variable_flows
    }


class TestPythonArgumentBinding:
    def test_positional_arguments_go_to_parameters_in_order(self):
        source = "def f(a, b):\n    pass\nf(x, y)\n"

        assert py_args(source, "f(") == {(0, "ENTRY:f", "a"), (1, "ENTRY:f", "b")}

    def test_extra_positional_arguments_are_dropped(self):
        source = "def f(a):\n    pass\nf(x, y, z)\n"

        assert py_args(source, "f(") == {(0, "ENTRY:f", "a")}

    def test_missing_arguments_bind_nothing(self):
        source = "def f(a, b=1, c=2):\n    pass\nf(x)\n"

        assert py_args(source, "f(") == {(0, "ENTRY:f", "a")}

    def test_keyword_arguments_go_to_the_parameter_of_that_name(self):
        source = "def f(a, b, c):\n    pass\nf(1, c=x, b=y)\n"

        assert py_args(source, "f(") == {
            (0, "ENTRY:f", "a"),
            (1, "ENTRY:f", "c"),
            (2, "ENTRY:f", "b"),
        }

    def test_an_unknown_keyword_goes_to_var_keyword_or_is_dropped(self):
        with_kwargs = "def f(a, **kw):\n    pass\nf(1, z=x)\n"
        without = "def f(a):\n    pass\nf(1, z=x)\n"

        assert py_args(with_kwargs, "f(") == {(0, "ENTRY:f", "a"), (1, "ENTRY:f", "kw")}
        assert py_args(without, "f(") == {(0, "ENTRY:f", "a")}

    def test_extra_positional_arguments_go_to_var_positional(self):
        source = "def f(a, *rest):\n    pass\nf(1, x, y)\n"

        assert py_args(source, "f(") == {
            (0, "ENTRY:f", "a"),
            (1, "ENTRY:f", "rest"),
            (2, "ENTRY:f", "rest"),
        }

    def test_keyword_only_parameters_are_not_filled_by_position(self):
        source = "def f(a, *, k):\n    pass\nf(x, y, k=z)\n"

        assert py_args(source, "f(") == {(0, "ENTRY:f", "a"), (2, "ENTRY:f", "k")}

    def test_a_star_argument_may_reach_every_remaining_positional_parameter(self):
        source = "def f(a, b, *rest, k):\n    pass\nf(1, *args)\n"

        assert py_args(source, "f(") == {
            (0, "ENTRY:f", "a"),
            (1, "ENTRY:f", "b"),
            (1, "ENTRY:f", "rest"),
        }

    def test_arguments_after_a_star_argument_may_reach_any_positional_parameter(self):
        source = "def f(a, b, *rest):\n    pass\nf(*args, x)\n"

        assert py_args(source, "f(") == {
            (0, "ENTRY:f", "a"),
            (0, "ENTRY:f", "b"),
            (0, "ENTRY:f", "rest"),
            (1, "ENTRY:f", "a"),
            (1, "ENTRY:f", "b"),
            (1, "ENTRY:f", "rest"),
        }

    def test_a_double_star_argument_may_reach_every_unbound_named_parameter(self):
        source = "def f(a, b, *, k, **kw):\n    pass\nf(1, **opts)\n"

        assert py_args(source, "f(") == {
            (0, "ENTRY:f", "a"),
            (1, "ENTRY:f", "b"),
            (1, "ENTRY:f", "k"),
            (1, "ENTRY:f", "kw"),
        }

    def test_positional_only_parameters_bind_by_position(self):
        source = "def f(a, /, b):\n    pass\nf(x, y)\n"

        assert py_args(source, "f(") == {(0, "ENTRY:f", "a"), (1, "ENTRY:f", "b")}

    def test_every_function_of_that_name_is_a_candidate(self):
        source = "def f(a):\n    pass\nclass A:\n    def f(self, b):\n        pass\nf(x)\nobj.f(y)\n"

        found = arguments("python", source)
        assert ("f(x)", 0, "ENTRY:f", "a") in found
        assert ("f(x)", 0, "ENTRY:A.f", "b") not in found
        assert ("obj.f(y)", 0, "ENTRY:f", "a") in found
        assert ("obj.f(y)", 0, "ENTRY:A.f", "b") in found
        assert ("obj.f(y)", -1, "ENTRY:A.f", "self") in found

    def test_a_call_with_no_name_has_no_flows(self):
        assert (
            arguments("python", "def f(a):\n    pass\nhandlers[k](x)\nf()(x)\n")
            == set()
        )

    def test_recursion_flows_into_its_own_entry(self):
        source = "def f(n):\n    return f(n - 1)\n"

        assert py_args(source, "return f") == {(0, "ENTRY:f", "n")}


class TestPythonMethods:
    SOURCE = (
        "class A:\n"
        "    def __init__(self, a, b=0):\n"
        "        self.a = a\n"
        "    def m(self, p):\n"
        "        return p\n"
        "    @staticmethod\n"
        "    def s(q):\n"
        "        return q\n"
        "    @classmethod\n"
        "    def c(cls, r):\n"
        "        return r\n"
        "def plain(z):\n"
        "    return z\n"
    )

    def flows(self, call: str):
        return {
            (index, callee, parameter)
            for node, index, callee, parameter in arguments(
                "python", self.SOURCE + call + "\n"
            )
            if node == call
        }

    def test_the_receiver_binds_self_and_shifts_the_arguments(self):
        assert self.flows("obj.m(x)") == {
            (-1, "ENTRY:A.m", "self"),
            (0, "ENTRY:A.m", "p"),
        }

    def test_a_constructor_call_shifts_without_binding_self(self):
        assert self.flows("A(x, y)") == {
            (0, "ENTRY:A.__init__", "a"),
            (1, "ENTRY:A.__init__", "b"),
        }

    def test_a_static_method_is_not_shifted(self):
        assert self.flows("A.s(x)") == {(0, "ENTRY:A.s", "q")}

    def test_a_class_method_binds_the_class(self):
        assert self.flows("A.c(x)") == {
            (-1, "ENTRY:A.c", "cls"),
            (0, "ENTRY:A.c", "r"),
        }

    def test_a_plain_function_called_through_a_module_is_not_shifted(self):
        assert self.flows("pkg.plain(x)") == {(0, "ENTRY:plain", "z")}

    def test_a_method_called_by_its_bare_name_is_not_shifted(self):
        assert self.flows("m(x)") == {(0, "ENTRY:A.m", "self")}


class TestReturns:
    def test_a_return_flows_to_every_call_of_the_function(self):
        source = "def f():\n    return 1\nx = f()\nprint(f())\n"

        assert returns("python", source) == {
            ("return 1", "x = f()"),
            ("return 1", "print(f())"),
        }

    def test_every_return_node_flows(self):
        source = "def f(c):\n    if c:\n        return 1\n    return 2\nx = f(y)\n"

        assert returns("python", source) == {
            ("return 1", "x = f(y)"),
            ("return 2", "x = f(y)"),
        }

    def test_a_function_without_return_has_none(self):
        assert returns("python", "def f():\n    pass\nx = f()\n") == set()

    def test_a_constructor_call_has_no_return_flow(self):
        source = "class A:\n    def __init__(self):\n        return\nx = A()\n"

        assert returns("python", source) == set()

    def test_the_call_is_identified_by_its_site(self):
        cfg = build("python", "def f():\n    return 1\nx = f() + f()\n")

        flows = analyze_interprocedural(cfg).return_flows

        assert sorted(f.call.site for f in flows) == [0, 1]

    def test_a_nested_call_in_an_argument_has_its_own_flow(self):
        source = "def g():\n    return 1\ndef f(a):\n    return a\nf(g())\n"

        assert returns("python", source) >= {("return 1", "f(g())")}


class TestPythonFreeVariables:
    def test_a_closure_reads_the_enclosing_functions_variable(self):
        source = "def outer():\n    n = 1\n    def inner():\n        return n\n    return inner\n"

        assert free("python", source) == {
            ("closure", "n", "n = 1", "return n"),
        }

    def test_the_variable_resolves_through_two_levels(self):
        source = (
            "def a():\n"
            "    n = 1\n"
            "    def b():\n"
            "        def c():\n"
            "            return n\n"
            "        return c\n"
            "    return b\n"
        )

        assert free("python", source) == {("closure", "n", "n = 1", "return n")}

    def test_a_global_declaration_skips_an_enclosing_functions_local(self):
        source = (
            "x = 0\n"
            "def outer():\n"
            "    x = 1\n"
            "    def inner():\n"
            "        global x\n"
            "        return x\n"
            "    return inner\n"
        )

        assert free("python", source) == {("global", "x", "x = 0", "return x")}

    def test_an_enclosing_global_declaration_makes_the_name_global_for_nested_functions(
        self,
    ):
        source = (
            "x = 0\n"
            "def a():\n"
            "    x = 1\n"
            "    def b():\n"
            "        global x\n"
            "        def c():\n"
            "            return x\n"
            "        return c\n"
            "    return b\n"
        )

        assert free("python", source) == {("global", "x", "x = 0", "return x")}

    def test_a_global_write_does_not_make_the_name_local(self):
        source = "def setter():\n    global g\n    g = 1\ndef reader():\n    return g\n"

        assert free("python", source) == {("global", "g", "g = 1", "return g")}

    def test_the_nearest_enclosing_definition_wins(self):
        source = (
            "def a():\n"
            "    n = 1\n"
            "    def b():\n"
            "        n = 2\n"
            "        def c():\n"
            "            return n\n"
            "        return c\n"
            "    return b\n"
        )

        assert free("python", source) == {("closure", "n", "n = 2", "return n")}

    def test_a_nonlocal_write_reaches_the_other_readers(self):
        source = (
            "def outer():\n"
            "    count = 0\n"
            "    def bump():\n"
            "        nonlocal count\n"
            "        count = count + 1\n"
            "    def read():\n"
            "        return count\n"
            "    return read\n"
        )

        found = free("python", source)
        assert ("closure", "count", "count = 0", "count = count + 1") in found
        assert ("closure", "count", "count = 0", "return count") in found
        assert ("closure", "count", "count = count + 1", "return count") in found

    def test_a_module_variable_reaches_the_functions_that_read_it(self):
        source = "limit = 10\ndef f():\n    return limit\n"

        assert free("python", source) == {
            ("global", "limit", "limit = 10", "return limit")
        }

    def test_a_global_write_reaches_the_module_and_other_functions(self):
        source = (
            "counter = 0\n"
            "def bump():\n"
            "    global counter\n"
            "    counter = counter + 1\n"
            "def read():\n"
            "    return counter\n"
            "print(counter)\n"
        )

        found = free("python", source)
        assert ("global", "counter", "counter = counter + 1", "return counter") in found
        assert ("global", "counter", "counter = counter + 1", "print(counter)") in found
        assert ("global", "counter", "counter = 0", "counter = counter + 1") in found

    def test_a_local_with_the_same_name_does_not_leak(self):
        source = "x = 1\ndef f():\n    x = 2\n    return x\ndef g():\n    return x\n"

        assert free("python", source) == {("global", "x", "x = 1", "return x")}

    def test_two_functions_with_the_same_local_name_do_not_share_it(self):
        source = (
            "def f():\n    t = 1\n    return t\ndef g():\n    t = 2\n    return t\n"
        )

        assert free("python", source) == set()

    def test_a_parameter_shadows_a_global(self):
        source = "x = 1\ndef f(x):\n    return x\n"

        assert free("python", source) == set()

    def test_an_attribute_write_does_not_make_the_name_local(self):
        source = "obj = make()\ndef f():\n    obj.attr = 1\n    return obj\n"

        found = free("python", source)
        assert ("global", "obj", "obj = make()", "obj.attr = 1") in found
        assert ("global", "obj", "obj = make()", "return obj") in found

    def test_a_for_target_and_a_with_target_are_local(self):
        source = (
            "i = 0\n"
            "def f(xs, p):\n"
            "    for i in xs:\n"
            "        pass\n"
            "    with open(p) as fh:\n"
            "        return fh, i\n"
        )

        assert free("python", source) == set()

    def test_methods_read_module_variables_not_class_attributes(self):
        source = "x = 1\nclass A:\n    x = 2\n    def m(self):\n        return x\n"

        assert free("python", source) == {("global", "x", "x = 1", "return x")}

    def test_a_nested_function_name_is_a_local_of_its_function(self):
        source = "def outer():\n    def inner():\n        pass\n    inner()\n"

        assert free("python", source) == set()

    def test_a_match_capture_is_local(self):
        source = (
            "v = 1\ndef f(c):\n    match c:\n        case [v]:\n            return v\n"
        )

        assert free("python", source) == set()


class TestC:
    def test_arguments_and_returns(self):
        source = "int src() { return 5; }\nvoid sink(int v) { }\nvoid f() { int x = src(); sink(x); }\n"

        assert arguments("c", source) == {("sink(x);", 0, "ENTRY:sink", "v")}
        assert returns("c", source) == {("return 5;", "int x = src();")}

    def test_arguments_bind_by_position(self):
        source = "void g(int a, int b) { }\nvoid f() { g(1, 2); }\n"

        assert arguments("c", source) == {
            ("g(1, 2);", 0, "ENTRY:g", "a"),
            ("g(1, 2);", 1, "ENTRY:g", "b"),
        }

    def test_a_global_written_in_one_function_reaches_readers_in_another(self):
        source = "int g;\nvoid set(int v) { g = v; }\nint get() { return g; }\n"

        assert free("c", source) == {("global", "g", "g = v;", "return g;")}

    def test_a_local_declaration_shadows_the_global(self):
        source = (
            "int g;\nvoid set(int v) { g = v; }\nint get() { int g = 1; return g; }\n"
        )

        assert free("c", source) == set()

    def test_a_parameter_shadows_the_global(self):
        source = "int g;\nvoid set(int v) { g = v; }\nint get(int g) { return g; }\n"

        assert free("c", source) == set()

    def test_declarations_in_inner_blocks_and_with_pointers_are_local(self):
        source = (
            "int a;\nint *b;\n"
            "void set(int v) { a = v; b = &v; }\n"
            "int get() { int x = 0; { int a, *b; a = 1; } return a; }\n"
        )

        assert free("c", source) == set()

    def test_a_function_pointer_call_has_no_flows(self):
        assert arguments("c", "void f(int x) { (*fp)(x); s->cb(x); }\n") == set()


class TestJava:
    SOURCE = (
        "class A {\n"
        "  int id(int a) { return a; }\n"
        "  void many(int a, int... rest) { }\n"
        "  void f(int x) { int y = id(x); many(1, 2, 3); this.id(y); }\n"
        "}\n"
    )

    def test_arguments_bind_by_position_and_the_receiver_binds_nothing(self):
        found = arguments("java", self.SOURCE)

        assert ("int y = id(x);", 0, "ENTRY:id", "a") in found
        assert ("this.id(y);", 0, "ENTRY:id", "a") in found
        assert not any(index == -1 for _, index, _, _ in found)

    def test_varargs_collect_the_extra_arguments(self):
        found = arguments("java", self.SOURCE)

        assert ("many(1, 2, 3);", 0, "ENTRY:many", "a") in found
        assert ("many(1, 2, 3);", 1, "ENTRY:many", "rest") in found
        assert ("many(1, 2, 3);", 2, "ENTRY:many", "rest") in found

    def test_returns(self):
        assert ("return a;", "int y = id(x);") in returns("java", self.SOURCE)

    def test_free_variables_are_not_modeled(self):
        assert free("java", self.SOURCE) == set()


class TestFunctionInfo:
    @staticmethod
    def infos(language: str, source: str):
        cfg = build(language, source)
        return {
            text(cfg, e): cfg.nodes[e].metadata.function for e in cfg.entry_node_ids
        }

    def test_python_parameters_and_kinds(self):
        infos = self.infos(
            "python", "def f(a, b=1, /, c=2, *args, d, e=3, **kw):\n    pass\n"
        )

        info = infos["ENTRY:f"]
        assert info is not None
        assert [(p.name, p.kind, p.has_default) for p in info.parameters] == [
            ("a", "positional", False),
            ("b", "positional", True),
            ("c", "positional", True),
            ("args", "var_positional", False),
            ("d", "keyword_only", False),
            ("e", "keyword_only", True),
            ("kw", "var_keyword", False),
        ]

    def test_python_methods_and_constructors(self):
        infos = self.infos(
            "python",
            "class A:\n    def __init__(self):\n        pass\n    def m(self):\n        pass\n"
            "    @staticmethod\n    def s():\n        pass\n    def none():\n        pass\n",
        )

        init, method = infos["ENTRY:A.__init__"], infos["ENTRY:A.m"]
        assert init is not None and method is not None
        assert (init.call_name, init.is_constructor, init.binds_receiver) == (
            "A",
            True,
            True,
        )
        assert (method.call_name, method.kind, method.binds_receiver) == (
            "m",
            "method",
            True,
        )
        static, bare = infos["ENTRY:A.s"], infos["ENTRY:A.none"]
        assert static is not None and bare is not None
        assert static.binds_receiver is False
        assert bare.binds_receiver is False

    def test_python_scopes(self):
        source = (
            "def outer(p):\n"
            "    global g\n"
            "    x = 1\n"
            "    def inner():\n"
            "        nonlocal x\n"
            "        y = 2\n"
            "    obj.attr = 3\n"
        )
        cfg = build("python", source)
        infos = {
            text(cfg, e): (e, cfg.nodes[e].metadata.function)
            for e in cfg.entry_node_ids
        }

        outer_entry, outer = infos["ENTRY:outer"]
        _, inner = infos["ENTRY:inner"]
        assert outer is not None and inner is not None
        assert sorted(outer.locals or []) == ["inner", "p", "x"]
        assert outer.globals == ["g"]
        assert inner.parent == outer_entry
        assert inner.nonlocals == ["x"]
        assert sorted(inner.locals or []) == ["y"]

    def test_declared_names_are_not_local_even_when_assigned(self):
        cfg = build(
            "python",
            "def outer():\n    x = 1\n    def inner():\n        global g\n"
            "        nonlocal x\n        g = 1\n        x = 2\n        y = 3\n",
        )
        inner = next(
            cfg.nodes[e].metadata.function
            for e in cfg.entry_node_ids
            if text(cfg, e) == "ENTRY:inner"
        )

        assert inner is not None
        assert inner.locals == ["y"]
        assert (inner.globals, inner.nonlocals) == (["g"], ["x"])

    def test_the_module_flow_is_the_parent_of_module_level_functions(self):
        cfg = build("python", "x = 1\ndef f():\n    pass\n")
        entries = {text(cfg, e): e for e in cfg.entry_node_ids}

        info = cfg.nodes[entries["ENTRY:f"]].metadata.function
        assert info is not None
        assert info.parent == entries["ENTRY:<module>"]
        module = cfg.nodes[entries["ENTRY:<module>"]].metadata.function
        assert module is not None and module.kind == "module"

    def test_c_locals_and_parameters(self):
        infos = self.infos(
            "c", "int f(int a, char *b, ...) { int x, *y = 0; return a; }\n"
        )

        info = infos["ENTRY:f"]
        assert info is not None
        assert [(p.name, p.kind) for p in info.parameters] == [
            ("a", "positional"),
            ("b", "positional"),
            ("...", "var_positional"),
        ]
        assert sorted(info.locals or []) == ["a", "b", "x", "y"]

    def test_java_has_parameters_but_no_scopes(self):
        infos = self.infos("java", "class A { void f(int a, String... rest) { } }\n")

        info = infos["ENTRY:f"]
        assert info is not None
        assert [(p.name, p.kind) for p in info.parameters] == [
            ("a", "positional"),
            ("rest", "var_positional"),
        ]
        assert info.locals is None

    def test_to_dict_carries_the_function_info(self):
        cfg = build("python", "def f(a, *b):\n    pass\n")
        entry = next(e for e in cfg.entry_node_ids if text(cfg, e) == "ENTRY:f")

        info = cfg.nodes[entry].to_dict()["metadata"]["function"]
        assert info["call_name"] == "f"
        assert info["parameters"][1] == {
            "name": "b",
            "kind": "var_positional",
            "has_default": False,
        }
        assert cfg.nodes[entry + 1].to_dict()["metadata"]["function"] is None


class TestResult:
    def test_to_dict(self):
        cfg = build("python", "def f(a):\n    return a\nx = f(y)\n")
        result = analyze_interprocedural(cfg)
        (argument,) = result.argument_flows
        (returned,) = result.return_flows

        assert result.to_dict() == {
            "argument_flows": [
                {
                    "call": {"node": argument.call.node, "site": 0},
                    "argument": 0,
                    "callee": argument.callee,
                    "parameter": "a",
                }
            ],
            "return_flows": [
                {
                    "return_node": returned.return_node,
                    "call": {"node": returned.call.node, "site": 0},
                }
            ],
            "free_variable_flows": [],
        }

    def test_a_free_variable_flow_serializes(self):
        cfg = build("python", "x = 1\ndef f():\n    return x\n")
        (flow,) = analyze_interprocedural(cfg).free_variable_flows

        assert flow.to_dict() == {
            "variable": "x",
            "definition": flow.definition,
            "use": flow.use,
            "scope": "global",
        }

    def test_an_empty_program(self):
        assert analyze_interprocedural(build("python", "")) == InterproceduralResult()

    def test_callee_locals_do_not_leak_into_the_caller(self):
        source = "def f():\n    x = 1\n    return x\nx = 0\nf()\nprint(x)\n"
        cfg = build("python", source)
        reaching = RoundRobinSolver().solve(cfg, ReachingDefinitionsProblem())
        chains = DefUseSolver().solve(cfg, reaching).chains

        defs_reaching_print = {
            text(cfg, c.definition)
            for c in chains["x"]
            if any(text(cfg, u) == "print(x)" for u in c.uses)
        }
        assert defs_reaching_print == {"x = 0"}
        assert not any(
            f.variable == "x" for f in analyze_interprocedural(cfg).free_variable_flows
        )


def reaches_sink(language: str, source: str, source_call: str, sink: str) -> bool:
    """A small taint propagation over def-use chains plus the interprocedural edges:
    starting from the results of calls to `source_call`, does anything reach an
    argument of a call to `sink`?"""
    cfg = build(language, source)
    reaching = RoundRobinSolver().solve(cfg, ReachingDefinitionsProblem())
    chains = DefUseSolver().solve(cfg, reaching).chains
    flows = analyze_interprocedural(cfg)
    uses: Dict[Tuple[str, int], List[int]] = {
        (variable, chain.definition): chain.uses
        for variable, variable_chains in chains.items()
        for chain in variable_chains
    }
    tainted: Set[Tuple[str, int]] = set()
    tainted_results: Set[Tuple[int, int]] = set()
    work: List[Tuple[str, int]] = []

    def mark(variable: str, node: int) -> None:
        if (variable, node) not in tainted:
            tainted.add((variable, node))
            work.append((variable, node))

    def taint_result(node_id: int, index: int) -> None:
        if (node_id, index) in tainted_results:
            return
        tainted_results.add((node_id, index))
        node = cfg.nodes[node_id]
        site = node.metadata.call_sites[index]
        for name in site.assigned_to or node.metadata.variable_definitions:
            mark(name, node_id)
        if site.feeds is not None and site.feeds.role == "argument":
            for flow in flows.argument_flows:
                if (flow.call.node, flow.call.site) == (node_id, site.feeds.call) and (
                    flow.argument == site.feeds.position
                ):
                    mark(flow.parameter, flow.callee)
        if node.node_type == NodeType.RETURN:
            for flow in flows.return_flows:
                if flow.return_node == node_id:
                    taint_result(flow.call.node, flow.call.site)

    for node_id, node in cfg.nodes.items():
        for index, site in enumerate(node.metadata.call_sites):
            if site.callee == source_call:
                taint_result(node_id, index)

    while work:
        variable, node = work.pop()
        for use in uses.get((variable, node), []):
            use_node = cfg.nodes[use]
            for flow in flows.argument_flows:
                if flow.call.node == use and flow.argument >= 0:
                    site = use_node.metadata.call_sites[flow.call.site]
                    if variable in site.arguments[flow.argument].uses:
                        mark(flow.parameter, flow.callee)
            if use_node.node_type == NodeType.RETURN:
                for flow in flows.return_flows:
                    if flow.return_node == use:
                        taint_result(flow.call.node, flow.call.site)
            for name in use_node.metadata.variable_definitions:
                mark(name, use)

    for node_id, node in cfg.nodes.items():
        for index, site in enumerate(node.metadata.call_sites):
            if site.callee != sink:
                continue
            for argument in site.arguments:
                for name in argument.uses:
                    for chain in chains.get(name, []):
                        if (
                            node_id in chain.uses
                            and (name, chain.definition) in tainted
                        ):
                            return True
            for other, inner in enumerate(node.metadata.call_sites):
                if (
                    inner.feeds is not None
                    and inner.feeds.call == index
                    and inner.feeds.role == "argument"
                    and (node_id, other) in tainted_results
                ):
                    return True
    return False


class TestTheCasesThePrototypeMissed:
    def test_a_tainted_argument_reaches_a_sink_in_the_callee(self):
        source = (
            "def run(cmd):\n    eval(cmd)\n\n"
            "def handler():\n    x = input()\n    run(x)\n"
        )

        assert reaches_sink("python", source, "input", "eval")

    def test_a_tainted_return_value_reaches_a_sink_in_the_caller(self):
        source = (
            "def read():\n    return input()\n\n"
            "def handler():\n    x = read()\n    eval(x)\n"
        )

        assert reaches_sink("python", source, "input", "eval")

    def test_a_constant_does_not(self):
        source = (
            "def run(cmd):\n    eval(cmd)\n\n"
            "def handler():\n    x = input()\n    run('safe')\n"
        )

        assert not reaches_sink("python", source, "input", "eval")

    def test_the_wrong_argument_does_not(self):
        source = (
            "def run(a, b):\n    eval(b)\n\n"
            "def handler():\n    x = input()\n    run(x, 'safe')\n"
        )

        assert not reaches_sink("python", source, "input", "eval")

    def test_through_two_calls_and_a_method(self):
        source = (
            "class Runner:\n"
            "    def go(self, cmd):\n        eval(cmd)\n\n"
            "def relay(v):\n    Runner().go(v)\n\n"
            "def handler():\n    relay(input())\n"
        )

        assert reaches_sink("python", source, "input", "eval")

    def test_c(self):
        source = (
            "int src() { return 5; }\n"
            "void sink(int v) { run(v); }\n"
            "void f() { int x = src(); sink(x); }\n"
        )

        assert reaches_sink("c", source, "src", "run")
