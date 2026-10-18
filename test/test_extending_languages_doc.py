"""
The sample visitor in docs/plans/extending-languages.md runs, and on C code gives
the same graph, metadata, def-use chains and argument flows as the C visitor.
"""

import re
from pathlib import Path

from tree_sitter_languages import get_parser

from tree_climber.query import CodeGraph

DOC = (
    Path(__file__).parents[1] / "docs" / "plans" / "extending-languages.md"
).read_text()
SAMPLES = re.findall(r"^```python\n(.*?)^```$", DOC, re.M | re.S)
SOURCE = """int z;
int f(int n) {
  while (n) {
    n = g(n);
    break;
  }
  h(n);
}
int g(int x) {
  while (x) {
    x = x;
  }
}
"""


def facts(graph):
    return [
        (
            node.node_type,
            node.source_text,
            sorted(node.successors),
            node.metadata.variable_definitions,
            node.metadata.variable_uses,
            [(a.text, a.uses) for s in node.metadata.call_sites for a in s.arguments],
        )
        for _, node in sorted(graph.cfg.nodes.items())
    ]


def test_the_sample_visitor_matches_the_c_visitor():
    namespace: dict = {}
    exec(SAMPLES[0], namespace)
    visitor = namespace["MyLangCFGVisitor"]()
    visitor.visit(get_parser("c").parse(SOURCE.encode()).root_node)
    visitor.postprocess_cfg()
    sample = CodeGraph(visitor.cfg)
    c = CodeGraph.from_source("c", SOURCE)

    assert facts(sample) == facts(c)
    assert sample.def_use_chains.chains == c.def_use_chains.chains
    assert sample.interprocedural_flows.argument_flows
    assert (
        sample.interprocedural_flows.argument_flows
        == c.interprocedural_flows.argument_flows
    )
