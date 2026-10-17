from typing import override

import pygraphviz as pgv
from tree_sitter import Node

from tree_climber.ast_utils import iter_ast_edges
from tree_climber.cli.visualizers.base_visualizer import (
    BaseVisualizer,
    get_node_display,
    get_node_label,
)
from tree_climber.cli.visualizers.utils import ast_label, draw_graph

from .constants import (
    AST_OVERLAY_BORDER_COLOR,
    AST_OVERLAY_EDGE_COLOR,
    AST_OVERLAY_FONT_SIZE,
    AST_OVERLAY_LINKING_EDGE_COLOR,
    AST_OVERLAY_NODE_COLOR,
    AST_OVERLAY_SHOW_ONLY_NAMED,
)


class BiGraphVisualizer(BaseVisualizer):
    @override
    def visualize(self):
        ast_root = self.ast_root
        cfg = self.cfg
        duc_edges = self.duc_edges

        # Combined CPG graph (AST + CFG + optional DFG overlay)
        if ast_root is None:
            raise ValueError("AST required to draw CPG")
        if cfg is None:
            raise ValueError("CFG required to draw CPG")
        if duc_edges is None:
            raise ValueError("DFG required to draw CPG")
        G = pgv.AGraph(strict=False, directed=True)
        G.graph_attr.update(
            ranksep="0.2",
            nodesep="0.45",
            rankdir="TB",
            splines=True,
            margin="0.05",
            bgcolor="white",
        )
        G.node_attr.update(style="filled")

        def add_ast_node(ts_node: Node):
            nid = f"ast_{ts_node.id}"
            if not G.has_node(nid):
                G.add_node(
                    nid,
                    label=ast_label(ts_node),
                    shape="box",
                    fontsize=str(AST_OVERLAY_FONT_SIZE),
                    fillcolor=AST_OVERLAY_NODE_COLOR,
                    color=AST_OVERLAY_BORDER_COLOR,
                    style="filled",
                )

        root = ast_root.root_node
        add_ast_node(root)
        for parent, child in iter_ast_edges(root, AST_OVERLAY_SHOW_ONLY_NAMED):
            add_ast_node(child)
            G.add_edge(
                f"ast_{parent.id}",
                f"ast_{child.id}",
                arrowhead="none",
                tailport="s",
                headport="n",
                color=AST_OVERLAY_EDGE_COLOR,
            )

        # Add CFG nodes and link each to its AST node if available
        for node_id, node in cfg.nodes.items():
            color, shape = get_node_display(node)
            node_label = get_node_label(node)
            G.add_node(node_id, label=node_label, shape=shape, fillcolor=color)
            ts_node = node.ast_node
            if ts_node is not None:
                ast_nid = f"ast_{ts_node.id}"
                if G.has_node(ast_nid):
                    G.add_subgraph(
                        [node_id, ast_nid], name=f"rank_pair_{node_id}"
                    ).graph_attr.update(rank="same")
                    G.add_edge(
                        node_id,
                        ast_nid,
                        style="dotted",
                        color=AST_OVERLAY_LINKING_EDGE_COLOR,
                        arrowhead="none",
                        penwidth="1",
                        headlabel=node_label,
                        labelfontsize=str(AST_OVERLAY_FONT_SIZE),
                        labelfontcolor=AST_OVERLAY_LINKING_EDGE_COLOR,
                    )

        # Add CFG edges
        for node_id, node in cfg.nodes.items():
            for succ in node.successors:
                label = node.edge_labels.get(succ, "")
                G.add_edge(node_id, succ, color="black", label=label)

        # Add DFG edges
        for (node_id, successor_id), variables in duc_edges.items():
            dfg_label = ", ".join(sorted(variables))
            G.add_edge(
                node_id,
                successor_id,
                color="red",
                style="dashed",
                fontcolor="red",
                label=dfg_label,
            )

        draw_graph(G, self.output_path("cpg"))
        print(f"Saved CPG visualization: {self.output_path('cpg')}")
