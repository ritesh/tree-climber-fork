"""Run the analyses over a corpus of real code and report crashes, timeouts and
slow files.

    python -m tree_climber.stress ROOT... [--language L] [--stages S...]
        [--timeout SECONDS] [--jobs N] [--baseline FILE] [--json FILE]

Each file runs in a worker process with a time limit, so a crash, a hang or a
dying worker is reported for that file and the run goes on. With a baseline
(known failures), the exit status is 1 only for failures not in it.
"""

import argparse
import json
import multiprocessing
import multiprocessing.connection
import os
import signal
import sys
import time
import traceback
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from tree_climber.cfg.builder import CFGBuilder
from tree_climber.cfg.visitor import CFG
from tree_climber.dataflow.analyses.def_use import DefUseSolver
from tree_climber.dataflow.analyses.reaching_definitions import (
    ReachingDefinitionsProblem,
)
from tree_climber.dataflow.control_dependence import control_dependence
from tree_climber.dataflow.interprocedural import analyze_interprocedural
from tree_climber.dataflow.solver import RoundRobinSolver
from tree_climber.language_registry import SUPPORTED_LANGUAGES, language_for_extension
from tree_climber.taint import analyze, builtin_rules


@dataclass
class Work:
    language: str
    source: str
    cfg: Optional[CFG] = None

    def graph(self) -> CFG:
        assert self.cfg is not None
        return self.cfg


def _build(work: Work) -> None:
    builder = CFGBuilder(work.language)
    builder.setup_parser()
    work.cfg = builder.build_cfg(work.source)


def _dataflow(work: Work) -> None:
    cfg = work.graph()
    reaching = RoundRobinSolver().solve(cfg, ReachingDefinitionsProblem())
    DefUseSolver().solve(cfg, reaching)


def _interprocedural(work: Work) -> None:
    analyze_interprocedural(work.graph())


def _control(work: Work) -> None:
    control_dependence(work.graph())


def _taint(work: Work) -> None:
    analyze(work.graph(), builtin_rules(work.language), work.language)


def _taint_precise(work: Work) -> None:
    analyze(
        work.graph(),
        builtin_rules(work.language),
        work.language,
        implicit_flows=True,
        field_sensitive=True,
    )


STAGES: Dict[str, Callable[[Work], None]] = {
    "cfg": _build,
    "dataflow": _dataflow,
    "interprocedural": _interprocedural,
    "control": _control,
    "taint": _taint,
    "taint-precise": _taint_precise,
}

TIMEOUT = "Timeout"
WORKER_DIED = "WorkerDied"


@dataclass(frozen=True)
class Task:
    path: str
    name: str
    language: str


@dataclass
class Failure:
    stage: str
    error: str
    message: str
    traceback: List[str] = field(default_factory=list)


@dataclass
class FileResult:
    name: str
    language: str
    lines: int = 0
    nodes: int = 0
    seconds: Dict[str, float] = field(default_factory=dict)
    failure: Optional[Failure] = None

    @property
    def total_seconds(self) -> float:
        return sum(self.seconds.values())


class _Timeout(Exception):
    pass


def _on_alarm(*_: Any) -> None:
    raise _Timeout()


def collect(roots: Sequence[Path], language: Optional[str] = None) -> List[Task]:
    """The files under each root (or the roots themselves) in a supported
    language, named relative to their root."""
    tasks = []
    for root in roots:
        paths = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in paths:
            found = language_for_extension(path.suffix)
            if not path.is_file() or found is None:
                continue
            if language is not None and found != language:
                continue
            name = path.name if path == root else path.relative_to(root).as_posix()
            tasks.append(Task(str(path), name, found))
    return tasks


