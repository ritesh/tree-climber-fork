from dataclasses import dataclass
from typing import Any, Dict, Tuple

FLOW = "flow"
TRUE = "true"
FALSE = "false"
EXCEPTION = "exception"
FUNCTION_CALL = "function_call"
FUNCTION_RETURN = "function_return"
DEF_USE = "def_use"

CALL_KINDS: Tuple[str, str] = (FUNCTION_CALL, FUNCTION_RETURN)


@dataclass(frozen=True)
class DataFlowEdge:
    """A value flowing from `source_variable` at node `source` to
    `target_variable` at node `target`.

    Def-use chains are edges of kind `def_use`. Analyses that connect more than
    one chain, such as an argument to a callee's parameter, describe their flows
    as edges of another kind and pass them to the data-flow queries.
    """

    source: int
    source_variable: str
    target: int
    target_variable: str
    kind: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "source_variable": self.source_variable,
            "target": self.target,
            "target_variable": self.target_variable,
            "kind": self.kind,
        }
