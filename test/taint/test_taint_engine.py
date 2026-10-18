"""Taint propagation: the #44 prototype cases, call-site sanitizers, argument
positions, sources, flows across calls, C and Java, and finding paths."""

import importlib.util
import json
from pathlib import Path

import pytest

from tree_climber.cfg.builder import CFGBuilder
from tree_climber.query import CodeGraph
from tree_climber.taint.engine import _origins, _Program
from tree_climber.taint import (
    Rule,
    Sanitizer,
    Sink,
    Source,
    analyze,
    analyze_source,
)


def _load_prototype_cases():
    """The cases of the query-layer tracker, kept in one place."""
    path = Path(__file__).parent.parent / "query" / "test_query_taint.py"
    spec = importlib.util.spec_from_file_location("test_query_taint_cases", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CASES, module.FIXTURE


CASES, FIXTURE = _load_prototype_cases()

PROTOTYPE = Rule(
    "prototype",
    sources=[Source(call=name) for name in ("input", "getenv", "source")],
    sinks=[Sink(call=name) for name in ("system", "eval", "execute", "sink")],
    sanitizers=[Sanitizer(call=name) for name in ("escape", "quote", "sanitize")],
)

BASIC = Rule(
    "basic",
    sources=[Source(call="input")],
    sinks=[Sink(call="system")],
    sanitizers=[Sanitizer(call="escape")],
)


def flows(code, rule=BASIC, language="python"):
    return [
        " -> ".join(finding.path.texts)
        for finding in analyze_source(language, code, rule)
    ]


EXPECTED = {
    "direct": ["data = input() -> system(data)"],
    "through_assignment": ['a = input() -> b = "ls " + a -> system(b)'],
    "reassignment_kills": [],
    "sanitizer_blocks": [],
    "sanitizer_on_the_way_but_not_on_every_path": ["a = input() -> b = a -> system(b)"],
    "branch": ["v = input() -> system(v)"],
    "loop": ["t = input() -> eval(t)"],
    "try": ["v = input() -> system(v)"],
    "with": ["with open(input()) as h -> t = h.read() -> system(t)"],
    "subscript": ["d['k'] = input() -> system(d)"],
    "no_source": [],
    "no_sink": [],
    "two_sinks": ["x = input() -> system(x)", "x = input() -> eval(x)"],
    "two_sources": [
        "x = input() -> execute(x + y)",
        "y = getenv('H') -> execute(x + y)",
    ],
    "sanitized_sink_itself": [],
    "not_across_calls": ["x = input() -> g(x) -> g -> system(p)"],
}


class TestThePrototypeCases:
    def test_every_case_has_an_expectation(self):
        assert set(EXPECTED) == set(CASES)

    @pytest.mark.parametrize("name", sorted(CASES))
    def test_case(self, name):
        assert flows(CASES[name], PROTOTYPE) == EXPECTED[name]

    def test_the_fixture(self):
        found = flows(FIXTURE.read_text(), PROTOTYPE)

        assert found == [
            'data = source() -> command = "run " + data -> sink(command)',
            "value = source() -> sink(value)",
            "value = source() -> sink(value)",
            "value = source() -> sink(value)",
            "with open(source()) as handle -> text = handle.read() -> sink(text)",
            'table["key"] = source() -> sink(table)',
            "obj.value = source() -> sink(obj)",
            "data = source() -> consume(data) -> consume -> sink(payload)",
            "return source() -> data = fetch() -> sink(data)",
        ]


class TestSanitizers:
    def test_the_sanitized_part_is_clean(self):
        assert flows('x = input()\ncmd = "ls " + escape(x)\nsystem(cmd)\n') == []

    def test_an_unsanitized_use_beside_it_is_not(self):
        assert flows("x = input()\ncmd = escape(x) + x\nsystem(cmd)\n") == [
            "x = input() -> cmd = escape(x) + x -> system(cmd)"
        ]

    def test_reassigning_the_sanitized_value(self):
        assert flows("x = input()\nx = escape(x)\nsystem(x)\n") == []

    def test_a_sanitizer_inside_a_sink(self):
        assert flows("x = input()\nsystem(escape(x))\n") == []
        assert flows("x = input()\nsystem(*escape(x))\n") == []
        assert flows("x = input()\nsystem(escape(x).strip())\n") == []
        assert flows("x = input()\nsystem(x + escape(x))\n") == [
            "x = input() -> system(x + escape(x))"
        ]

    def test_a_source_inside_a_sanitizer(self):
        assert flows("system(escape(input()))\n") == []
        assert flows("system(input())\n") == ["system(input())"]

    def test_other_calls_pass_taint_through(self):
        assert flows("x = input()\nsystem(x.strip())\n") == [
            "x = input() -> system(x.strip())"
        ]
        assert flows("x = input()\ny = clean(x)\nsystem(y)\n") == [
            "x = input() -> y = clean(x) -> system(y)"
        ]

    def test_a_clean_value_stored_at_a_tainted_index_is_clean(self):
        assert flows("i = input()\narr[i] = escape(t)\nsystem(arr)\n") == []
        assert flows("i = input()\narr[i] = t\nsystem(arr)\n") == [
            "i = input() -> arr[i] = t -> system(arr)"
        ]

    def test_a_definition_whose_uses_are_not_known_uses_them_all(self):
        code = "x = input()\n\n\n@deco\ndef f(a=x):\n    pass\n\n\nsystem(f)\n"
        assert flows(code) == ["x = input() -> @deco -> system(f)"]

    def test_weak_updates_keep_earlier_taint(self):
        assert flows('d = {}\nd["a"] = input()\nd["b"] = escape(d)\nsystem(d)\n') == [
            'd["a"] = input() -> d["b"] = escape(d) -> system(d)'
        ]
        assert flows("x = input()\nx += escape(y)\nsystem(x)\n") == [
            "x = input() -> x += escape(y) -> system(x)"
        ]


class TestArguments:
    RULE = Rule(
        "sql",
        sources=[Source(call="input")],
        sinks=[Sink(call="execute", arguments=[0, "sql"])],
    )

    def findings(self, code):
        return [
            (f.argument, f.sink_call) for f in analyze_source("python", code, self.RULE)
        ]

    def test_only_watched_positions(self):
        assert self.findings('x = input()\nexecute("q", x)\n') == []
        assert self.findings("x = input()\nexecute(x, ())\n") == [(0, "execute")]

    def test_keywords(self):
        assert self.findings("x = input()\nexecute(params=x, sql='q')\n") == []
        assert self.findings("x = input()\nexecute(params=(), sql=x)\n") == [
            (1, "execute")
        ]

    def test_positions_count_positional_arguments_only(self):
        assert self.findings("x = input()\nexecute(timeout=x, sql='q')\n") == []
        assert self.findings("x = input()\nexecute('q', timeout=1, *x)\n") == [
            (2, "execute")
        ]

    def test_a_nested_call_taints_only_its_own_argument(self):
        rule = Rule(
            "pos",
            sources=[Source(call="input")],
            sinks=[Sink(call="execute", arguments=[1])],
        )
        assert analyze_source("python", 'execute(input(), "q")\n', rule) == []

    def test_a_tainted_receiver_is_not_an_argument(self):
        rule = Rule("r", sources=[Source(call="input")], sinks=[Sink(call="*.run")])
        assert analyze_source("python", "x = input()\nx.run()\n", rule) == []
        assert len(analyze_source("python", "x = input()\ny.run(x)\n", rule)) == 1

    def test_star_arguments_may_be_any_position(self):
        assert self.findings("x = input()\nexecute(*x)\n") == [(0, "execute")]

    def test_every_argument_without_a_list(self):
        rule = Rule("any", sources=[Source(call="input")], sinks=[Sink(call="f")])
        found = analyze_source("python", "x = input()\nf(1, 2, x)\n", rule)
        assert [f.argument for f in found] == [2]

    def test_two_tainted_arguments_are_two_findings(self):
        rule = Rule("any", sources=[Source(call="input")], sinks=[Sink(call="f")])
        found = analyze_source("python", "x = input()\nf(x, x)\n", rule)
        assert [f.argument for f in found] == [0, 1]


class TestSources:
    def test_parameters_by_name_and_function(self):
        rule = Rule(
            "p",
            sources=[Source(parameter="request", function="handle*")],
            sinks=[Sink(call="system")],
        )
        code = (
            "def handler(request, other):\n    system(request)\n    system(other)\n\n\n"
            "def helper(request):\n    system(request)\n"
        )
        assert flows(code, rule) == ["handler -> system(request)"]

    def test_parameters_by_position(self):
        rule = Rule("p", sources=[Source(parameter=1)], sinks=[Sink(call="system")])
        code = (
            "def f(a, b):\n    system(a)\n    system(b)\n\n\ndef g(a):\n    system(a)\n"
        )
        assert flows(code, rule) == ["f -> system(b)"]

    def test_attributes(self):
        rule = Rule(
            "a",
            sources=[Source(attribute="request.args")],
            sinks=[Sink(call="system")],
            sanitizers=[Sanitizer(call="escape")],
        )
        code = (
            "def h(request):\n"
            '    name = request.args.get("q")\n'
            "    system(name)\n"
            "    system(request.method)\n"
            "    system(escape(request.args))\n"
            '    system(request.args["x"] + escape(y))\n'
            "    system(request.argsx)\n"
        )
        assert flows(code, rule) == [
            'name = request.args.get("q") -> system(name)',
            'system(request.args["x"] + escape(y))',
        ]

    def test_attributes_in_strings_and_comments_do_not_count(self):
        rule = Rule(
            "a", sources=[Source(attribute="sys.argv")], sinks=[Sink(call="system")]
        )
        code = (
            'system("sys.argv")\n'
            'system("""\nsys.argv\n""")  # sys.argv\n'
            'system(f"run {sys.argv[1]}")\n'
            'system(f"sys.argv {x}")\n'
        )
        assert flows(code, rule) == ['system(f"run {sys.argv[1]}")']

    def test_c_and_java_literals_do_not_count(self):
        rule = Rule(
            "a", sources=[Source(attribute="req.q")], sinks=[Sink(call="system")]
        )
        c = 'void f() { system("req.q"); /* req.q */ system(req.q); }'
        java = 'class A { void f() { system("req.q"); // req.q\n system(req.q); } }'
        assert flows(c, rule, "c") == ["system(req.q);"]
        assert flows(java, rule, "java") == ["system(req.q);"]

    def test_attributes_find_their_argument_among_equal_texts(self):
        rule = Rule("a", sources=[Source(attribute="r.a")], sinks=[Sink(call="f")])
        found = analyze_source("python", 'f("r.a", r.a)\n', rule)
        assert [finding.argument for finding in found] == [1]

    def test_writing_to_the_attribute_is_not_a_source(self):
        rule = Rule(
            "a", sources=[Source(attribute="sys.argv")], sinks=[Sink(call="system")]
        )
        code = (
            "sys.argv[0] = name\nsystem(sys.stdin.read())\nx = sys.argv[1]\nsystem(x)\n"
        )
        assert flows(code, rule) == ["x = sys.argv[1] -> system(x)"]

    def test_attributes_only_inside_a_sanitizer_are_clean(self):
        rule = Rule(
            "a",
            sources=[Source(attribute="request.*")],
            sinks=[Sink(call="system")],
            sanitizers=[Sanitizer(call="escape")],
        )
        assert flows("y = 1 + escape(request.b)\nsystem(y)\n", rule) == []
        assert flows("y = request.a + escape(request.b)\nsystem(y)\n", rule) == [
            "y = request.a + escape(request.b) -> system(y)"
        ]

    def test_attribute_wildcards(self):
        rule = Rule(
            "a", sources=[Source(attribute="request.*")], sinks=[Sink(call="system")]
        )
        assert flows("system(request.form)\nsystem(request)\n", rule) == [
            "system(request.form)"
        ]

    def test_source_calls_by_whole_callee(self):
        rule = Rule(
            "e", sources=[Source(call="os.getenv")], sinks=[Sink(call="system")]
        )
        code = "a = os.getenv('A')\nb = getenv('B')\nsystem(a)\nsystem(b)\n"
        assert flows(code, rule) == ["a = os.getenv('A') -> system(a)"]


class TestOrigins:
    def test_each_source_reports_only_its_own_flows(self):
        found = analyze_source(
            "python", "a = input()\nb = escape(a) + input()\nsystem(b)\n", BASIC
        )

        assert [" -> ".join(f.path.texts) for f in found] == [
            "b = escape(a) + input() -> system(b)"
        ]

    @staticmethod
    def program(code, language="python"):
        builder = CFGBuilder(language)
        builder.setup_parser()
        return _Program(CodeGraph(builder.build_cfg(code)))

    def test_rules_sharing_sources_find_them_once(self, monkeypatch):
        sources = [Source(call="input"), Source(attribute="sys.argv")]
        rules = [
            Rule("shell", sources=sources, sinks=[Sink(call="system")]),
            Rule("eval", sources=sources, sinks=[Sink(call="eval")]),
        ]
        found = []
        find = _Program._find_origins

        def counted(self, source):
            found.append(source)
            return find(self, source)

        monkeypatch.setattr(_Program, "_find_origins", counted)
        code = "a = input()\nb = sys.argv[1]\nsystem(a)\neval(b)\n"

        findings = analyze_source("python", code, rules)

        assert sorted(found, key=repr) == sorted(sources, key=repr)
        assert [(f.rule, " -> ".join(f.path.texts)) for f in findings] == [
            ("eval", "b = sys.argv[1] -> eval(b)"),
            ("shell", "a = input() -> system(a)"),
        ]

    def test_origins_follow_the_rule_sources_then_the_nodes(self):
        program = self.program("a = second()\nb = first()\nc = second()\n")
        first, second = Source(call="first"), Source(call="second")
        rule = Rule("r", sources=[second, first], sinks=[Sink(call="system")])

        origins = [
            (program.cfg.nodes[o.node].source_text, o.source)
            for o in _origins(program, rule)
        ]

        assert origins == [
            ("a = second()", second),
            ("c = second()", second),
            ("b = first()", first),
        ]

    def test_a_call_pattern_matches_every_callee_once_per_node(self):
        program = self.program(
            'x = os.getenv("A") + os.getenv("B")\ny = env.getenv("C")\nz = getenvx()\n'
        )

        origins = program.origins(Source(call="*getenv"))

        assert [program.cfg.nodes[o.node].source_text for o in origins] == [
            'x = os.getenv("A") + os.getenv("B")',
            'y = env.getenv("C")',
        ]

    def test_call_origins_are_in_node_order(self):
        lines = [f"a{i} = {'f()' if i in (3, 9) else '0'}" for i in range(12)]
        program = self.program("\n".join(lines) + "\n")

        origins = program.origins(Source(call="f"))

        assert [program.cfg.nodes[o.node].source_text for o in origins] == [
            "a3 = f()",
            "a9 = f()",
        ]
        assert [o.node for o in origins] != list({o.node for o in origins})

    def test_an_attribute_needs_more_than_its_literal(self):
        program = self.program(
            "a = request.args\nb = myrequest.args\nc = request.argsx\n"
            'd = "request.args"\ne = args.request\n'
        )

        origins = program.origins(Source(attribute="request.args"))

        assert [program.cfg.nodes[o.node].source_text for o in origins] == [
            "a = request.args"
        ]

    def test_an_attribute_of_only_wildcards_checks_every_node(self):
        program = self.program("a = 1\nb = x.y\nc = f(1)\n")

        origins = program.origins(Source(attribute="*.*"))

        assert [program.cfg.nodes[o.node].source_text for o in origins] == ["b = x.y"]


class TestAcrossCalls:
    def test_into_a_function(self):
        code = "def run(cmd):\n    system(cmd)\n\n\ndef f():\n    run(input())\n"
        assert flows(code) == ["run(input()) -> run -> system(cmd)"]

    def test_out_of_a_function(self):
        code = "def read():\n    return input()\n\n\ndef f():\n    y = read()\n    system(y)\n"
        assert flows(code) == ["return input() -> y = read() -> system(y)"]

    def test_a_defined_function_decides_its_own_result(self):
        code = (
            "def g(a):\n    return 1\n\n\ndef f():\n    y = g(input())\n    system(y)\n"
        )
        assert flows(code) == []

    def test_in_and_out_again(self):
        code = "def wrap(a):\n    return a\n\n\ndef f():\n    system(wrap(input()))\n"
        assert flows(code) == [
            "system(wrap(input())) -> wrap -> return a -> system(wrap(input()))"
        ]

    def test_a_sanitizing_function(self):
        code = "def clean(a):\n    return escape(a)\n\n\ndef f():\n    system(clean(input()))\n"
        assert flows(code) == []

    def test_closures_and_globals(self):
        code = (
            "G = input()\n\n\n"
            "def f():\n    x = input()\n\n    def g():\n        system(x)\n        system(G)\n\n    g()\n"
        )
        assert flows(code) == ["G = input() -> system(G)", "x = input() -> system(x)"]

    def test_methods_and_objects(self):
        code = (
            "class R:\n    def __init__(self, c):\n        self.c = c\n\n"
            "    def run(self):\n        system(self.c)\n\n\n"
            "def f():\n    r = R(input())\n    r.run()\n"
        )
        assert flows(code) == ["r = R(input()) -> r.run() -> R.run -> system(self.c)"]


class TestCAndJava:
    def test_c(self):
        rule = Rule(
            "c",
            sources=[Source(call="getenv")],
            sinks=[Sink(call="system")],
            sanitizers=[Sanitizer(call="escape")],
        )
        code = 'void f() { char *x = getenv("A"); char *y = escape(x); system(y); system(x); }'
        assert flows(code, rule, "c") == ['char *x = getenv("A"); -> system(x);']

    def test_c_across_calls(self):
        rule = Rule("c", sources=[Source(call="getenv")], sinks=[Sink(call="system")])
        code = 'void run(char *c) { system(c); }\nvoid f() { run(getenv("A")); }\n'
        assert flows(code, rule, "c") == ['run(getenv("A")); -> run -> system(c);']

    def test_c_main_arguments(self):
        rule = Rule(
            "c",
            sources=[Source(parameter="argv", function="main")],
            sinks=[Sink(call="printf", arguments=[0])],
        )
        code = 'int main(int argc, char **argv) { printf(argv[1]); printf("%s", argv[1]); return 0; }'
        assert flows(code, rule, "c") == ["main -> printf(argv[1]);"]

    def test_java(self):
        rule = Rule(
            "j",
            sources=[Source(call="*.getParameter")],
            sinks=[Sink(call="*.exec")],
            sanitizers=[Sanitizer(call="escape")],
        )
        code = (
            'class A { void f(Request req) { String q = req.getParameter("q");'
            " Runtime.getRuntime().exec(q); Runtime.getRuntime().exec(escape(q)); } }"
        )
        assert flows(code, rule, "java") == [
            'String q = req.getParameter("q"); -> Runtime.getRuntime().exec(q);'
        ]


class TestFindings:
    def test_finding_fields_and_json(self):
        (finding,) = analyze_source(
            "python", "def run(c):\n    system(c)\n\n\nrun(input())\n", BASIC
        )

        assert (finding.rule, finding.sink_call, finding.argument) == (
            "basic",
            "system",
            0,
        )
        data = json.loads(json.dumps(finding.to_dict()))
        assert data["rule"] == "basic"
        assert [step["edge"] for step in data["path"]["steps"]] == [
            None,
            "argument",
            "def_use",
        ]
        assert [step["variable"] for step in data["path"]["steps"]] == [None, "c", "c"]
        assert str(finding).startswith("basic: argument 0 of system\n")

    def test_one_finding_per_source_and_sink_argument(self):
        code = "x = input()\ny = x\nsystem(x + y)\n"
        assert flows(code) == ["x = input() -> system(x + y)"]

    def test_rules_for_other_languages_are_skipped(self):
        rule = Rule(
            "py-only",
            sources=[Source(call="input")],
            sinks=[Sink(call="system")],
            languages=["python"],
        )
        assert analyze_source("c", "void f() { system(input()); }", rule) == []
        assert len(analyze_source("python", "system(input())\n", rule)) == 1

    def test_analyze_takes_a_cfg_and_several_rules(self):
        builder = CFGBuilder("python")
        builder.setup_parser()
        cfg = builder.build_cfg("x = input()\nsystem(x)\neval(x)\n")
        other = Rule("eval", sources=[Source(call="input")], sinks=[Sink(call="eval")])

        found = analyze(cfg, [BASIC, other])
        assert [(f.rule, f.sink_call) for f in found] == [
            ("basic", "system"),
            ("eval", "eval"),
        ]

    @pytest.mark.parametrize("precise", [False, True])
    def test_a_code_graph_gives_the_findings_of_its_cfg(self, precise):
        from tree_climber.taint import builtin_rules

        graph = CodeGraph.from_source("python", GUIDE_APP)
        rules = builtin_rules("python")

        assert analyze(graph, rules, "python", precise, precise) == analyze(
            graph.cfg, rules, "python", precise, precise
        )

    def test_a_code_graph_s_data_flow_is_not_solved_again(self, monkeypatch):
        from tree_climber.query import graph as module
        from tree_climber.taint import builtin_rules

        graph = CodeGraph.from_source("python", GUIDE_APP)
        expected = analyze(graph, builtin_rules("python"), "python", True, True)
        for name in (
            "ReachingDefinitionsProblem",
            "analyze_interprocedural",
            "control_dependence",
        ):
            monkeypatch.setattr(module, name, lambda *args: pytest.fail("solved"))

        found = analyze(graph, builtin_rules("python"), "python", True, True)

        assert expected
        assert found == expected

    def test_paths_are_query_paths(self):
        (finding,) = analyze_source("python", "x = input()\nsystem(x)\n", BASIC)
        graph = CodeGraph.from_source("python", "x = input()\nsystem(x)\n")

        assert finding.path == graph.data_flow_path(finding.source, finding.sink)


GUIDE_APP = """import os
import shlex
from flask import request


def ping():
    host = request.args.get("host")
    run("ping -c 1 " + host)
    run("ping -c 1 " + shlex.quote(host))


def run(command):
    os.system(command)


def search(cursor):
    term = request.args["q"]
    cursor.execute("SELECT * FROM t WHERE name = ?", (term,))
    cursor.execute("SELECT * FROM t WHERE name = '" + term + "'")
"""

GUIDE_RULES = """
{"rules": [{
  "id": "eval",
  "languages": ["python"],
  "sources": [{"call": "input"}, {"parameter": "expr", "function": "calc*"}],
  "sinks": [{"call": "eval", "arguments": [0]}],
  "sanitizers": [{"call": "ast.literal_eval"}]
}]}
"""

GUIDE_CODE = """import ast


def calculate(expr):
    return eval(expr)


x = input()
eval(ast.literal_eval(x))
eval("1 + 1", {"x": x})
"""


class TestTheGuide:
    def test_builtin_example(self):
        from tree_climber.taint import builtin_rules

        found = analyze_source("python", GUIDE_APP, builtin_rules("python"))

        assert [str(f) for f in found] == [
            "python-command-injection: argument 0 of os.system\n"
            '[7] host = request.args.get("host")\n'
            '  --def_use host--> [8] run("ping -c 1 " + host)\n'
            "  --argument command--> [10] ENTRY run\n"
            "  --def_use command--> [12] os.system(command)",
            "python-sql-injection: argument 0 of cursor.execute\n"
            '[15] term = request.args["q"]\n'
            '  --def_use term--> [17] cursor.execute("SELECT * FROM t WHERE name = \'" + term + ...',
        ]

    def test_json_rules_example(self):
        from tree_climber.taint import RuleSet

        found = analyze_source("python", GUIDE_CODE, RuleSet.from_json(GUIDE_RULES))

        assert [" -> ".join(f.path.texts) for f in found] == [
            "calculate -> return eval(expr)"
        ]

    def test_context_insensitivity_example(self):
        code = (
            'def wrap(a):\n    return a\n\n\nt = wrap(input())\nsystem(wrap("safe"))\n'
        )
        assert flows(code) == [
            't = wrap(input()) -> wrap -> return a -> system(wrap("safe"))'
        ]