def run_file(task: Task, stages: Sequence[str], timeout: float) -> FileResult:
    """Run the stages on one file in this process, stopping at the first that
    fails or runs out of time."""
    source = Path(task.path).read_bytes().decode("utf-8", errors="replace")
    result = FileResult(task.name, task.language, lines=len(source.splitlines()))
    work = Work(task.language, source)
    previous = signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, timeout)
    stage = "cfg"
    try:
        for stage in ["cfg", *(s for s in stages if s != "cfg")]:
            start = time.perf_counter()
            try:
                STAGES[stage](work)
            finally:
                result.seconds[stage] = time.perf_counter() - start
            if stage == "cfg":
                result.nodes = len(work.graph().nodes)
    except _Timeout:
        result.failure = Failure(stage, TIMEOUT, f"over {timeout:g} s")
    except Exception as error:
        lines = traceback.format_exc().splitlines()
        result.failure = Failure(
            stage, type(error).__name__, str(error)[:200], lines[-6:]
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
    return result


def _worker(tasks: Any, results: Any, stages: Sequence[str], timeout: float) -> None:
    while (item := tasks.recv()) is not None:
        index, task = item
        results.send((index, run_file(task, stages, timeout)))


@dataclass
class _Slot:
    process: Any
    tasks: Any
    results: Any
    index: Optional[int] = None
    started: float = 0.0


def run(
    tasks: Sequence[Task],
    stages: Sequence[str],
    timeout: float,
    jobs: int = 1,
    progress: Optional[Callable[[int, int], None]] = None,
    grace: float = 5.0,
) -> List[FileResult]:
    """Run every task in worker processes, one file at a time each. A worker
    that dies, or does not answer within twice the timeout plus `grace`, is
    replaced and its file reported as failed."""
    context: Any = multiprocessing.get_context(
        "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn"
    )
    deadline = 2 * timeout + grace
    pending = list(range(len(tasks)))[::-1]
    results: Dict[int, FileResult] = {}

    def start_slot() -> _Slot:
        task_reader, task_writer = context.Pipe(duplex=False)
        result_reader, result_writer = context.Pipe(duplex=False)
        process = context.Process(
            target=_worker,
            args=(task_reader, result_writer, list(stages), timeout),
            daemon=True,
        )
        process.start()
        task_reader.close()
        result_writer.close()
        return _Slot(process, task_writer, result_reader)

    def finish(index: int, result: FileResult) -> None:
        results[index] = result
        if progress is not None:
            progress(len(results), len(tasks))

    def assign(slot: _Slot) -> None:
        if pending:
            slot.index = pending.pop()
            slot.started = time.monotonic()
            slot.tasks.send((slot.index, tasks[slot.index]))

    slots = [start_slot() for _ in range(max(1, min(jobs, len(tasks))))]
    for slot in slots:
        assign(slot)
    while len(results) < len(tasks):
        busy = [slot for slot in slots if slot.index is not None]
        multiprocessing.connection.wait(
            [slot.results for slot in busy] + [slot.process.sentinel for slot in busy],
            timeout=0.5,
        )
        for position, slot in enumerate(slots):
            if slot.index is None:
                continue
            if slot.results.poll():
                try:
                    index, result = slot.results.recv()
                except EOFError:
                    pass
                else:
                    slot.index = None
                    finish(index, result)
                    assign(slot)
                    continue
            overdue = time.monotonic() - slot.started > deadline
            if slot.process.is_alive() and not overdue:
                continue
            slot.process.kill()
            slot.process.join()
            slot.tasks.close()
            slot.results.close()
            task = tasks[slot.index]
            failure = (
                Failure("?", TIMEOUT, f"no answer in {deadline:g} s")
                if overdue
                else Failure("?", WORKER_DIED, f"exit code {slot.process.exitcode}")
            )
            finish(slot.index, FileResult(task.name, task.language, failure=failure))
            slots[position] = start_slot()
            assign(slots[position])
    for slot in slots:
        slot.tasks.send(None)
    for slot in slots:
        slot.process.join(timeout=5)
        if slot.process.is_alive():
            slot.process.kill()
    return [results[index] for index in range(len(tasks))]


@dataclass(frozen=True)
class Known:
    name: str
    stage: str
    error: str


def load_baseline(path: Path) -> Set[Known]:
    """Known failures: `{"known": [{"file", "stage", "error", "issue"}, ...]}`,
    where `error` is the exception's type name (or Timeout, WorkerDied)."""
    data = json.loads(path.read_text())
    return {
        Known(entry["file"], entry["stage"], entry["error"])
        for entry in data.get("known", [])
    }


@dataclass
class Comparison:
    new: List[FileResult]
    known: List[FileResult]
    fixed: List[Known]


def compare(results: Sequence[FileResult], baseline: Set[Known]) -> Comparison:
    failed = [result for result in results if result.failure is not None]
    keys = {
        Known(r.name, r.failure.stage, r.failure.error): r
        for r in failed
        if r.failure is not None
    }
    names = {result.name for result in results}
    return Comparison(
        new=[result for key, result in keys.items() if key not in baseline],
        known=[result for key, result in keys.items() if key in baseline],
        fixed=sorted(
            (key for key in baseline if key not in keys and key.name in names),
            key=lambda key: key.name,
        ),
    )


def summary(results: Sequence[FileResult], slowest: int = 10) -> Dict[str, Any]:
    failed = [r for r in results if r.failure is not None]
    seconds: Dict[str, float] = defaultdict(float)
    for result in results:
        for stage, spent in result.seconds.items():
            seconds[stage] += spent
    groups: Dict[Tuple[str, str, str], List[FileResult]] = defaultdict(list)
    for result in failed:
        assert result.failure is not None
        failure = result.failure
        groups[(failure.stage, failure.error, failure.message[:80])].append(result)
    return {
        "files": len(results),
        "ok": len(results) - len(failed),
        "failed": len(failed),
        "lines": sum(r.lines for r in results),
        "nodes": sum(r.nodes for r in results),
        "seconds": {stage: round(spent, 2) for stage, spent in seconds.items()},
        "failures": [
            {
                "stage": stage,
                "error": error,
                "message": message,
                "count": len(members),
                "files": [member.name for member in members],
                "traceback": members[0].failure.traceback if members[0].failure else [],
            }
            for (stage, error, message), members in sorted(
                groups.items(), key=lambda item: (-len(item[1]), item[0])
            )
        ],
        "slowest": [
            {
                "file": r.name,
                "seconds": round(r.total_seconds, 2),
                "lines": r.lines,
                "nodes": r.nodes,
            }
            for r in sorted(
                (r for r in results if r.failure is None),
                key=lambda r: -r.total_seconds,
            )[:slowest]
        ],
    }


def format_report(data: Dict[str, Any], comparison: Comparison) -> str:
    lines = [
        f"files={data['files']} ok={data['ok']} failed={data['failed']} "
        f"lines={data['lines']} nodes={data['nodes']}",
        "seconds: "
        + ", ".join(f"{stage} {spent}" for stage, spent in data["seconds"].items()),
    ]
    if data["failures"]:
        lines.append("failures:")
    for group in data["failures"]:
        lines.append(
            f"  {group['count']:4d} [{group['stage']}] {group['error']}: "
            f"{group['message']}"
        )
        lines.append(f"       e.g. {group['files'][0]}")
        lines.extend(f"       {line}" for line in group["traceback"])
    if data["slowest"]:
        lines.append("slowest:")
    for entry in data["slowest"]:
        lines.append(
            f"  {entry['seconds']:7.2f} s  {entry['lines']:6d} lines  "
            f"{entry['nodes']:6d} nodes  {entry['file']}"
        )
    for result in comparison.new:
        assert result.failure is not None
        lines.append(
            f"new: {result.name} [{result.failure.stage}] {result.failure.error}"
        )
    for known in comparison.fixed:
        lines.append(
            f"fixed (remove from the baseline): {known.name} [{known.stage}] "
            f"{known.error}"
        )
    lines.append(
        f"{len(comparison.new)} new failures, {len(comparison.known)} known, "
        f"{len(comparison.fixed)} fixed"
    )
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tree_climber.stress",
        description="Run the analyses over a corpus and report crashes, "
        "timeouts and slow files.",
    )
    parser.add_argument("roots", nargs="+", type=Path, help="files or directories")
    parser.add_argument("--language", "-l", choices=SUPPORTED_LANGUAGES)
    parser.add_argument(
        "--stages",
        nargs="+",
        choices=list(STAGES),
        default=list(STAGES),
        help="stages after cfg to run (default: all)",
    )
    parser.add_argument("--timeout", type=float, default=60.0, help="seconds per file")
    parser.add_argument("--jobs", "-j", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--baseline", type=Path, help="JSON file of known failures")
    parser.add_argument("--json", type=Path, help="write the report as JSON")
    parser.add_argument("--quiet", "-q", action="store_true", help="no progress")
    args = parser.parse_args(argv)

    missing = [root for root in args.roots if not root.exists()]
    if missing:
        parser.error(f"not found: {', '.join(map(str, missing))}")
    tasks = collect(args.roots, args.language)
    if not tasks:
        parser.error("no files in a supported language")
    baseline = load_baseline(args.baseline) if args.baseline else set()

    def progress(done: int, total: int) -> None:
        if not args.quiet and (done % 100 == 0 or done == total):
            print(f"{done}/{total}", file=sys.stderr, flush=True)

    results = run(tasks, args.stages, args.timeout, args.jobs, progress)
    data = summary(results)
    comparison = compare(results, baseline)
    print(format_report(data, comparison))
    if args.json:
        data["results"] = [asdict(result) for result in results]
        data["new"] = [result.name for result in comparison.new]
        data["fixed"] = [asdict(known) for known in comparison.fixed]
        args.json.write_text(json.dumps(data, indent=2))
    return 1 if comparison.new else 0


if __name__ == "__main__":
    sys.exit(main())
