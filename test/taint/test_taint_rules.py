"""Taint rules: matching, validation, loading, and the built-in example rules."""

import json

import pytest

from tree_climber.cfg.cfg_types import CallArgument, CallSite
from tree_climber.taint import (
    Rule,
    RuleSet,
    Sink,
    Source,
    analyze_source,
    builtin_rules,
)
from tree_climber.taint.rules import call_matches


def site(callee, callee_text, *arguments):
    return CallSite(callee=callee, callee_text=callee_text, arguments=list(arguments))


class TestMatching:
    def test_call_patterns_match_the_whole_callee(self):
        system = site("system", "os.system")

        assert not call_matches("system", system)
        assert call_matches("system", site("system", "system"))
        assert call_matches("os.system", system)
        assert call_matches("*system", system)
        assert not call_matches("eval", site("eval", "self.tk.eval"))
        assert call_matches("os.*", system)
        assert not call_matches("sys", system)
        assert not call_matches("subprocess.system", system)
        assert call_matches("*.execute", site("execute", "self.db.cursor().execute"))
        assert not call_matches("f", site(None, "handlers[k]"))

    def test_patterns_are_case_sensitive(self):
        assert not call_matches("System", site("system", "system"))

    def test_attribute_patterns(self):
        pattern = Source(attribute="request.args").attribute_pattern()
        assert pattern is not None

        assert pattern.search("request.args.get('q')")
        assert pattern.search("x = request.args")
        assert not pattern.search("request.argsx")
        assert not pattern.search("self.request.args")
        assert not pattern.search("myrequest.args")
        assert Source(call="f").attribute_pattern() is None
        wild = Source(attribute="request.*").attribute_pattern()
        assert wild is not None and wild.search("request.form")
        assert not wild.search("request")

    def test_attribute_patterns_are_compiled_once(self):
        first = Source(attribute="request.args").attribute_pattern()

        assert Source(attribute="request.args").attribute_pattern() is first
        assert Source(attribute="request.form").attribute_pattern() is not first

    @pytest.mark.parametrize(
        "attribute, literal",
        [
            ("request.args", "request"),
            ("sys.argv", "argv"),
            ("*.args", "args"),
            ("request.*", "request"),
            ("*.*", ""),
        ],
    )
    def test_the_attribute_literal_is_its_longest_named_part(self, attribute, literal):
        assert Source(attribute=attribute).attribute_literal() == literal

    def test_sinks_watch_positions_and_keywords(self):
        call = site(
            "execute",
            "c.execute",
            CallArgument("q"),
            CallArgument("p", keyword="sql", kind="keyword"),
            CallArgument("rest", kind="star"),
        )
        assert Sink("execute", [0]).watches(call, 0)
        assert not Sink("execute", [1]).watches(call, 0)
        assert Sink("execute", ["sql"]).watches(call, 1)
        assert not Sink("execute", [1]).watches(call, 1)
        assert Sink("execute", [5]).watches(call, 2)
        assert Sink("execute").watches(call, 1)

    def test_positions_skip_keyword_arguments(self):
        call = site(
            "f",
            "f",
            CallArgument("a", keyword="k", kind="keyword"),
            CallArgument("b"),
        )
        assert Sink("f", [0]).watches(call, 1)


class TestValidation:
    @pytest.mark.parametrize(
        "fields",
        [{}, {"call": "a", "attribute": "b"}, {"call": "a", "parameter": "p"}],
    )
    def test_a_source_has_exactly_one_kind(self, fields):
        with pytest.raises(ValueError):
            Source(**fields)

    def test_parameter_zero_is_a_parameter(self):
        assert Source(parameter=0).parameter == 0

    def test_unknown_rule_keys_are_rejected(self):
        with pytest.raises(ValueError, match="sink"):
            Rule.from_dict({"id": "r", "sources": [], "sink": []})

    def test_unknown_source_keys_are_rejected(self):
        with pytest.raises(TypeError):
            Rule.from_dict({"id": "r", "sources": [{"cal": "x"}]})

    def test_rule_ids_are_unique(self):
        with pytest.raises(ValueError, match="unique"):
            RuleSet.from_dict({"rules": [{"id": "a"}, {"id": "a"}]})


RULES = {
    "rules": [
        {
            "id": "cmd",
            "description": "shell commands",
            "languages": ["python"],
            "sources": [
                {"call": "input"},
                {"parameter": "request", "function": "handler"},
                {"attribute": "sys.argv"},
            ],
            "sinks": [{"call": "os.system", "arguments": [0]}, {"call": "eval"}],
            "sanitizers": [{"call": "shlex.quote"}],
        }
    ]
}


