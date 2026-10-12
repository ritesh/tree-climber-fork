"""
Tests for the FastAPI endpoints in tree_climber.viz.app.

The endpoint coroutines are called directly, so no running server is needed.
"""

import asyncio

import pytest

from tree_climber.viz.app import (
    ParseRequest,
    health_check,
    parse_source_code,
    root,
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
    assert result["supported_languages"] == ["c", "java"]


def test_health_endpoint():
    assert asyncio.run(health_check()) == {"status": "healthy"}


@pytest.mark.parametrize(
    "language, source", [("c", C_SOURCE), ("java", JAVA_SOURCE)], ids=["c", "java"]
)
def test_parse_endpoint(language, source):
    request = ParseRequest.model_validate({"source_code": source, "language": language})

    response = asyncio.run(parse_source_code(request))

    assert response.success, response.error
    assert response.cfg is not None
    assert len(response.cfg["nodes"]) > 0
    assert response.cfg["entry_node_ids"]
    assert response.cfg["exit_node_ids"]
    assert response.ast is not None
    assert response.dfg is not None
    assert response.dfg["edges"], "x = 42 should reach its use in the return"
