"""Taint propagation over a CFG.

Each source occurrence is followed on its own, so every finding has one source.
Inside a node, call results are worked out innermost first: a source call is
tainted, a sanitizer is clean, a call to a function defined in the file is
tainted when one of its returns is, and any other call passes on the taint of
its arguments and receiver. Between nodes, taint follows def-use chains (so a
reassignment kills it) and the interprocedural argument, return and
free-variable flows.
"""

from collections import deque
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import (
    Any,
    Deque,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

from tree_sitter import Node

from tree_climber.cfg.call_sites import preorder
from tree_climber.cfg.cfg_types import CallSite, CFGNode, NodeType
from tree_climber.cfg.visitor import CFG
from tree_climber.query.edges import ARGUMENT, CONTROL, DEF_USE, FREE_VARIABLE, RETURN
from tree_climber.query.graph import CodeGraph
from tree_climber.query.path import Path, PathStep
from tree_climber.taint.fields import Accesses, accesses
from tree_climber.taint.rules import Rule, RuleSet, Source, call_matches

RECEIVER = -1
PREDICATES = (NodeType.CONDITION, NodeType.LOOP_HEADER, NodeType.SWITCH_HEAD)

Value = Tuple[Any, ...]
Step = Tuple[Value, Optional[str], Optional[str]]
Region = Tuple[Any, ...]


@dataclass(frozen=True)
class Finding:
    """A tainted value reaching a watched argument of a sink call."""

    rule: str
    source: int
    sink: int
    sink_call: str
    argument: int
    path: Path

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule": self.rule,
            "source": self.source,
            "sink": self.sink,
            "sink_call": self.sink_call,
            "argument": self.argument,
            "path": self.path.to_dict(),
        }

    def __str__(self) -> str:
        return f"{self.rule}: argument {self.argument} of {self.sink_call}\n{self.path}"


@dataclass(frozen=True)
class _Origin:
    node: int
    source: Source
    parameter: Optional[str] = None


