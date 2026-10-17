from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class AnalysisOptions:
    """Configuration options for source code analysis."""

    draw_ast: bool
    draw_cfg: bool
    draw_dfg: bool
    draw_cpg: bool
    language: str
    layout: str
    output_dir: Path
    show: bool
    verbose: bool
    quiet: bool
    timing: bool
    image_format: str = "png"


@dataclass
class TaintOptions:
    """Configuration options for the taint command."""

    language: str
    rules: str
    as_json: bool
    finding: Optional[int]
    draw_cfg: bool
    draw_dfg: bool
    output_dir: Path
    show: bool
    image_format: str = "png"


@dataclass
class QueryOptions:
    """Configuration options for the query command."""

    language: str
    calls: List[str]
    slice_from: Optional[int]
    backward: bool
    variable: Optional[str]
    across_calls: bool
    as_json: bool
