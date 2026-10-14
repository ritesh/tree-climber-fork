"""The fields and constant keys a statement reads and writes."""

import pytest
from tree_sitter_languages import get_parser

from tree_climber.taint.fields import accesses


def statement(language, source):
    tree = get_parser(language).parse(source.encode())
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "expression_statement":
            return node
        stack.extend(reversed(node.children))
    raise AssertionError("no statement")


def of(language, source):
    found = accesses(statement(language, source))
    return {k: sorted(v, key=str) for k, v in found.reads.items()}, found.writes


@pytest.mark.parametrize(
    "source, reads, writes",
    [
        ('d["k"] = x', {"x": [None]}, {"d": "[k]"}),
        ("d['k'] = x", {"x": [None]}, {"d": "[k]"}),
        ('y = d["k"] + d[0] + o.a', {"d": ["[0]", "[k]"], "o": [".a"]}, {}),
        ("y = d[i]", {"d": [None], "i": [None]}, {}),
        ("y = d", {"d": [None]}, {}),
        ('d["k"] += 1', {"d": ["[k]"]}, {"d": "[k]"}),
        ("d[i] = 2", {"i": [None]}, {"d": None}),
        ("a.b, c[1] = t", {"t": [None]}, {"a": ".b", "c": "[1]"}),
        ("(a.b, c) = t", {"t": [None]}, {"a": ".b"}),
        ("x = x + 1", {"x": [None]}, {}),
        ("x += 1", {"x": [None]}, {}),
        ("self.items[0] = v", {"v": [None]}, {"self": ".items"}),
        ("y = self.items[0]", {"self": [".items"]}, {}),
        ('d["a"]["b"] = 1', {}, {"d": "[a]"}),
        ("self.run(x)", {"self": [None], "x": [None]}, {}),
        ("y = o.x", {"o": [".x"]}, {}),
        ("y = f(o).x", {"f": [None], "o": [None]}, {}),
        ("y = d[True]", {"d": ["[True]"]}, {}),
    ],
)
def test_python(source, reads, writes):
    assert of("python", source) == (reads, writes)


@pytest.mark.parametrize(
    "source, reads, writes",
    [
        ("s.a = x;", {"x": [None]}, {"s": ".a"}),
        ("s.a += x;", {"s": [".a"], "x": [None]}, {"s": ".a"}),
        ("y = s.b + arr[0] + p->c;", {"arr": ["[0]"], "p": [".c"], "s": [".b"]}, {}),
        ("arr[i] = 3;", {"i": [None]}, {"arr": None}),
        ("y = x;", {"x": [None]}, {}),
    ],
)
def test_c(source, reads, writes):
    assert of("c", f"void f() {{ {source} }}") == (reads, writes)


@pytest.mark.parametrize(
    "source, reads, writes",
    [
        ("o.a = x;", {"x": [None]}, {"o": ".a"}),
        ("o.a += x;", {"o": [".a"], "x": [None]}, {"o": ".a"}),
        ("y = o.b + arr[0] + this.c;", {"arr": ["[0]"], "o": [".b"]}, {}),
        ("y = arr[i];", {"arr": [None], "i": [None]}, {}),
    ],
)
def test_java(source, reads, writes):
    assert of("java", f"class A {{ void f() {{ {source} }} }}") == (reads, writes)