class _Program:
    """What every run over one CFG shares: def-use chains, interprocedural flows,
    and the shape of each node's calls."""

    def __init__(
        self,
        graph: CodeGraph,
        implicit_flows: bool = False,
        field_sensitive: bool = False,
    ):
        cfg = graph.cfg
        self.cfg = cfg
        self.field_sensitive = field_sensitive
        self._code: Dict[int, bytes] = {}
        self._accesses: Dict[int, Accesses] = {}
        self.governed: Dict[int, List[int]] = {}
        self.cases: Dict[int, List[int]] = {}
        if implicit_flows:
            self.cases = _match_cases(cfg)
            for node_id, controllers in graph.control_dependence.controllers.items():
                for branch, label in controllers:
                    if (
                        cfg.nodes[branch].node_type in PREDICATES
                        and label != "exception"
                    ):
                        self.governed.setdefault(branch, []).append(node_id)
        self.def_use: Dict[Tuple[int, str], List[int]] = {}
        for chains in graph.def_use_chains.chains.values():
            for chain in chains:
                key = (chain.definition, chain.variable_name)
                self.def_use.setdefault(key, []).extend(chain.uses)

        flows = graph.interprocedural_flows
        self.arguments: Dict[Tuple[int, int, int], List[Tuple[int, str]]] = {}
        for flow in flows.argument_flows:
            key = (flow.call.node, flow.call.site, flow.argument)
            self.arguments.setdefault(key, []).append((flow.callee, flow.parameter))
        self.returns: Dict[int, List[Tuple[int, int]]] = {}
        for flow in flows.return_flows:
            self.returns.setdefault(flow.return_node, []).append(
                (flow.call.node, flow.call.site)
            )
        self.free: Dict[Tuple[int, str], List[int]] = {}
        for flow in flows.free_variable_flows:
            self.free.setdefault((flow.definition, flow.variable), []).append(flow.use)

        functions: Dict[str, List[bool]] = {}
        for entry, name in cfg.context.function_definitions.items():
            info = cfg.nodes[entry].metadata.function
            functions.setdefault(name, []).append(
                info is not None and info.is_constructor
            )
        self.defined: Set[Tuple[int, int]] = set()
        for node_id, node in cfg.nodes.items():
            for index, site in enumerate(node.metadata.call_sites):
                kinds = functions.get(site.callee or "", [])
                if kinds and not all(kinds):
                    self.defined.add((node_id, index))

    def accesses(self, node: CFGNode) -> Accesses:
        """The fields and keys the node reads and writes, computed once."""
        if node.id not in self._accesses:
            ast = node.ast_node
            self._accesses[node.id] = accesses(ast) if ast is not None else Accesses()
        return self._accesses[node.id]

    def code(self, node: CFGNode) -> bytes:
        """The node's text without string literals and comments, computed once."""
        if node.id not in self._code:
            self._code[node.id] = code_only(node.ast_node) if node.ast_node else b""
        return self._code[node.id]

    def attribute_regions(self, node: CFGNode, source: Source) -> Set[Region]:
        """Where in the node the attribute occurs outside any nested call: the
        statement itself, an argument, or a receiver. Text in string literals
        and comments does not count, nor does a statement that writes to the
        attribute's root (`sys.argv[0] = x` defines `sys`)."""
        pattern = source.attribute_pattern()
        ast = node.ast_node
        if pattern is None or ast is None or ast.text is None:
            return set()
        raw, code = ast.text, self.code(node)
        sites = node.metadata.call_sites

        def span(site: CallSite) -> Tuple[int, int]:
            return site.start_byte - ast.start_byte, site.end_byte - ast.start_byte

        def count(text: bytes) -> int:
            return len(pattern.findall(text.decode("utf-8", errors="replace")))

        def inside(call: int, role: str, position: Optional[int]) -> int:
            return sum(
                count(code[slice(*span(inner))])
                for inner in sites
                if inner.feeds is not None
                and (inner.feeds.call, inner.feeds.role, inner.feeds.position)
                == (call, role, position)
            )

        regions: Set[Region] = set()
        top = sum(
            count(code[slice(*span(site))]) for site in sites if site.feeds is None
        )
        root = (source.attribute or "").split(".")[0]
        written = root in node.metadata.variable_definitions
        if count(code) > top and not written:
            regions.add(("statement",))
        for s, site in enumerate(sites):
            start, end = span(site)
            raw_site, code_site = raw[start:end], code[start:end]
            cursor = len(site.callee_text.encode())
            for i, argument in enumerate(site.arguments):
                text = argument.text.encode()
                found = raw_site.find(text, cursor)
                if found < 0:
                    continue
                cursor = found + len(text)
                if count(code_site[found:cursor]) > inside(s, "argument", i):
                    regions.add(("argument", s, i))
            receiver = (site.receiver or "").encode()
            if receiver and raw_site.startswith(receiver):
                if count(code_site[: len(receiver)]) > inside(s, "receiver", None):
                    regions.add(("argument", s, RECEIVER))
        return regions


LITERALS = frozenset(
    {
        "string",
        "string_literal",
        "char_literal",
        "character_literal",
        "comment",
        "line_comment",
        "block_comment",
    }
)


def code_only(ast: Node) -> bytes:
    """The node's text with string literals and comments blanked out, except the
    code interpolated in an f-string."""
    text = bytearray(ast.text or b"")
    base = ast.start_byte
    stack = [ast]
    keep: List[Node] = []
    while stack:
        current = stack.pop()
        if current.type in LITERALS:
            for index in range(current.start_byte - base, current.end_byte - base):
                text[index] = 0x20
            keep.extend(
                child for child in preorder(current) if child.type == "interpolation"
            )
        else:
            stack.extend(current.children)
    for interpolation in keep:
        start, end = interpolation.start_byte - base, interpolation.end_byte - base
        text[start:end] = (ast.text or b"")[start:end]
    return bytes(text)


