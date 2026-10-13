"""Programs and helpers shared by the query tests.

The same program is written in Python, C and Java so that each query can be
checked in all three languages. Nodes are named by role (see `roles`), and
expectations are written in roles, so they read the same for every language.

    helper(n): returns n + 1
    main():
        x = input()          # src
        y = clean(x)         # clean
        if y:                # cond
            system(y)        # sink
        else:
            y = 0            # reset
        total = 0            # zero
        while total < 10:    # loop
            total = total + y  # acc
        r = helper(total)    # ret
        return r             # out
"""

from typing import Dict, List, Tuple

import pytest

from tree_climber.cfg.cfg_types import CFGNode
from tree_climber.query import CodeGraph

PYTHON = """\
def helper(n):
    return n + 1


def main():
    x = input()
    y = clean(x)
    if y:
        system(y)
    else:
        y = 0
    total = 0
    while total < 10:
        total = total + y
    r = helper(total)
    return r
"""

C = """\
int helper(int n) { return n + 1; }

int main() {
    int x = input();
    int y = clean(x);
    if (y) {
        system(y);
    } else {
        y = 0;
    }
    int total = 0;
    while (total < 10) {
        total = total + y;
    }
    int r = helper(total);
    return r;
}
"""

JAVA = """\
class A {
    int helper(int n) { return n + 1; }

    int main() {
        int x = input();
        int y = clean(x);
        if (y > 0) {
            system(y);
        } else {
            y = 0;
        }
        int total = 0;
        while (total < 10) {
            total = total + y;
        }
        int r = helper(total);
        return r;
    }
}
"""

SOURCES = {"python": PYTHON, "c": C, "java": JAVA}

LANGUAGES = pytest.mark.parametrize("language", sorted(SOURCES))


def build(language: str) -> CodeGraph:
    return CodeGraph.from_source(language, SOURCES[language])


def roles(graph: CodeGraph) -> Dict[str, CFGNode]:
    entries = {entry.source_text.split(".")[-1]: entry for entry in graph.functions()}
    return {
        "helper_entry": entries["helper"],
        "main_entry": entries["main"],
        "helper_exit": graph.by_type("EXIT")[0],
        "main_exit": graph.by_type("EXIT")[1],
        "helper_ret": graph.by_text("n + 1")[0],
        "src": graph.calling("input")[0],
        "clean": graph.calling("clean")[0],
        "cond": graph.by_type("CONDITION")[0],
        "sink": graph.calling("system")[0],
        "reset": graph.by_text("y = 0")[0],
        "zero": graph.by_text("total = 0")[0],
        "loop": graph.by_type("LOOP_HEADER")[0],
        "acc": graph.by_text("total = total + y")[0],
        "ret": graph.calling("helper")[0],
        "out": graph.by_text("return r")[0],
    }


def named(graph: CodeGraph, nodes) -> List[str]:
    by_id = {node.id: role for role, node in roles(graph).items()}
    return [by_id.get(getattr(node, "id", node), "?") for node in nodes]


def ids(graph: CodeGraph, *names: str) -> List[int]:
    found = roles(graph)
    return [found[name].id for name in names]


def pair(graph: CodeGraph, first: str, second: str) -> Tuple[int, int]:
    found = roles(graph)
    return found[first].id, found[second].id
