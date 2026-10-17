"""
Tests for the FastAPI endpoints in tree_climber.viz.app.

The endpoints are called directly, so no running server is needed.
"""

import asyncio
import inspect
import threading
import time

import pytest
from pydantic import ValidationError

from tree_climber.language_registry import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES
from tree_climber.query import graph as graph_module
from tree_climber.viz import app
from tree_climber.viz.app import (
    CACHED_ANALYSES,
    ParseRequest,
    QueryRequest,
    TaintRequest,
    health_check,
    parse_source_code,
    query_source_code,
    root,
    taint_source_code,
)

C_SOURCE = """
int foo() {
    int x = 42;
    return x;
}
"""

JAVA_SOURCE = """
public class Test {
    public static int foo() {
        int x = 42;
        return x;
    }
}
"""


def test_root_endpoint():
    result = asyncio.run(root())

    assert "version" in result
    assert result["supported_languages"] == SUPPORTED_LANGUAGES
    assert "python" in result["supported_languages"]


def test_health_endpoint():
    assert asyncio.run(health_check()) == {"status": "healthy"}


@pytest.mark.parametrize(
    "language, source", [("c", C_SOURCE), ("java", JAVA_SOURCE)], ids=["c", "java"]
)
def test_parse_endpoint(language, source):
    request = ParseRequest.model_validate({"source_code": source, "language": language})

    response = parse_source_code(request)

    assert response.success, response.error
    assert response.cfg is not None
    assert len(response.cfg["nodes"]) > 0
    assert response.cfg["entry_node_ids"]
    assert response.cfg["exit_node_ids"]
    assert response.ast is not None
    assert response.dfg is not None
    assert response.dfg["edges"], "x = 42 should reach its use in the return"


def test_parse_endpoint_python():
    source = "def foo():\n    x = 42\n    return x\n"
    request = ParseRequest.model_validate({"source_code": source, "language": "python"})

    response = parse_source_code(request)

    assert response.success, response.error
    assert response.cfg is not None
    assert len(response.cfg["nodes"]) > 0
    assert response.cfg["entry_node_ids"]
    assert response.ast is not None
    assert response.dfg is not None
    assert response.dfg["edges"], "x = 42 should reach its use in the return"


def test_unsupported_language_is_rejected():
    with pytest.raises(ValidationError, match="Unsupported language: cobol"):
        ParseRequest.model_validate({"source_code": C_SOURCE, "language": "cobol"})


def test_language_defaults_to_registry_default():
    request = ParseRequest.model_validate({"source_code": C_SOURCE})

    assert request.language == DEFAULT_LANGUAGE


TAINTED = """\
import os


def handler():
    name = input()
    run(name)


def run(command):
    os.system(command)
"""


def taint(**body):
    request = TaintRequest.model_validate({"language": "python", **body})
    return taint_source_code(request)


def query(**body):
    request = QueryRequest.model_validate({"language": "python", **body})
    return query_source_code(request)


def test_root_lists_the_new_endpoints():
    assert {"/taint", "/query"} <= set(asyncio.run(root())["endpoints"])


def test_taint_with_the_builtin_rules():
    response = taint(source_code=TAINTED)

    assert response.success, response.error
    assert [f["rule"] for f in response.findings] == ["python-command-injection"]
    finding = response.findings[0]
    assert finding["sink_call"] == "os.system"
    assert [step["edge"] for step in finding["path"]["steps"]] == [
        None,
        "def_use",
        "argument",
        "def_use",
    ]


def test_taint_node_ids_are_those_of_parse():
    parsed = parse_source_code(
        ParseRequest.model_validate({"source_code": TAINTED, "language": "python"})
    )
    assert parsed.cfg is not None

    steps = taint(source_code=TAINTED).findings[0]["path"]["steps"]

    for step in steps:
        node = parsed.cfg["nodes"][step["node"]]
        assert node["node_type"] == step["node_type"]
        assert node["source_text"].splitlines()[0] == step["text"]
        assert node["start_index"] is not None


def test_taint_with_rules_in_the_request():
    rules = {
        "rules": [
            {
                "id": "run",
                "sources": [{"call": "input"}],
                "sinks": [{"call": "run"}],
            }
        ]
    }

    response = taint(source_code=TAINTED, rules=rules)

    assert response.success, response.error
    assert [(f["rule"], f["sink_call"]) for f in response.findings] == [("run", "run")]


@pytest.mark.parametrize(
    "rules, message",
    [
        ({"rules": [{"id": "x", "bad": 1}]}, "Unknown rule keys"),
        ({"rules": [{"sinks": []}]}, "missing key 'id'"),
        ({"rules": [{"id": "x", "languages": ["c"]}]}, "No rules for python"),
    ],
)
def test_taint_with_bad_rules(rules, message):
    response = taint(source_code=TAINTED, rules=rules)

    assert not response.success
    assert response.findings == []
    assert response.error is not None and message in response.error


def test_taint_without_findings():
    response = taint(source_code="x = 1\n")

    assert response.success
    assert response.findings == []


def test_taint_in_c():
    source = 'int main() { char *c = getenv("C"); system(c); return 0; }\n'

    response = taint(source_code=source, language="c")

    assert [f["rule"] for f in response.findings] == ["c-command-injection"]


def test_taint_language_is_validated():
    with pytest.raises(ValidationError, match="Unsupported language: cobol"):
        TaintRequest.model_validate({"source_code": "", "language": "cobol"})


def test_query_calls():
    response = query(source_code=TAINTED, kind="calls", names=["system"])

    assert response.success, response.error
    assert response.nodes == [
        {
            "node": 9,
            "node_type": "STATEMENT",
            "text": "os.system(command)",
            "line": 10,
            "function": "run",
        }
    ]


