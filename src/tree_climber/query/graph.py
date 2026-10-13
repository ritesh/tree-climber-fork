from collections import deque
from functools import cached_property
from typing import (
    Collection,
    Dict,
    Iterable,
    List,
    Optional,
    Pattern,
    Set,
    Tuple,
    Union,
)

import networkx as nx

from tree_climber.cfg.builder import CFGBuilder
from tree_climber.cfg.cfg_types import CFGNode, NodeType
from tree_climber.cfg.visitor import CFG
from tree_climber.dataflow.analyses.def_use import DefUseResult, DefUseSolver
from tree_climber.dataflow.analyses.reaching_definitions import (
    ReachingDefinitionsProblem,
)
from tree_climber.dataflow.analyses.use_def import UseDefResult, UseDefSolver
from tree_climber.dataflow.solver import RoundRobinSolver
from tree_climber.query.edges import (
    CALL_KINDS,
    DEF_USE,
    FLOW,
    DataFlowEdge,
    interprocedural_edges,
)
from tree_climber.query.facts import FactGraph, Route
from tree_climber.query.path import Path, PathStep

NodeRef = Union[int, CFGNode]
Kinds = Optional[Collection[str]]
ExtraEdges = Optional[Iterable[DataFlowEdge]]


class CodeGraph:
    """Queries over a CFG and its data flow, built once.

    Nodes come back as `CFGNode`s sorted by id; anywhere a node is taken, its id
    works too. Flow queries follow every edge kind unless told otherwise, so
    they cross calls and returns; pass `exclude=CALL_KINDS` to stay inside one
    function. Data-flow queries take `extra_edges`, `DataFlowEdge`s from other
    analyses, for that call only.
    """

    def __init__(self, cfg: CFG):
        self.cfg = cfg
        self._last_extras: Optional[Tuple[Tuple[DataFlowEdge, ...], FactGraph]] = None
        self._function_entry: Dict[int, int] = {}
        for entry in cfg.entry_node_ids:
            for node_id in self._within_function(entry):
                self._function_entry.setdefault(node_id, entry)

    @classmethod
    def from_cfg(cls, cfg: CFG) -> "CodeGraph":
        return cls(cfg)

    @classmethod
    def from_source(cls, language: str, source: str) -> "CodeGraph":
        builder = CFGBuilder(language)
        builder.setup_parser()
        return cls(builder.build_cfg(source))

    def _within_function(self, entry: int) -> Set[int]:
        seen: Set[int] = set()
        stack = [entry]
        while stack:
            node_id = stack.pop()
            if node_id in seen:
                continue
            seen.add(node_id)
            node = self.cfg.nodes[node_id]
            stack.extend(
                successor
                for successor in node.successors
                if node.edge_labels.get(successor) not in CALL_KINDS
            )
        return seen

    def _id(self, ref: NodeRef) -> int:
        node_id = ref.id if isinstance(ref, CFGNode) else ref
        if node_id not in self.cfg.nodes:
            raise KeyError(f"No node {node_id}")
        return node_id

    def _sorted(self, ids: Iterable[int]) -> List[CFGNode]:
        return [self.cfg.nodes[node_id] for node_id in sorted(ids)]

    @property
    def nodes(self) -> List[CFGNode]:
        return self._sorted(self.cfg.nodes)

    def node(self, ref: NodeRef) -> CFGNode:
        return self.cfg.nodes[self._id(ref)]

    def by_text(
        self, text: Union[str, Pattern[str]], exact: bool = False
    ) -> List[CFGNode]:
        """Nodes whose source text contains `text`, equals it (`exact`), or
        matches the compiled regex."""
        if isinstance(text, str):
            if exact:
                return self._filter(lambda node: node.source_text == text)
            return self._filter(lambda node: text in node.source_text)
        return self._filter(lambda node: text.search(node.source_text) is not None)

    def by_type(self, *types: Union[NodeType, str]) -> List[CFGNode]:
        names = {t.name if isinstance(t, NodeType) else t.upper() for t in types}
        return self._filter(lambda node: node.node_type.name in names)

    def calling(self, *names: str) -> List[CFGNode]:
        """Nodes that call any of the names, matched against the callee name
        (`system`) and the whole callee expression (`os.system`)."""
        wanted = set(names)

        def calls(node: CFGNode) -> bool:
            called = set(node.metadata.function_calls)
            called.update(site.callee_text for site in node.metadata.call_sites)
            return not wanted.isdisjoint(called)

        return self._filter(calls)

    def defining(self, variable: str) -> List[CFGNode]:
        return self._filter(lambda node: variable in node.metadata.variable_definitions)

    def using(self, variable: str) -> List[CFGNode]:
        return self._filter(lambda node: variable in node.metadata.variable_uses)

    def _filter(self, keep) -> List[CFGNode]:
        return [node for node in self.nodes if keep(node)]

    def functions(self) -> List[CFGNode]:
        """The ENTRY node of every function (and of the Python module)."""
        return self._sorted(self.cfg.entry_node_ids)

    def function_of(self, ref: NodeRef) -> Optional[CFGNode]:
        """The ENTRY node of the function containing the node, or None for a
        node no entry reaches."""
        entry = self._function_entry.get(self._id(ref))
        return None if entry is None else self.cfg.nodes[entry]

    def function_nodes(self, function: Union[str, NodeRef]) -> List[CFGNode]:
        """The nodes of a function given by its ENTRY node or by name (all
        functions of that name)."""
        if isinstance(function, str):
            entries = {
                entry
                for entry in self.cfg.entry_node_ids
                if self.cfg.nodes[entry].source_text == function
            }
        else:
            entry = self._id(function)
            if entry not in self.cfg.entry_node_ids:
                raise ValueError(f"Node {entry} is not an ENTRY node")
            entries = {entry}
        return self._sorted(
            node_id
            for node_id, entry in self._function_entry.items()
            if entry in entries
        )

    @staticmethod
    def _edge_kind(node: CFGNode, successor: int) -> str:
        return node.edge_labels.get(successor) or FLOW

    @staticmethod
    def _allowed(kind: str, labels: Kinds, exclude: Kinds) -> bool:
        return (labels is None or kind in labels) and (
            exclude is None or kind not in exclude
        )

    def edge_kind(self, source: NodeRef, target: NodeRef) -> Optional[str]:
        """The kind of the edge between two nodes, or None if there is none."""
        node = self.node(source)
        target_id = self._id(target)
        return (
            self._edge_kind(node, target_id) if target_id in node.successors else None
        )

    def successors(
        self, ref: NodeRef, labels: Kinds = None, exclude: Kinds = None
    ) -> List[CFGNode]:
        node = self.node(ref)
        return self._sorted(
            successor
            for successor in node.successors
            if self._allowed(self._edge_kind(node, successor), labels, exclude)
        )

    def predecessors(
        self, ref: NodeRef, labels: Kinds = None, exclude: Kinds = None
    ) -> List[CFGNode]:
        node = self.node(ref)
        return self._sorted(
            predecessor
            for predecessor in node.predecessors
            if self._allowed(
                self._edge_kind(self.cfg.nodes[predecessor], node.id), labels, exclude
            )
        )

    def _steps(
        self, node_id: int, labels: Kinds, exclude: Kinds, backward: bool = False
    ) -> List[int]:
        if backward:
            return [node.id for node in self.predecessors(node_id, labels, exclude)]
        return [node.id for node in self.successors(node_id, labels, exclude)]

    def reachable(
        self,
        ref: NodeRef,
        labels: Kinds = None,
        exclude: Kinds = None,
        backward: bool = False,
    ) -> List[CFGNode]:
        """The node and every node reachable from it (or, with `backward`, every
        node that can reach it)."""
        start = self._id(ref)
        seen = {start}
        stack = [start]
        while stack:
            for node_id in self._steps(stack.pop(), labels, exclude, backward):
                if node_id not in seen:
                    seen.add(node_id)
                    stack.append(node_id)
        return self._sorted(seen)

    def _reaching_without(
        self, goal: int, labels: Kinds, exclude: Kinds, blocked: Set[int]
    ) -> Set[int]:
        seen = {goal}
        stack = [goal]
        while stack:
            for node_id in self._steps(stack.pop(), labels, exclude, backward=True):
                if node_id not in seen and node_id not in blocked:
                    seen.add(node_id)
                    stack.append(node_id)
        return seen

    def can_reach(
        self,
        source: NodeRef,
        target: NodeRef,
        labels: Kinds = None,
        exclude: Kinds = None,
    ) -> bool:
        target_id = self._id(target)
        return any(
            node.id == target_id for node in self.reachable(source, labels, exclude)
        )

    def _control_path(self, node_ids: List[int]) -> Path:
        steps = [PathStep.of(self.cfg.nodes[node_ids[0]])]
        for previous, node_id in zip(node_ids, node_ids[1:]):
            kind = self._edge_kind(self.cfg.nodes[previous], node_id)
            steps.append(PathStep.of(self.cfg.nodes[node_id], kind))
        return Path(tuple(steps))

    def shortest_path(
        self,
        source: NodeRef,
        target: NodeRef,
        labels: Kinds = None,
        exclude: Kinds = None,
        avoid: Iterable[NodeRef] = (),
    ) -> Optional[Path]:
        """A path with the fewest edges, or None. `avoid` nodes may not appear
        between the ends. Ties go to the lower node ids."""
        start, goal = self._id(source), self._id(target)
        blocked = {self._id(ref) for ref in avoid} - {start, goal}
        parent: Dict[int, Optional[int]] = {start: None}
        queue = deque([start])
        while queue and goal not in parent:
            node_id = queue.popleft()
            for next_id in self._steps(node_id, labels, exclude):
                if next_id not in parent and next_id not in blocked:
                    parent[next_id] = node_id
                    queue.append(next_id)
        if goal not in parent:
            return None
        order: List[int] = []
        current: Optional[int] = goal
        while current is not None:
            order.append(current)
            current = parent[current]
        order.reverse()
        return self._control_path(order)

    def paths(
        self,
        source: NodeRef,
        target: NodeRef,
        max_paths: int = 100,
        max_length: Optional[int] = None,
        labels: Kinds = None,
        exclude: Kinds = None,
        avoid: Iterable[NodeRef] = (),
    ) -> List[Path]:
        """Paths from source to target that visit no node twice, found depth
        first with successors in id order. At most `max_paths` are returned, none
        longer than `max_length` edges. When source and target are the same node
        the only path is that node."""
        self._check_bounds(max_paths, max_length)
        start, goal = self._id(source), self._id(target)
        if start == goal:
            return [self._control_path([start])]
        blocked = {self._id(ref) for ref in avoid} - {start, goal}
        useful = self._reaching_without(goal, labels, exclude, blocked)
        found: List[Path] = []
        route = [start]
        stack = [iter(self._steps(start, labels, exclude))]
        while stack and len(found) < max_paths:
            next_id = next(stack[-1], None)
            if next_id is None:
                stack.pop()
                route.pop()
                continue
            if next_id in route or next_id not in useful:
                continue
            if max_length is not None and len(route) > max_length:
                continue
            if next_id == goal:
                found.append(self._control_path(route + [goal]))
                continue
            route.append(next_id)
            stack.append(iter(self._steps(next_id, labels, exclude)))
        return found

    @staticmethod
    def _check_bounds(max_paths: int, max_length: Optional[int]):
        if max_paths < 1:
            raise ValueError("max_paths must be at least 1")
        if max_length is not None and max_length < 0:
            raise ValueError("max_length must not be negative")

    @cached_property
    def _reaching(self):
        return RoundRobinSolver().solve(self.cfg, ReachingDefinitionsProblem())

    @cached_property
    def _def_use(self) -> DefUseResult:
        return DefUseSolver().solve(self.cfg, self._reaching)

    @cached_property
    def _use_def(self) -> UseDefResult:
        return UseDefSolver().solve(self.cfg, self._reaching)

    def _fact_graph(self, extra_edges: ExtraEdges) -> FactGraph:
        extras = tuple(extra_edges or ())
        if not extras:
            return self._base_facts
        if self._last_extras is None or self._last_extras[0] != extras:
            self._last_extras = (extras, self._build_facts(extras))
        return self._last_extras[1]

    @cached_property
    def _base_facts(self) -> FactGraph:
        return self._build_facts(())

    def _build_facts(self, extras: Tuple[DataFlowEdge, ...]) -> FactGraph:
        chains = [
            (chain.variable_name, chain.definition, chain.uses)
            for variable_chains in self._def_use.chains.values()
            for chain in variable_chains
        ]
        return FactGraph(self.nodes, chains, extras)

    def def_use(
        self, variable: str, extra_edges: ExtraEdges = None
    ) -> Dict[int, List[int]]:
        """{definition node: nodes using that definition} for a variable. Only
        definitions that are used appear. Extra edges are listed under their
        source variable."""
        result: Dict[int, Set[int]] = {}
        for chain in self._def_use.chains.get(variable, []):
            result.setdefault(chain.definition, set()).update(chain.uses)
        for edge in extra_edges or ():
            if edge.source_variable == variable:
                result.setdefault(self._id(edge.source), set()).add(
                    self._id(edge.target)
                )
        return {node_id: sorted(uses) for node_id, uses in sorted(result.items())}

    def use_def(
        self, variable: str, extra_edges: ExtraEdges = None
    ) -> Dict[int, List[int]]:
        """{use node: definitions reaching it} for a variable; a use with no
        reaching definition maps to []. Extra edges are listed under their
        target variable."""
        result: Dict[int, Set[int]] = {}
        for chain in self._use_def.chains.get(variable, []):
            result.setdefault(chain.use, set()).update(chain.definitions)
        for edge in extra_edges or ():
            if edge.target_variable == variable:
                result.setdefault(self._id(edge.target), set()).add(
                    self._id(edge.source)
                )
        return {node_id: sorted(defs) for node_id, defs in sorted(result.items())}

    @cached_property
    def _interprocedural(self) -> List[DataFlowEdge]:
        return interprocedural_edges(self.cfg)

    def interprocedural_edges(self) -> List[DataFlowEdge]:
        """Argument, return and free-variable flows between functions, to pass as
        `extra_edges` so the data-flow queries cross calls."""
        return list(self._interprocedural)

    def data_flow_edges(self, extra_edges: ExtraEdges = None) -> List[DataFlowEdge]:
        """Every def-use edge, then the extra edges, without repeats."""
        edges = {
            DataFlowEdge(
                chain.definition, chain.variable_name, use, chain.variable_name, DEF_USE
            )
            for variable_chains in self._def_use.chains.values()
            for chain in variable_chains
            for use in chain.uses
        }
        ordered = sorted(
            edges,
            key=lambda e: (e.source, e.target, e.source_variable),
        )
        for edge in extra_edges or ():
            if edge not in edges:
                edges.add(edge)
                ordered.append(edge)
        return ordered

    def forward_slice(
        self,
        ref: NodeRef,
        variable: Optional[str] = None,
        extra_edges: ExtraEdges = None,
    ) -> List[CFGNode]:
        """The node and every node whose value depends on it: what it defines
        flows to uses, and a node's uses flow to what it defines. With
        `variable`, only that variable's flow from the node is followed."""
        graph = self._fact_graph(extra_edges)
        node_id = self._id(ref)
        reached = graph.reach(graph.seeds(node_id, variable), graph.forward)
        return self._sorted({fact.node for fact in reached} | {node_id})

    def backward_slice(
        self,
        ref: NodeRef,
        variable: Optional[str] = None,
        extra_edges: ExtraEdges = None,
    ) -> List[CFGNode]:
        """The node and every node it depends on."""
        graph = self._fact_graph(extra_edges)
        node_id = self._id(ref)
        reached = graph.reach(graph.seeds(node_id, variable), graph.backward)
        return self._sorted({fact.node for fact in reached} | {node_id})

    def _route_path(self, start: int, route: Route) -> Path:
        steps = [PathStep.of(self.cfg.nodes[start])]
        for _, move in route:
            if move.kind is not None:
                node = self.cfg.nodes[move.target.node]
                steps.append(PathStep.of(node, move.kind, move.variable))
        return Path(tuple(steps))

    def data_flow_path(
        self,
        source: NodeRef,
        target: NodeRef,
        variable: Optional[str] = None,
        avoid: Iterable[NodeRef] = (),
        extra_edges: ExtraEdges = None,
    ) -> Optional[Path]:
        """A data-flow path from source to target with the fewest steps between
        nodes, or None. Each step's edge is `def_use` (or the kind of an extra
        edge) and carries the variable. `avoid` nodes may not appear between
        the ends, and the path does not come back to the source."""
        graph = self._fact_graph(extra_edges)
        start, goal = self._id(source), self._id(target)
        seeds = graph.seeds(start, variable)
        if start == goal:
            return self._route_path(start, [])
        blocked = {self._id(ref) for ref in avoid} - {start, goal}
        route = graph.shortest(seeds, goal, blocked)
        return None if route is None else self._route_path(start, route)

    def data_flow_paths(
        self,
        source: NodeRef,
        target: NodeRef,
        max_paths: int = 100,
        max_length: Optional[int] = None,
        variable: Optional[str] = None,
        avoid: Iterable[NodeRef] = (),
        extra_edges: ExtraEdges = None,
    ) -> List[Path]:
        """Data-flow paths from source to target that visit no node twice, depth
        first, at most `max_paths`, none longer than `max_length` steps."""
        self._check_bounds(max_paths, max_length)
        graph = self._fact_graph(extra_edges)
        start, goal = self._id(source), self._id(target)
        seeds = graph.seeds(start, variable)
        if start == goal:
            return [self._route_path(start, [])]
        blocked = {self._id(ref) for ref in avoid} - {start, goal}
        useful = graph.reaching_nodes(goal, blocked)
        found: List[Path] = []
        for seed in seeds:
            for route in graph.routes(seed, goal, useful, max_length, blocked):
                path = self._route_path(start, route)
                if path not in found:
                    found.append(path)
                    if len(found) == max_paths:
                        return found
        return found

    def to_networkx(self, data_flow: bool = False, extra_edges: ExtraEdges = None):
        """A `networkx.MultiDiGraph` of the CFG: nodes keyed by id, control edges
        with `kind` and `layer="control"`. With `data_flow`, def-use edges and
        extra edges are added with `layer="data"`, `kind`, `source_variable`
        and `target_variable`."""
        graph = nx.MultiDiGraph()
        for node in self.nodes:
            function = self.function_of(node)
            graph.add_node(
                node.id,
                text=node.source_text,
                node_type=node.node_type.name,
                function=function.source_text if function else None,
                calls=list(node.metadata.function_calls),
                definitions=list(node.metadata.variable_definitions),
                uses=list(node.metadata.variable_uses),
            )
        for node in self.nodes:
            for successor in sorted(node.successors):
                graph.add_edge(
                    node.id,
                    successor,
                    kind=self._edge_kind(node, successor),
                    layer="control",
                )
        if data_flow:
            for edge in self.data_flow_edges(extra_edges):
                graph.add_edge(
                    self._id(edge.source),
                    self._id(edge.target),
                    kind=edge.kind,
                    layer="data",
                    source_variable=edge.source_variable,
                    target_variable=edge.target_variable,
                )
        return graph
