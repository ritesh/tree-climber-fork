"""The two precision options of the taint analysis, each compared with the
default: implicit flows through branches, and field and key sensitivity."""

import pytest

from tree_climber.taint import Rule, Sanitizer, Sink, Source, analyze_source

RULE = Rule(
    "r",
    sources=[Source(call="input")],
    sinks=[Sink(call="system")],
    sanitizers=[Sanitizer(call="escape")],
)


def flows(code, language="python", **options):
    return [str(f.path) for f in analyze_source(language, code, RULE, **options)]


def texts(code, language="python", **options):
    return [
        " -> ".join(f.path.texts)
        for f in analyze_source(language, code, RULE, **options)
    ]


class TestImplicitFlows:
    IF = 'x = input()\nif x == "a":\n    cmd = "safe"\nelse:\n    cmd = "other"\nsystem(cmd)\n'

    def test_off_by_default(self):
        assert flows(self.IF) == []

    def test_a_branch_on_tainted_data_taints_what_it_decides(self):
        assert flows(self.IF, implicit_flows=True) == [
            '[2] x = input()\n  --def_use x--> [3] x == "a"\n'
            '  --control--> [5] cmd = "safe"\n  --def_use cmd--> [7] system(cmd)'
        ]

    def test_nested_branches(self):
        code = (
            'def f(c):\n    x = input()\n    cmd = "a"\n'
            '    if x:\n        if c:\n            cmd = "b"\n    system(cmd)\n'
        )
        assert texts(code, implicit_flows=True) == [
            'x = input() -> x -> c -> cmd = "b" -> system(cmd)'
        ]

    def test_loops(self):
        code = "x = input()\nn = 0\nwhile n < len(x):\n    n = n + 1\nsystem(n)\n"
        assert texts(code) == []
        assert texts(code, implicit_flows=True) == [
            "x = input() -> n < len(x) -> n = n + 1 -> system(n)"
        ]

    def test_match(self):
        code = (
            'x = input()\nmatch x:\n    case "a":\n        cmd = 1\n'
            "    case _:\n        cmd = 2\nsystem(cmd)\n"
        )
        assert texts(code) == []
        assert texts(code, implicit_flows=True) == [
            "x = input() -> match x -> cmd = 1 -> system(cmd)"
        ]

    def test_returns(self):
        code = (
            'def check(x):\n    if x == "admin":\n        return True\n    return False\n\n\n'
            "ok = check(input())\nsystem(ok)\n"
        )
        assert texts(code) == []
        assert texts(code, implicit_flows=True) == [
            'ok = check(input()) -> check -> x == "admin" -> return True -> ok = check(input()) -> system(ok)'
        ]

    def test_code_after_the_branch_is_not_decided_by_it(self):
        assert (
            texts(
                'x = input()\nif x:\n    pass\ncmd = "safe"\nsystem(cmd)\n',
                implicit_flows=True,
            )
            == []
        )

    def test_a_sanitized_assignment_in_a_tainted_branch_is_tainted(self):
        code = "x = input()\nif x:\n    cmd = escape(t)\nsystem(cmd)\n"
        assert texts(code) == []
        assert texts(code, implicit_flows=True) == [
            "x = input() -> x -> cmd = escape(t) -> system(cmd)"
        ]

    def test_exceptions_are_not_implicit_flows(self):
        code = (
            "x = input()\ntry:\n    v = int(x)\nexcept E:\n    cmd = 1\nsystem(cmd)\n"
        )
        assert texts(code, implicit_flows=True) == []

    def test_sink_arguments_are_not_tainted_by_control(self):
        assert (
            texts('x = input()\nif x:\n    system("ls")\n', implicit_flows=True) == []
        )

    def test_c_switch_and_java_if(self):
        c = "void f() { int x = input(); int v = 0; switch (x) { case 1: v = 1; break; default: v = 2; } system(v); }"
        java = "class A { void f() { int x = input(); int v = 0; if (x > 1) { v = 1; } system(v); } }"
        assert texts(c, "c") == []
        assert texts(c, "c", implicit_flows=True) == [
            "int x = input(); -> (x) -> v = 1; -> system(v);"
        ]
        assert texts(java, "java") == []
        assert texts(java, "java", implicit_flows=True) == [
            "int x = input(); -> (x > 1) -> v = 1; -> system(v);"
        ]


