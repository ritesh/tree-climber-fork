"""
CLI command implementations for Tree Climber.

This module contains the core logic for analyzing source code and generating
visualizations of AST, CFG, DFG, and CPG.
"""

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer
from tree_sitter import Tree

from tree_climber.ast_utils import parse_source_to_ast
from tree_climber.cfg.builder import CFGBuilder
from tree_climber.cfg.visitor import CFG
from tree_climber.dataflow.analyses.def_use import DefUseResult, DefUseSolver
from tree_climber.dataflow.analyses.reaching_definitions import (
    ReachingDefinitionsProblem,
)
from tree_climber.dataflow.solver import RoundRobinSolver
from tree_climber.query import CodeGraph
from tree_climber.reporting import (
    load_rules,
    node_line,
    node_to_dict,
    slice_from_line,
)
from tree_climber.taint import Finding, analyze

from .options import AnalysisOptions, QueryOptions, TaintOptions
from .source import ClipboardSource, CodeSource
from .visualizers import (
    ASTVisualizer,
    BiGraphVisualizer,
    CFGVisualizer,
    DFGVisualizer,
    SubtreeVisualizer,
)
from .visualizers.utils import draw_graph, highlight_path

SUPPORTED_LAYOUTS = {"bigraph": BiGraphVisualizer, "subtree": SubtreeVisualizer}


class AnalysisTimer:
    """Context manager for timing analysis operations."""

    def __init__(
        self, operation_name: str, show_timing: bool = False, verbose: bool = False
    ):
        self.operation_name = operation_name
        self.show_timing = show_timing
        self.verbose = verbose
        self.start_time = 0.0

    def __enter__(self):
        if self.verbose:
            typer.echo(f"Starting {self.operation_name}...")
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = time.time() - self.start_time
        if self.show_timing:
            typer.echo(f"✓ {self.operation_name} completed in {elapsed:.3f}s")
        elif self.verbose:
            typer.echo(f"✓ {self.operation_name} completed")


def analyze_source_code(source: CodeSource, options: AnalysisOptions) -> None:
    """
    Analyze source code and generate requested visualizations.

    Args:
        source: Code source (file or clipboard)
        options: Configuration options for the analysis
    """
    if not options.quiet:
        if isinstance(source, ClipboardSource):
            typer.echo("Analyzing text from clipboard")
        else:
            typer.echo(f"Analyzing: {source.get_display_name()}")

    # Parse source code to AST
    with AnalysisTimer("AST parsing", options.timing, options.verbose):
        ast_root = _parse_source_string(source.get_content(), options.language)

    # Build CFG if needed
    cfg = None
    if options.draw_cfg or options.draw_dfg or options.draw_cpg:
        with AnalysisTimer("CFG construction", options.timing, options.verbose):
            cfg = _build_cfg(ast_root, options.language)

    # Perform dataflow analysis if needed for DFG
    def_use_result = None
    if options.draw_dfg or options.draw_cpg:
        if cfg is None:
            raise ValueError("CFG is required for dataflow analysis")
        with AnalysisTimer("Dataflow analysis", options.timing, options.verbose):
            def_use_result = _analyze_dataflow(cfg)

    visualizer_options = (source, options, ast_root, cfg, def_use_result)
    saved_paths = []
    if options.draw_ast:
        with AnalysisTimer("AST visualization", options.timing, options.verbose):
            visualizer = ASTVisualizer(*visualizer_options)
            visualizer.visualize()
            saved_paths.append(visualizer.output_path("ast"))
    if options.draw_cfg:
        with AnalysisTimer("CFG visualization", options.timing, options.verbose):
            visualizer = CFGVisualizer(*visualizer_options)
            visualizer.visualize()
            saved_paths.append(visualizer.output_path("cfg"))
    if options.draw_dfg:
        with AnalysisTimer("DFG visualization", options.timing, options.verbose):
            visualizer = DFGVisualizer(*visualizer_options)
            visualizer.visualize()
            saved_paths.append(visualizer.output_path("dfg"))
    if options.draw_cpg:
        with AnalysisTimer("CPG visualization", options.timing, options.verbose):
            visualizer = SUPPORTED_LAYOUTS[options.layout](*visualizer_options)
            visualizer.visualize()
            saved_paths.append(visualizer.output_path("cpg"))

    if options.show:
        for path in saved_paths:
            if typer.launch(str(path)) != 0:
                typer.echo(f"Warning: could not open {path}", err=True)

    if not options.quiet:
        typer.echo("✨ Analysis complete!")


def _parse_source_string(source_code: str, language: str) -> Tree:
    """Parse source code string to AST."""
    return parse_source_to_ast(source_code, language)


def _build_cfg(ast_root: Tree, language: str) -> CFG:
    """Build Control Flow Graph from AST."""
    builder = CFGBuilder(language)
    builder.setup_parser()
    return builder.build_cfg(tree=ast_root)


def _analyze_dataflow(cfg: CFG) -> DefUseResult:
    """Perform reaching definitions dataflow analysis."""
    problem = ReachingDefinitionsProblem()
    dataflow_solver = RoundRobinSolver()
    def_use_solver = DefUseSolver()
    return def_use_solver.solve(cfg, dataflow_solver.solve(cfg, problem))


