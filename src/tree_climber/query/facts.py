from collections import deque
from typing import (
    Collection,
    Dict,
    Iterable,
    Iterator,
    List,
    NamedTuple,
    Optional,
    Set,
    Tuple,
)

from tree_climber.cfg.cfg_types import CFGNode
from tree_climber.query.edges import DEF_USE, DataFlowEdge


class Fact(NamedTuple):
    node: int
    variable: str
    is_definition: bool


class Move(NamedTuple):
    target: Fact
    kind: Optional[str]
    variable: Optional[str]


Moves = Dict[Fact, List[Move]]
Route = List[Tuple[Fact, Move]]


class FactGraph:
    """The values of a program as facts and the moves between them.

    A definition fact moves to the use facts its definition reaches (`def_use`
    or the kind of an extra edge). A use fact moves to every definition fact of
    its node, since a statement's definitions depend on all of its uses. Moves
    inside a node have no kind; a move between nodes always has one.
    """

    def __init__(
        self,
        nodes: Iterable[CFGNode],
        chains: Iterable[Tuple[str, int, Iterable[int]]],
        extra_edges: Iterable[DataFlowEdge] = (),
    ):
        self.forward: Moves = {}
        self.backward: Moves = {}
        self.at_node: Dict[int, Set[Fact]] = {}
        definitions: Dict[int, List[Fact]] = {}
        for node in nodes:
            facts = self.at_node.setdefault(node.id, set())
            definitions[node.id] = [
                Fact(node.id, variable, True)
                for variable in dict.fromkeys(node.metadata.variable_definitions)
            ]
            facts.update(definitions[node.id])
            facts.update(
                Fact(node.id, variable, False)
                for variable in dict.fromkeys(node.metadata.variable_uses)
            )
        for fact in sorted(self.all_facts()):
            if not fact.is_definition:
                for definition in definitions[fact.node]:
                    self._add(fact, Move(definition, None, None))
        for variable, definition, uses in chains:
            for use in uses:
                self._add(
                    Fact(definition, variable, True),
                    Move(Fact(use, variable, False), DEF_USE, variable),
                )
        self._add_extra_edges(list(extra_edges), definitions)

    def all_facts(self) -> Set[Fact]:
        return {fact for facts in self.at_node.values() for fact in facts}

    def _add(self, source: Fact, move: Move):
        self.forward.setdefault(source, []).append(move)
        self.backward.setdefault(move.target, []).append(
            Move(source, move.kind, move.variable)
        )

    def _add_extra_edges(
        self, edges: List[DataFlowEdge], definitions: Dict[int, List[Fact]]
    ):
        arrivals: List[List[Fact]] = []
        for edge in edges:
            if edge.source not in self.at_node:
                raise KeyError(f"No node {edge.source}")
            if edge.target not in self.at_node:
                raise KeyError(f"No node {edge.target}")
            arrivals.append(self._arrival_facts(edge, definitions))
        for edge, arrival in zip(edges, arrivals):
            at_source = self.at_node[edge.source]
            leaving = [
                fact for fact in at_source if fact.variable == edge.source_variable
            ]
            for source in sorted(leaving or at_source):
                for target in arrival:
                    self._add(source, Move(target, edge.kind, edge.target_variable))

    def _arrival_facts(
        self, edge: DataFlowEdge, definitions: Dict[int, List[Fact]]
    ) -> List[Fact]:
        defined = Fact(edge.target, edge.target_variable, True)
        used = Fact(edge.target, edge.target_variable, False)
        arrival = [
            fact for fact in (defined, used) if fact in self.at_node[edge.target]
        ]
        if not arrival:
            arrival = [used]
            self.at_node[edge.target].add(used)
            for definition in definitions[edge.target]:
                self._add(used, Move(definition, None, None))
        return arrival

    def seeds(self, node: int, variable: Optional[str] = None) -> List[Fact]:
        facts = sorted(self.at_node[node])
        if variable is None:
            return facts
        seeds = [fact for fact in facts if fact.variable == variable]
        if not seeds:
            raise ValueError(f"Node {node} neither defines nor uses {variable!r}")
        return seeds

    def reach(self, seeds: Iterable[Fact], moves: Moves) -> Set[Fact]:
        seen: Set[Fact] = set(seeds)
        stack = list(seen)
        while stack:
            for move in moves.get(stack.pop(), ()):
                if move.target not in seen:
                    seen.add(move.target)
                    stack.append(move.target)
        return seen

    def shortest(
        self, seeds: Iterable[Fact], target: int, avoid: Collection[int] = ()
    ) -> Optional[Route]:
        """The route with the fewest moves between nodes.

        Moves inside a node are free, so this is a 0-1 breadth-first search.
        """
        seeds = list(seeds)
        if not seeds:
            return None
        source = seeds[0].node
        cost: Dict[Fact, int] = {seed: 0 for seed in seeds}
        parent: Dict[Fact, Tuple[Fact, Move]] = {}
        queue = deque(seeds)
        done: Set[Fact] = set()
        while queue:
            fact = queue.popleft()
            if fact in done:
                continue
            done.add(fact)
            if fact.node == target:
                route: Route = []
                while fact in parent:
                    origin, move = parent[fact]
                    route.append((origin, move))
                    fact = origin
                route.reverse()
                return route
            if fact.node in avoid and fact.node != source:
                continue
            for move in self.forward.get(fact, ()):
                step = 0 if move.kind is None else 1
                new_cost = cost[fact] + step
                if move.target not in cost or new_cost < cost[move.target]:
                    cost[move.target] = new_cost
                    parent[move.target] = (fact, move)
                    if step:
                        queue.append(move.target)
                    else:
                        queue.appendleft(move.target)
        return None

    def routes(
        self,
        seed: Fact,
        target: int,
        max_length: Optional[int] = None,
        avoid: Collection[int] = (),
    ) -> Iterator[Route]:
        """Routes from a seed to the target that visit no node twice, depth first."""
        useful = {fact.node for fact in self.reach(self.at_node[target], self.backward)}
        on_path = {seed.node}
        route: Route = []
        hops = 0
        stack = [iter(self.forward.get(seed, ()))]
        while stack:
            move = next(stack[-1], None)
            if move is None:
                stack.pop()
                if route:
                    _, taken = route.pop()
                    if taken.kind is not None:
                        on_path.discard(taken.target.node)
                        hops -= 1
                continue
            node = move.target.node
            if move.kind is not None:
                if node in on_path or node not in useful:
                    continue
                if node in avoid and node != target:
                    continue
                if max_length is not None and hops + 1 > max_length:
                    continue
            origin = seed if not route else route[-1][1].target
            if move.kind is not None and node == target:
                yield route + [(origin, move)]
                continue
            route.append((origin, move))
            if move.kind is not None:
                on_path.add(node)
                hops += 1
            stack.append(iter(self.forward.get(move.target, ())))