class TestLoading:
    def test_from_dict(self):
        (rule,) = RuleSet.from_dict(RULES).rules

        assert rule.id == "cmd"
        assert rule.languages == ["python"]
        assert rule.sources == (
            Source(call="input"),
            Source(parameter="request", function="handler"),
            Source(attribute="sys.argv"),
        )
        assert rule.sinks == (Sink("os.system", (0,)), Sink("eval"))
        assert [s.call for s in rule.sanitizers] == ["shlex.quote"]

    def test_round_trip(self):
        rules = RuleSet.from_dict(RULES)

        assert RuleSet.from_dict(json.loads(json.dumps(rules.to_dict()))) == rules

    def test_from_json_and_load(self, tmp_path):
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(RULES))

        assert RuleSet.load(path) == RuleSet.from_json(json.dumps(RULES))
        assert RuleSet.load(str(path)).rules[0].id == "cmd"

    def test_for_language(self):
        rules = RuleSet.from_dict(RULES)

        assert rules.for_language("python") == list(rules.rules)
        assert rules.for_language("c") == []
        assert rules.for_language(None) == list(rules.rules)

    def test_loaded_rules_run(self):
        rules = RuleSet.from_dict(RULES)
        code = (
            "import os, shlex, sys\n\n\n"
            "def handler(request):\n    os.system(request)\n    os.system(shlex.quote(request))\n\n\n"
            "eval(sys.argv[1])\n"
        )
        found = analyze_source("python", code, rules)

        assert [(f.rule, " -> ".join(f.path.texts)) for f in found] == [
            ("cmd", "handler -> os.system(request)"),
            ("cmd", "eval(sys.argv[1])"),
        ]


PYTHON = """import os, shlex, subprocess
from flask import request


def ping():
    host = request.args.get("host")
    os.system("ping -c 1 " + host)
    os.system("ping -c 1 " + shlex.quote(host))


def search(cursor):
    term = request.args["q"]
    cursor.execute("SELECT * FROM t WHERE name = '" + term + "'")
    cursor.execute("SELECT * FROM t WHERE name = ?", (term,))


def calc():
    eval(input())
"""

C = """int main(int argc, char **argv) {
    printf(argv[1]);
    printf("%s", argv[1]);
    char *cmd = getenv("CMD");
    system(cmd);
    return 0;
}
"""

JAVA = """class Servlet {
    void doGet(HttpServletRequest request, Statement statement) throws Exception {
        String user = request.getParameter("user");
        statement.executeQuery("SELECT * FROM users WHERE name = '" + user + "'");
        PreparedStatement ps = connection.prepareStatement("SELECT * FROM users WHERE name = ?");
        ps.setString(1, user);
        Runtime.getRuntime().exec("ping " + request.getHeader("Host"));
    }
}
"""


class TestBuiltinRules:
    def test_rules_per_language(self):
        assert [r.id for r in builtin_rules("python").rules] == [
            "python-command-injection",
            "python-code-injection",
            "python-sql-injection",
        ]
        assert [r.id for r in builtin_rules("c").rules] == [
            "c-command-injection",
            "c-format-string",
        ]
        assert [r.id for r in builtin_rules("java").rules] == [
            "java-command-injection",
            "java-sql-injection",
        ]
        assert len(builtin_rules().rules) == 7
        assert all(r.description.startswith("Example") for r in builtin_rules().rules)

    @pytest.mark.parametrize(
        "language, code, expected",
        [
            (
                "python",
                PYTHON,
                [
                    ("python-code-injection", "eval(input())"),
                    (
                        "python-command-injection",
                        'os.system("ping -c 1 " + host)',
                    ),
                    (
                        "python-sql-injection",
                        'cursor.execute("SELECT * FROM t WHERE name = \'" + term + "\'")',
                    ),
                ],
            ),
            (
                "c",
                C,
                [
                    ("c-command-injection", "system(cmd);"),
                    ("c-format-string", "printf(argv[1]);"),
                ],
            ),
            (
                "java",
                JAVA,
                [
                    (
                        "java-command-injection",
                        'Runtime.getRuntime().exec("ping " + request.getHeader("Host"));',
                    ),
                    (
                        "java-sql-injection",
                        'statement.executeQuery("SELECT * FROM users WHERE name = \'" + user + "\'");',
                    ),
                ],
            ),
        ],
    )
    def test_examples(self, language, code, expected):
        found = analyze_source(language, code, builtin_rules(language))

        assert sorted((f.rule, f.path.texts[-1]) for f in found) == sorted(expected)