class _Run:
    """Taint from one source occurrence, as a worklist over tainted values."""

    def __init__(self, program: _Program, rule: Rule, origin: _Origin):
        self.program = program
        self.cfg = program.cfg
        self.rule = rule
        self.origin = origin
        self.pred: Dict[Value, Optional[Step]] = {}
        self.uses_in: Dict[int, Dict[str, Dict[Optional[str], Value]]] = {}
        self.results_in: Dict[Tuple[int, int], Value] = {}
        self.control_in: Dict[int, Value] = {}
        self.subject_in: Dict[int, Value] = {}
        self.queue: Deque[int] = deque()
        self.queued: Set[int] = set()
        self.findings: Dict[Tuple[int, int, int], Value] = {}
        self.attribute_regions: Set[Region] = set()
        if origin.source.attribute is not None:
            self.attribute_regions = program.attribute_regions(
                self.cfg.nodes[origin.node], origin.source
            )

    def mark(self, value: Value, step: Optional[Step]) -> bool:
        if value in self.pred:
            return False
        self.pred[value] = step
        return True

    def enqueue(self, node: int) -> None:
        if node not in self.queued:
            self.queued.add(node)
            self.queue.append(node)

    def run(self) -> Dict[Tuple[int, int, int], Value]:
        root = ("source", self.origin.node)
        self.mark(root, None)
        if self.origin.parameter is not None:
            self.define(self.origin.node, self.origin.parameter, (root, None, None))
        else:
            self.enqueue(self.origin.node)
        while self.queue:
            node = self.queue.popleft()
            self.queued.discard(node)
            self.evaluate(node)
        return self.findings

    def define(
        self, node: int, variable: str, step: Step, tag: Optional[str] = None
    ) -> None:
        value = ("def", node, variable, tag)
        if not self.mark(value, step):
            return
        shown = variable + tag if tag else variable
        for use in self.program.def_use.get((node, variable), []):
            self.use(use, variable, (value, DEF_USE, shown), tag)
        for use in self.program.free.get((node, variable), []):
            self.use(use, variable, (value, FREE_VARIABLE, shown), tag)

    def use(
        self, node: int, variable: str, step: Step, tag: Optional[str] = None
    ) -> None:
        value = ("use", node, variable, tag)
        if self.mark(value, step):
            tags = self.uses_in.setdefault(node, {}).setdefault(variable, {})
            tags[tag] = value
            self.enqueue(node)

    def evaluate(self, n: int) -> None:
        node = self.cfg.nodes[n]
        metadata = node.metadata
        sites = metadata.call_sites
        tainted = self.uses_in.get(n, {})
        here = n == self.origin.node
        fields = self.program.accesses(node) if self.program.field_sensitive else None

        def readable(name: str) -> Optional[Value]:
            tags = tainted.get(name)
            if not tags:
                return None
            whole = tags.get(None) or tags[min(t for t in tags if t is not None)]
            if fields is None or None in tags:
                return whole
            reads = fields.reads.get(name)
            if reads is None:
                reads = set() if name in fields.writes else {None}
            if None in reads:
                return whole
            for tag in sorted(t for t in reads if t is not None):
                if tag in tags:
                    return tags[tag]
            return None

        def direct(names: Optional[Iterable[str]]) -> Optional[Value]:
            for name in metadata.variable_uses if names is None else names:
                found = readable(name)
                if found is not None:
                    return found
            return None

        def from_attribute(region: Region) -> Optional[Value]:
            if here and region in self.attribute_regions:
                return ("source", n)
            return None

        result: Dict[int, Value] = {}
        argument: Dict[Tuple[int, int], Value] = {}

        def nested(call: int, role: str, position: Optional[int]) -> Optional[Value]:
            for k, inner in enumerate(sites):
                if (
                    k in result
                    and inner.feeds is not None
                    and (inner.feeds.call, inner.feeds.role, inner.feeds.position)
                    == (call, role, position)
                ):
                    return result[k]
            return None

        def taint_argument(s: int, i: int, found: Optional[Value]) -> None:
            if found is not None:
                value = ("argument", n, s, i)
                self.mark(value, (found, None, None))
                argument[(s, i)] = value

        for s in reversed(range(len(sites))):
            site = sites[s]
            for i, arg in enumerate(site.arguments):
                taint_argument(
                    s,
                    i,
                    direct(arg.direct_uses)
                    or nested(s, "argument", i)
                    or from_attribute(("argument", s, i)),
                )
            if site.receiver is not None:
                taint_argument(
                    s,
                    RECEIVER,
                    direct(site.receiver_uses)
                    or nested(s, "receiver", None)
                    or from_attribute(("argument", s, RECEIVER)),
                )
            found = self.call_result(n, s, site, here, argument)
            if found is not None:
                value = ("call", n, s)
                self.mark(value, (found, None, None))
                result[s] = value

        top = [s for s, site in enumerate(sites) if site.feeds is None]
        control = self.control_in.get(n)
        statement = (
            direct(metadata.direct_uses)
            or next((result[s] for s in top if s in result), None)
            or from_attribute(("statement",))
            or control
            or self.subject_in.get(n)
        )
        if statement is not None:
            for case in self.program.cases.get(n, []):
                if case not in self.subject_in:
                    self.subject_in[case] = statement
                    self.enqueue(case)
        if statement is not None and n in self.program.governed:
            branch = ("branch", n)
            self.mark(branch, (statement, None, None))
            for governed in self.program.governed[n]:
                value = ("control", governed)
                if self.mark(value, (branch, CONTROL, None)):
                    self.control_in[governed] = value
                    self.enqueue(governed)

        assigned: Dict[str, int] = {}
        for s in top:
            for variable in sites[s].assigned_to:
                assigned.setdefault(variable, s)
        for variable in metadata.variable_definitions:
            if fields is not None and variable in fields.writes:
                found = (
                    result.get(assigned[variable]) or control
                    if variable in assigned
                    else statement
                )
                if found is not None:
                    self.define(
                        n, variable, (found, None, None), fields.writes[variable]
                    )
                for tag, earlier in tainted.get(variable, {}).items():
                    self.define(n, variable, (earlier, None, None), tag)
                continue
            if variable in assigned:
                found = result.get(assigned[variable]) or control
                if found is None and (
                    metadata.direct_uses is None or variable in metadata.direct_uses
                ):
                    found = direct([variable])
            else:
                found = statement
            if found is not None:
                self.define(n, variable, (found, None, None))

        if node.node_type == NodeType.RETURN and statement is not None:
            returned = ("return", n)
            self.mark(returned, (statement, None, None))
            for call in self.program.returns.get(n, []):
                value = ("call", call[0], call[1])
                if self.mark(value, (returned, RETURN, None)):
                    self.results_in[call] = value
                    self.enqueue(call[0])

        for (s, i), value in argument.items():
            bare = _bare_variable(sites[s], i) if fields is not None else None
            for entry, parameter in self.program.arguments.get((n, s, i), []):
                if bare is not None and bare in tainted:
                    for tag, earlier in tainted[bare].items():
                        self.define(
                            entry, parameter, (earlier, ARGUMENT, parameter), tag
                        )
                else:
                    self.define(entry, parameter, (value, ARGUMENT, parameter))
            if i == RECEIVER:
                continue
            site = sites[s]
            if any(
                call_matches(sink.call, site) and sink.watches(site, i)
                for sink in self.rule.sinks
            ):
                self.findings.setdefault((n, s, i), value)

    def call_result(
        self,
        n: int,
        s: int,
        site: CallSite,
        here: bool,
        argument: Dict[Tuple[int, int], Value],
    ) -> Optional[Value]:
        if any(
            call_matches(sanitizer.call, site) for sanitizer in self.rule.sanitizers
        ):
            return None
        source = self.origin.source
        if here and source.call is not None and call_matches(source.call, site):
            return ("source", n)
        if (n, s) in self.results_in:
            return self.results_in[(n, s)]
        if (n, s) in self.program.defined:
            return None
        passed = [i for i in range(-1, len(site.arguments)) if (s, i) in argument]
        return argument[(s, passed[0])] if passed else None

    def path(self, value: Value) -> Path:
        chain: List[Step] = []
        current: Optional[Value] = value
        while current is not None:
            step = self.pred[current]
            if step is None:
                break
            chain.append((current, step[1], step[2]))
            current = step[0]
        root = current if current is not None else value
        steps = [PathStep.of(self.cfg.nodes[root[1]])]
        for reached, kind, variable in reversed(chain):
            if kind is not None:
                steps.append(PathStep.of(self.cfg.nodes[reached[1]], kind, variable))
        return Path(tuple(steps))


