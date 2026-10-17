from typing import override

import pygraphviz as pgv

from tree_climber.cli.visualizers.base_visualizer import (
    BaseVisualizer,
    get_node_display,
)
from tree_climber.cli.visualizers.dfg_visualizer import add_dfg_edge
from tree_climber.cli.visualizers.utils import add_cfg_node, draw_graph


class CFGVisualizer(BaseVisualizer):
    @override
    def visualize(self):
        options = self.options
        if not options.draw_cfg:
            return

        draw_graph(self.graph(), self.output_path("cfg"))
        name = "CFG"
        if options.draw_dfg:
            name += "/DFG"
        print(f"Saved {name} visualization: {self.output_path('cfg')}")

    def graph(self) -> pgv.AGraph:
        options = self.options
        cfg = self.cfg
        duc_edges = self.duc_edges
        if cfg is None:
            raise ValueError("CFG required to draw CFG")
        if options.draw_dfg and duc_edges is None:
            raise ValueError("Def-use information required to draw CFG")

        # CFG graph (optionally overlay DFG when requested)
        G_cfg = pgv.AGraph(strict=False, directed=True)
        G_cfg.graph_attr.update(
            ranksep="0.2",
            nodesep="0.45",
            rankdir="TB",
            splines=True,
            margin="0.05",
            bgcolor="white",
        )
        G_cfg.node_attr.update(style="filled")
        for node_id, node in cfg.nodes.items():
            col, shape = get_node_display(node)
            add_cfg_node(G_cfg, node_id, node, col, shape)
        for node_id, node in cfg.nodes.items():
            for succ in node.successors:
                lab = node.edge_labels.get(succ, "")
                G_cfg.add_edge(node_id, succ, color="black", label=lab)
        if options.draw_dfg and duc_edges is not None:
            for (src, dst), names in duc_edges.items():
                dfg_label = ", ".join(sorted(names))
                add_dfg_edge(G_cfg, src, dst, dfg_label)
        return G_cfg