class TestFieldSensitivity:
    @pytest.mark.parametrize(
        "code, default, sensitive",
        [
            ('d = {}\nd["k"] = input()\nsystem(d["other"])\n', 1, 0),
            ('d = {}\nd["k"] = input()\nsystem(d["k"])\n', 1, 1),
            ("d = {}\nd['k'] = input()\nsystem(d[\"k\"])\n", 1, 1),
            ('d = {}\nd["k"] = input()\nsystem(d)\n', 1, 1),
            ("d = {}\nd[0] = input()\nsystem(d[1])\n", 1, 0),
            ("o.secret = input()\nsystem(o.name)\n", 1, 0),
            ("o.secret = input()\nsystem(o.secret)\n", 1, 1),
            ('d = {}\nd[i] = input()\nsystem(d["other"])\n', 1, 1),
            ('d = {}\nd["k"] = input()\nsystem(d[j])\n', 1, 1),
            ('d = input()\nsystem(d["other"])\n', 1, 1),
            ('d = {}\nd["k"] = input()\ne = d\nsystem(e["other"])\n', 1, 1),
            ('d = {}\nd["k"] = escape(input())\nsystem(d["k"])\n', 0, 0),
        ],
    )
    def test_reads_and_writes(self, code, default, sensitive):
        assert len(flows(code)) == default
        assert len(flows(code, field_sensitive=True)) == sensitive

    def test_tags_are_shown_and_kept_across_other_writes(self):
        code = 'd = {}\nd["k"] = input()\nd["other"] = "safe"\nsystem(d["k"])\nsystem(d["other"])\n'
        assert flows(code, field_sensitive=True) == [
            '[3] d["k"] = input()\n  --def_use d[k]--> [4] d["other"] = "safe"\n'
            '  --def_use d[k]--> [5] system(d["k"])'
        ]
        assert len(flows(code)) == 2

    def test_a_deeper_write_taints_the_first_level_field(self):
        code = "self.items[0] = input()\nsystem(self.items)\nsystem(self.other)\n"
        assert texts(code, field_sensitive=True) == [
            "self.items[0] = input() -> system(self.items)"
        ]

    def test_objects_keep_their_fields_into_methods(self):
        code = (
            "class A:\n"
            "    def __init__(self):\n"
            "        self.debug = input()\n"
            '        self.name = "a"\n'
            "        self.run()\n\n"
            "    def run(self):\n"
            "        system(self.name)\n"
            "        system(self.debug)\n"
        )
        assert len(flows(code)) == 2
        assert flows(code, field_sensitive=True) == [
            "[5] self.debug = input()\n"
            '  --def_use self.debug--> [6] self.name = "a"\n'
            "  --def_use self.debug--> [7] self.run()\n"
            "  --argument self--> [8] ENTRY A.run\n"
            "  --def_use self.debug--> [11] system(self.debug)"
        ]

    def test_a_bare_argument_carries_its_fields(self):
        code = (
            'def show(d):\n    system(d["name"])\n    system(d["q"])\n\n\n'
            'd = {}\nd["q"] = input()\nshow(d)\n'
        )
        assert texts(code, field_sensitive=True) == [
            'd["q"] = input() -> show(d) -> show -> system(d["q"])'
        ]
        assert len(texts(code)) == 2

    def test_c_structs(self):
        code = "void f() { struct S s; s.a = input(); system(s.b); system(s.a); }"
        assert len(flows(code, "c")) == 2
        assert texts(code, "c", field_sensitive=True) == [
            "s.a = input(); -> system(s.a);"
        ]

    def test_java_reads(self):
        code = "class A { void f() { Req p = input(); system(p.a); } }"
        assert len(flows(code, "java", field_sensitive=True)) == 1

    def test_both_options_together(self):
        code = 'd = {}\nd["k"] = input()\nif d["other"]:\n    cmd = 1\nelse:\n    cmd = 2\nsystem(cmd)\n'
        assert len(flows(code, implicit_flows=True)) == 1
        assert flows(code, implicit_flows=True, field_sensitive=True) == []


def test_the_guide_example():
    rule = Rule("r", sources=[Source(call="input")], sinks=[Sink(call="system")])
    code = 'd = {}\nd["k"] = input()\nd["other"] = "safe"\nsystem(d["other"])\nsystem(d["k"])\n'

    found = analyze_source("python", code, rule, field_sensitive=True)
    assert [str(f.path) for f in found] == [
        '[3] d["k"] = input()\n'
        '  --def_use d[k]--> [4] d["other"] = "safe"\n'
        '  --def_use d[k]--> [6] system(d["k"])'
    ]
    assert len(analyze_source("python", code, rule)) == 2
