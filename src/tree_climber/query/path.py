from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple

from tree_climber.cfg.cfg_types import CFGNode, NodeType
from tree_climber.query.edges import FLOW

MAX_TEXT_WIDTH = 60


@dataclass(frozen=True)
class PathStep:
    """One node on a path.

    `edge` is the kind of the edge from the previous step (None for the first
    step) and `variable` the variable a data-flow edge carries.
    """

    node: int
    node_type: str
    text: str
    edge: Optional[str] = None
    variable: Optional[str] = None

    @classmethod
    def of(
        cls, node: CFGNode, edge: Optional[str] = None, variable: Optional[str] = None
    ) -> "PathStep":
        text = node.source_text.splitlines()[0] if node.source_text else ""
        return cls(node.id, node.node_type.name, text, edge, variable)

    def label(self) -> str:
        text = self.text
        if self.node_type in (NodeType.ENTRY.name, NodeType.EXIT.name):
            text = f"{self.node_type} {text}"
        if len(text) > MAX_TEXT_WIDTH:
            text = text[: MAX_TEXT_WIDTH - 3] + "..."
        return f"[{self.node}] {text}"

    def arrow(self) -> str:
        kind = self.edge or FLOW
        if kind == FLOW and self.variable is None:
            return "-->"
        variable = f" {self.variable}" if self.variable else ""
        return f"--{kind}{variable}-->"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node": self.node,
            "node_type": self.node_type,
            "text": self.text,
            "edge": self.edge,
            "variable": self.variable,
        }


@dataclass(frozen=True)
class Path:
    """A walk through the graph: nodes in order, each with the edge that led to it."""

    steps: Tuple[PathStep, ...]

    @property
    def nodes(self) -> List[int]:
        return [step.node for step in self.steps]

    @property
    def edges(self) -> List[str]:
        return [step.edge or FLOW for step in self.steps[1:]]

    @property
    def texts(self) -> List[str]:
        return [step.text for step in self.steps]

    @property
    def source(self) -> PathStep:
        return self.steps[0]

    @property
    def target(self) -> PathStep:
        return self.steps[-1]

    def __len__(self) -> int:
        return len(self.steps)

    def __iter__(self) -> Iterator[PathStep]:
        return iter(self.steps)

    def __str__(self) -> str:
        lines = [self.steps[0].label()]
        lines.extend(f"  {step.arrow()} {step.label()}" for step in self.steps[1:])
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {"steps": [step.to_dict() for step in self.steps]}
