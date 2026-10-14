import pygraphviz as pgv
from tree_sitter import Node

from tree_climber.cfg.cfg_types import CFGNode
from tree_climber.cfg.visitor import CFG
from tree_climber.cli.visualizers.base_visualizer import (
    get_node_display,
    get_node_label,
    truncate_ast_label,
)
from tree_climber.query import FLOW, Path

from .constants import PATH_EDGE_COLOR, PATH_NODE_COLOR


def add_dfg_edge(G: pgv.AGraph, pred: int, succ: int, dfg_label: str):
    G.add_edge(
        pred,
        succ,
        color="red",
        style="dashed",
        fontcolor="red",
        label=dfg_label,
    )


def add_cfg_node(G: pgv.AGraph, node_id: int, node: CFGNode, color: str, shape: str):
    G.add_node(node_id, label=get_node_label(node), fillcolor=color, shape=shape)


def ast_label(ts_node: Node) -> str:
    node_type = ts_node.type
    text = ts_node.text
    try:
        text_str = text.decode("utf-8").strip().replace("\n", " ")
    except Exception:
        text_str = ""
    return truncate_ast_label(f"{node_type}: {text_str}" if text_str else node_type)


def highlight_path(G: pgv.AGraph, cfg: CFG, path: Path):
    for node_id in path.nodes:
        node = cfg.nodes[node_id]
        add_cfg_node(G, node_id, node, *get_node_display(node))
        G.add_node(
            node_id, fillcolor=PATH_NODE_COLOR, color=PATH_EDGE_COLOR, penwidth="3"
        )
    for number, (previous, step) in enumerate(zip(path.steps, path.steps[1:]), 1):
        label = " ".join(part for part in (step.edge or FLOW, step.variable) if part)
        G.add_edge(
            previous.node,
            step.node,
            color=PATH_EDGE_COLOR,
            fontcolor=PATH_EDGE_COLOR,
            penwidth="3",
            label=f"{number}: {label}",
        )
