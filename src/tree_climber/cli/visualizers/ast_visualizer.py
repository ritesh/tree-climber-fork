from typing import override

import pygraphviz as pgv
from tree_sitter import Node

from tree_climber.cli.visualizers.base_visualizer import (
    BaseVisualizer,
)
from tree_climber.ast_utils import iter_ast_edges
from tree_climber.cli.visualizers.utils import ast_label

from .constants import (
    AST_OVERLAY_BORDER_COLOR,
    AST_OVERLAY_EDGE_COLOR,
    AST_OVERLAY_FONT_SIZE,
    AST_OVERLAY_NODE_COLOR,
    AST_OVERLAY_SHOW_ONLY_NAMED,
    DEFAULT_DPI,
)


class ASTVisualizer(BaseVisualizer):
    @override
    def visualize(self):
        options = self.options
        ast_root = self.ast_root
        if not options.draw_ast:
            return
        if ast_root is None:
            raise ValueError("AST root required to draw AST")
        G_ast = pgv.AGraph(strict=False, directed=True)
        G_ast.graph_attr.update(
            ranksep="0.5",
            nodesep="0.2",
            dpi=str(DEFAULT_DPI),
            splines="line",
        )
        G_ast.node_attr.update(style="filled")
        G_ast.edge_attr.update(
            arrowhead="none",
            tailport="s",
            headport="n",
            penwidth="1",
            color=AST_OVERLAY_EDGE_COLOR,
        )

        def add_ast_node(G: pgv.AGraph, ts_node: Node, nid: str):
            G.add_node(
                nid,
                label=ast_label(ts_node),
                shape="box",
                fontsize=str(AST_OVERLAY_FONT_SIZE),
                fillcolor=AST_OVERLAY_NODE_COLOR,
                color=AST_OVERLAY_BORDER_COLOR,
            )

        root = ast_root.root_node
        add_ast_node(G_ast, root, f"ast_{root.id}")
        for parent, child in iter_ast_edges(root, AST_OVERLAY_SHOW_ONLY_NAMED):
            cid = f"ast_{child.id}"
            if not G_ast.has_node(cid):
                add_ast_node(G_ast, child, cid)
            G_ast.add_edge(f"ast_{parent.id}", cid)
        G_ast.draw(str(self.output_path("ast")), prog="dot")
        print(f"Saved AST visualization: {self.output_path('ast')}")