def test_query_slices():
    forward = query(source_code=TAINTED, kind="slice", line=5)
    within = query(source_code=TAINTED, kind="slice", line=5, across_calls=False)
    backward = query(source_code=TAINTED, kind="slice", line=10, backward=True)

    assert [n["line"] for n in forward.nodes] == [5, 6, 9, 10]
    assert [n["line"] for n in within.nodes] == [5, 6]
    assert [n["text"] for n in backward.nodes] == [
        "import os",
        "name = input()",
        "run(name)",
        "run",
        "os.system(command)",
    ]


def test_query_slice_of_one_variable():
    source = "a, b = f()\nprint(a)\nprint(b)\n"

    response = query(source_code=source, kind="slice", line=1, variable="a")

    assert [n["text"] for n in response.nodes] == ["a, b = f()", "print(a)"]


@pytest.mark.parametrize(
    "body, message",
    [
        ({"kind": "calls"}, "needs names"),
        ({"kind": "slice"}, "needs a line"),
        ({"kind": "slice", "line": 3}, "No statement on line 3"),
    ],
)
def test_query_errors(body, message):
    response = query(source_code=TAINTED, **body)

    assert not response.success
    assert response.error is not None and message in response.error


@pytest.mark.parametrize(
    "body",
    [{"kind": "callers"}, {"kind": "slice", "line": 0}, {}],
    ids=["unknown kind", "line 0", "no kind"],
)
def test_query_request_is_validated(body):
    with pytest.raises(ValidationError):
        QueryRequest.model_validate({"source_code": TAINTED, **body})


@pytest.mark.parametrize(
    "endpoint", [parse_source_code, taint_source_code, query_source_code]
)
def test_analysis_endpoints_run_in_the_thread_pool(endpoint):
    assert not inspect.iscoroutinefunction(endpoint)


def test_parse_without_the_ast_skips_building_it(monkeypatch):
    monkeypatch.setattr(
        "tree_climber.viz.app.ast_to_json",
        lambda node: pytest.fail("the AST was built"),
    )
    request = ParseRequest.model_validate(
        {"source_code": C_SOURCE, "language": "c", "include_ast": False}
    )

    response = parse_source_code(request)

    assert response.success, response.error
    assert response.ast is None
    assert response.cfg is not None and response.cfg["nodes"]
    assert response.dfg is not None and response.dfg["edges"]


def test_parse_includes_the_ast_by_default():
    request = ParseRequest.model_validate({"source_code": C_SOURCE, "language": "c"})

    assert request.include_ast
    assert parse_source_code(request).ast is not None


def test_only_parse_takes_include_ast():
    assert "include_ast" not in TaintRequest.model_fields
    assert "include_ast" not in QueryRequest.model_fields


@pytest.fixture
def solves(monkeypatch):
    """The reaching-definitions solves, each slowed down so that concurrent
    requests overlap."""
    app._analyses.clear()
    calls = []
    original = graph_module.ReachingDefinitionsProblem

    def counted():
        calls.append(1)
        time.sleep(0.2)
        return original()

    monkeypatch.setattr(graph_module, "ReachingDefinitionsProblem", counted)
    yield calls
    app._analyses.clear()


def test_one_edit_is_analysed_once(solves):
    body = {"source_code": TAINTED, "language": "python"}

    parsed = parse_source_code(ParseRequest.model_validate(body))
    tainted = taint_source_code(TaintRequest.model_validate(body))
    queried = query_source_code(
        QueryRequest.model_validate({**body, "kind": "calls", "names": ["input"]})
    )

    assert parsed.success and tainted.success and queried.success
    assert tainted.findings and queried.nodes
    assert len(solves) == 1


def test_concurrent_requests_wait_for_one_analysis(solves):
    body = {"source_code": TAINTED, "language": "python"}
    responses = []
    requests = [
        lambda: parse_source_code(ParseRequest.model_validate(body)),
        lambda: taint_source_code(TaintRequest.model_validate(body)),
    ]
    threads = [
        threading.Thread(target=lambda r=request: responses.append(r()))
        for request in requests
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert all(response.success for response in responses)
    assert len(solves) == 1


def test_other_sources_and_languages_are_analysed_afresh(solves):
    for language, source in [
        ("python", TAINTED),
        ("python", TAINTED + "\n"),
        ("c", C_SOURCE),
        ("java", C_SOURCE),
    ]:
        request = ParseRequest.model_validate(
            {"source_code": source, "language": language}
        )
        assert parse_source_code(request).success

    assert len(solves) == 4


def test_only_the_last_sources_are_kept(solves):
    sources = [f"x = {n}\n" for n in range(CACHED_ANALYSES + 1)]
    for source in sources:
        parse_source_code(ParseRequest.model_validate({"source_code": source}))
    parse_source_code(ParseRequest.model_validate({"source_code": sources[-1]}))
    assert len(solves) == CACHED_ANALYSES + 1

    parse_source_code(ParseRequest.model_validate({"source_code": sources[0]}))
    assert len(solves) == CACHED_ANALYSES + 2
    assert len(app._analyses) == CACHED_ANALYSES


def test_a_failed_analysis_is_not_kept(solves, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("no CFG")

    request = ParseRequest.model_validate({"source_code": C_SOURCE, "language": "c"})
    with monkeypatch.context() as patch:
        patch.setattr("tree_climber.viz.app.CFGBuilder.build_cfg", broken)
        assert parse_source_code(request).error == "no CFG"

    assert parse_source_code(request).success