def _bare_variable(site: CallSite, index: int) -> Optional[str]:
    """The variable an argument or receiver is, when it is nothing else."""
    text = site.receiver if index == RECEIVER else site.arguments[index].text
    return text if text is not None and text.isidentifier() else None


def _match_cases(cfg: CFG) -> Dict[int, List[int]]:
    """The first case of each switch head that has one successor (Python `match`):
    it decides on the head's subject, which it does not read. Later cases depend
    on the earlier ones' `false` edges."""
    cases: Dict[int, List[int]] = {}
    for node_id, node in cfg.nodes.items():
        if node.node_type == NodeType.SWITCH_HEAD and len(node.successors) == 1:
            cases[node_id] = list(node.successors)
    return cases


def _origins(program: _Program, rule: Rule) -> List[_Origin]:
    cfg = program.cfg
    origins: List[_Origin] = []
    for source in rule.sources:
        if source.call is not None:
            for node_id in sorted(cfg.nodes):
                sites = cfg.nodes[node_id].metadata.call_sites
                if any(call_matches(source.call, site) for site in sites):
                    origins.append(_Origin(node_id, source))
        elif source.attribute is not None:
            pattern = source.attribute_pattern()
            assert pattern is not None
            for node_id in sorted(cfg.nodes):
                code = program.code(cfg.nodes[node_id])
                if pattern.search(code.decode("utf-8", errors="replace")):
                    origins.append(_Origin(node_id, source))
        else:
            for entry in cfg.entry_node_ids:
                for name in _matching_parameters(cfg.nodes[entry], source):
                    origins.append(_Origin(entry, source, name))
    return origins