def _where(cfg: CFG, node_id: int) -> str:
    line = node_line(cfg.nodes[node_id])
    return "" if line is None else f"line {line}"


def format_finding(number: int, finding: Finding, cfg: CFG) -> str:
    lines = [
        f"{number}. {finding.rule}: argument {finding.argument} of "
        f"{finding.sink_call} ({_where(cfg, finding.sink)})"
    ]
    for index, step in enumerate(finding.path):
        arrow = f"  {step.arrow()} " if index else ""
        lines.append(f"   {_where(cfg, step.node):<9} {arrow}{step.label()}")
    return "\n".join(lines)


def _count(number: int, noun: str) -> str:
    if number == 0:
        return f"No {noun}s"
    return f"{number} {noun}" + ("" if number == 1 else "s")


def _finding_image(
    source: CodeSource, options: TaintOptions, number: int, kind: str
) -> Path:
    options.output_dir.mkdir(parents=True, exist_ok=True)
    name = f"{source.get_output_name()}_finding{number}_{kind}.{options.image_format}"
    return options.output_dir / name


def _draw_finding(
    source: CodeSource,
    options: TaintOptions,
    ast_root: Tree,
    cfg: CFG,
    def_use: Optional[DefUseResult],
    number: int,
    finding: Finding,
) -> List[Path]:
    drawing = AnalysisOptions(
        draw_ast=False,
        draw_cfg=options.draw_cfg,
        draw_dfg=False,
        draw_cpg=False,
        language=options.language,
        layout="subtree",
        output_dir=options.output_dir,
        show=False,
        verbose=False,
        quiet=True,
        timing=False,
    )
    graphs = []
    if options.draw_cfg:
        graphs.append(("cfg", CFGVisualizer(source, drawing, ast_root, cfg, None)))
    if options.draw_dfg:
        graphs.append(("dfg", DFGVisualizer(source, drawing, ast_root, cfg, def_use)))
    saved = []
    for kind, visualizer in graphs:
        graph = visualizer.graph()
        highlight_path(graph, cfg, finding.path)
        path = _finding_image(source, options, number, kind)
        draw_graph(graph, path)
        typer.echo(f"Saved finding {number} on the {kind.upper()}: {path}", err=True)
        saved.append(path)
    return saved


def run_taint(source: CodeSource, options: TaintOptions) -> None:
    """Report the findings of the rules on the source, and draw their paths."""
    rules = load_rules(options.rules, options.language)
    ast_root = _parse_source_string(source.get_content(), options.language)
    cfg = _build_cfg(ast_root, options.language)
    findings = analyze(cfg, rules, options.language)
    numbered = list(enumerate(findings, 1))
    if options.finding is not None:
        if not 1 <= options.finding <= len(findings):
            raise ValueError(
                f"No finding {options.finding}: "
                f"{_count(len(findings), 'finding').lower()} in "
                f"{source.get_display_name()}"
            )
        numbered = [numbered[options.finding - 1]]

    if options.as_json:
        report = {"findings": [finding.to_dict() for _, finding in numbered]}
        typer.echo(json.dumps(report, indent=2))
    else:
        typer.echo(f"Analyzing: {source.get_display_name()}")
        for number, finding in numbered:
            typer.echo(format_finding(number, finding, cfg))
        typer.echo(_count(len(findings), "finding"))

    saved: List[Path] = []
    if options.draw_cfg or options.draw_dfg:
        def_use = _analyze_dataflow(cfg) if options.draw_dfg else None
        for number, finding in numbered:
            saved.extend(
                _draw_finding(source, options, ast_root, cfg, def_use, number, finding)
            )
    if options.show:
        for path in saved:
            if typer.launch(str(path)) != 0:
                typer.echo(f"Warning: could not open {path}", err=True)


def format_node(node: Dict[str, Any]) -> str:
    where = "" if node["line"] is None else f"line {node['line']}"
    function = f"  (in {node['function']})" if node["function"] else ""
    label = node["text"]
    if node["node_type"] in ("ENTRY", "EXIT"):
        label = f"{node['node_type']} {label}"
    return f"   {where:<9} [{node['node']}] {label}{function}"


def run_query(source: CodeSource, options: QueryOptions) -> None:
    """Print the nodes that call the given names, or a slice from a line."""
    graph = CodeGraph.from_cfg(
        _build_cfg(
            _parse_source_string(source.get_content(), options.language),
            options.language,
        )
    )
    if options.calls:
        nodes = graph.calling(*options.calls)
        title = f"Calls to {', '.join(options.calls)}"
    else:
        assert options.slice_from is not None
        nodes = slice_from_line(
            graph,
            options.slice_from,
            backward=options.backward,
            variable=options.variable,
            across_calls=options.across_calls,
        )
        direction = "Backward" if options.backward else "Forward"
        title = f"{direction} slice from line {options.slice_from}"
        if options.variable:
            title += f" ({options.variable})"
    found = [node_to_dict(graph, node) for node in nodes]
    if options.as_json:
        typer.echo(json.dumps({"nodes": found}, indent=2))
        return
    typer.echo(f"{title}: {_count(len(found), 'node').lower()}")
    for node in found:
        typer.echo(format_node(node))