def _matching_parameters(entry: CFGNode, source: Source) -> List[str]:
    info = entry.metadata.function
    if info is None:
        return []
    names = {info.call_name, entry.source_text}
    if not any(fnmatchcase(name, source.function) for name in names):
        return []
    parameters = [parameter.name for parameter in info.parameters]
    if isinstance(source.parameter, int):
        if 0 <= source.parameter < len(parameters):
            return [parameters[source.parameter]]
        return []
    return [name for name in parameters if fnmatchcase(name, str(source.parameter))]


Rules = Union[RuleSet, Rule, Sequence[Rule]]


def _rules(rules: Rules, language: Optional[str]) -> List[Rule]:
    if isinstance(rules, RuleSet):
        return rules.for_language(language)
    if isinstance(rules, Rule):
        rules = [rules]
    return [rule for rule in rules if rule.applies_to(language)]


def analyze(
    cfg: Union[CFG, CodeGraph],
    rules: Rules,
    language: Optional[str] = None,
    implicit_flows: bool = False,
    field_sensitive: bool = False,
) -> List[Finding]:
    """Findings of the rules on a CFG, ordered by rule, source, sink and argument.
    `language` filters out rules for other languages. With `implicit_flows`, a
    branch on a tainted value taints what is defined or returned in the code it
    decides on. With `field_sensitive`, a write into a field or constant key
    taints only that field, and reads of other fields stay clean. Given a
    `CodeGraph`, taint reuses its data flow instead of solving it again."""
    graph = cfg if isinstance(cfg, CodeGraph) else CodeGraph(cfg)
    cfg = graph.cfg
    program = _Program(graph, implicit_flows, field_sensitive)
    findings: Dict[Tuple[str, int, int, int, int], Finding] = {}
    for rule in _rules(rules, language):
        for origin in _origins(program, rule):
            run = _Run(program, rule, origin)
            for (sink, s, i), value in run.run().items():
                key = (rule.id, origin.node, sink, s, i)
                if key not in findings:
                    site = cfg.nodes[sink].metadata.call_sites[s]
                    findings[key] = Finding(
                        rule.id, origin.node, sink, site.callee_text, i, run.path(value)
                    )
    return [findings[key] for key in sorted(findings)]


def analyze_source(
    language: str,
    source: str,
    rules: Rules,
    implicit_flows: bool = False,
    field_sensitive: bool = False,
) -> List[Finding]:
    graph = CodeGraph.from_source(language, source)
    return analyze(graph, rules, language, implicit_flows, field_sensitive)
