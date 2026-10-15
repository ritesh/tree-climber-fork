"""Tests for `python -m tree_climber.stress`, the corpus stress runner."""

import json
import os
import signal
import time
from pathlib import Path

import pytest

from tree_climber import stress
from tree_climber.stress import (
    STAGES,
    TIMEOUT,
    WORKER_DIED,
    Failure,
    FileResult,
    Known,
    Task,
    collect,
    compare,
    format_report,
    load_baseline,
    main,
    run,
    run_file,
    summary,
)

PROGRAM = """\
import os


def run(command):
    os.system(command)


run(input())
"""


@pytest.fixture
def corpus(tmp_path):
    (tmp_path / "app.py").write_text(PROGRAM)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "types.pyi").write_text("x: int\n")
    (tmp_path / "main.c").write_text("int main(void) { return 0; }\n")
    (tmp_path / "Main.java").write_text("class Main { void f() {} }\n")
    (tmp_path / "notes.txt").write_text("not code\n")
    return tmp_path


def task(path: Path, name: str = "", language: str = "python") -> Task:
    return Task(str(path), name or path.name, language)


def test_collect_finds_supported_files_named_relative_to_their_root(corpus):
    tasks = collect([corpus])
    assert [(t.name, t.language) for t in tasks] == [
        ("Main.java", "java"),
        ("app.py", "python"),
        ("main.c", "c"),
        ("pkg/types.pyi", "python"),
    ]
    assert tasks[1].path == str(corpus / "app.py")


def test_collect_filters_by_language_and_takes_files_as_roots(corpus):
    assert [t.name for t in collect([corpus], "python")] == ["app.py", "pkg/types.pyi"]
    assert collect([corpus / "main.c", corpus / "notes.txt"]) == [
        Task(str(corpus / "main.c"), "main.c", "c")
    ]


def test_run_file_runs_every_stage(corpus):
    result = run_file(task(corpus / "app.py"), list(STAGES), 60)
    assert result.failure is None
    assert list(result.seconds) == list(STAGES)
    assert result.lines == 8
    assert result.nodes > 0


def test_run_file_always_builds_the_cfg_first(corpus):
    result = run_file(task(corpus / "app.py"), ["taint"], 60)
    assert list(result.seconds) == ["cfg", "taint"]


def test_run_file_reports_the_failing_stage_and_stops(corpus, monkeypatch):
    def broken(work):
        raise ValueError("no such node")

    monkeypatch.setitem(STAGES, "dataflow", broken)
    result = run_file(task(corpus / "app.py"), list(STAGES), 60)
    assert result.failure is not None
    assert (result.failure.stage, result.failure.error) == ("dataflow", "ValueError")
    assert result.failure.message == "no such node"
    assert "ValueError: no such node" in result.failure.traceback[-1]
    assert list(result.seconds) == ["cfg", "dataflow"]


def test_run_file_times_out_and_restores_the_alarm(corpus, monkeypatch):
    monkeypatch.setitem(STAGES, "control", lambda work: time.sleep(5))
    started = time.monotonic()
    result = run_file(task(corpus / "app.py"), ["control", "taint"], 0.2)
    assert time.monotonic() - started < 2
    assert result.failure == Failure("control", TIMEOUT, "over 0.2 s")
    assert signal.getsignal(signal.SIGALRM) == signal.SIG_DFL
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


def test_run_keeps_the_order_of_the_tasks(corpus):
    tasks = collect([corpus])
    results = run(tasks, ["dataflow"], 60, jobs=2)
    assert [r.name for r in results] == [t.name for t in tasks]
    assert all(r.failure is None for r in results)


def test_a_dying_worker_fails_its_file_only(corpus, monkeypatch):
    def die_on_c(work):
        if work.language == "c":
            os._exit(3)

    monkeypatch.setitem(STAGES, "control", die_on_c)
    tasks = collect([corpus])
    done = []
    results = run(tasks, ["control"], 60, jobs=2, progress=lambda d, t: done.append(d))
    failed = {r.name: r.failure for r in results if r.failure is not None}
    assert failed == {"main.c": Failure("?", WORKER_DIED, "exit code 3")}
    assert len(results) == 4
    assert done == [1, 2, 3, 4]


def test_a_worker_that_ignores_the_alarm_is_killed(corpus, monkeypatch):
    def hang(work):
        if work.language == "java":
            signal.signal(signal.SIGALRM, signal.SIG_IGN)
            time.sleep(30)

    monkeypatch.setitem(STAGES, "control", hang)
    started = time.monotonic()
    results = run(collect([corpus]), ["control"], 0.1, jobs=1, grace=0.5)
    assert time.monotonic() - started < 10
    failed = {r.name: r.failure for r in results if r.failure is not None}
    assert failed == {"Main.java": Failure("?", TIMEOUT, "no answer in 0.7 s")}


def failing(name: str, stage: str = "cfg", error: str = "ValueError") -> FileResult:
    return FileResult(name, "python", failure=Failure(stage, error, "boom"))


def test_compare_splits_new_known_and_fixed():
    results = [
        failing("a.py"),
        failing("b.py", "taint", "KeyError"),
        FileResult("c.py", "python"),
    ]
    baseline = {
        Known("a.py", "cfg", "ValueError"),
        Known("b.py", "taint", "RecursionError"),
        Known("c.py", "cfg", "ValueError"),
        Known("elsewhere.py", "cfg", "ValueError"),
    }
    comparison = compare(results, baseline)
    assert [r.name for r in comparison.new] == ["b.py"]
    assert [r.name for r in comparison.known] == ["a.py"]
    assert comparison.fixed == [
        Known("b.py", "taint", "RecursionError"),
        Known("c.py", "cfg", "ValueError"),
    ]


def test_load_baseline(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps(
            {
                "known": [
                    {"file": "a.py", "stage": "cfg", "error": "Timeout", "issue": 1}
                ]
            }
        )
    )
    assert load_baseline(path) == {Known("a.py", "cfg", "Timeout")}


def test_summary_groups_failures_and_lists_the_slowest():
    fast = FileResult("fast.py", "python", lines=10, nodes=5, seconds={"cfg": 0.1})
    slow = FileResult(
        "slow.py", "python", lines=99, nodes=50, seconds={"cfg": 1.0, "taint": 2.0}
    )
    data = summary(
        [fast, slow, failing("x.py"), failing("y.py"), failing("z.py", "taint")],
        slowest=1,
    )
    assert data["files"] == 5
    assert (data["ok"], data["failed"]) == (2, 3)
    assert data["seconds"] == {"cfg": 1.1, "taint": 2.0}
    assert [(g["stage"], g["count"], g["files"]) for g in data["failures"]] == [
        ("cfg", 2, ["x.py", "y.py"]),
        ("taint", 1, ["z.py"]),
    ]
    assert data["slowest"] == [
        {"file": "slow.py", "seconds": 3.0, "lines": 99, "nodes": 50}
    ]
    report = format_report(data, compare([failing("x.py")], set()))
    assert "     2 [cfg] ValueError: boom\n       e.g. x.py" in report
    assert "new: x.py [cfg] ValueError" in report
    assert report.endswith("1 new failures, 0 known, 0 fixed")


def test_main_exits_with_1_on_new_failures_only(corpus, monkeypatch, capsys):
    def broken(work):
        if work.language == "java":
            raise RuntimeError("unsupported")

    monkeypatch.setitem(STAGES, "taint", broken)
    report = corpus / "report.json"
    assert main([str(corpus), "-q", "--json", str(report)]) == 1
    out = capsys.readouterr().out
    assert out.startswith("files=4 ok=3 failed=1")
    assert "new: Main.java [taint] RuntimeError" in out
    data = json.loads(report.read_text())
    assert data["new"] == ["Main.java"]
    assert [r["name"] for r in data["results"]] == [
        "Main.java",
        "app.py",
        "main.c",
        "pkg/types.pyi",
    ]

    baseline = corpus / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "known": [
                    {"file": "Main.java", "stage": "taint", "error": "RuntimeError"}
                ]
            }
        )
    )
    assert main([str(corpus), "-q", "--baseline", str(baseline)]) == 0
    assert "0 new failures, 1 known, 0 fixed" in capsys.readouterr().out


def test_main_with_a_language_and_stages(corpus, capsys):
    assert main([str(corpus), "-q", "-l", "c", "--stages", "dataflow", "-j", "1"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("files=1 ok=1 failed=0")
    assert "seconds: cfg " in out and ", dataflow " in out and "taint" not in out


def test_main_rejects_missing_roots_and_empty_corpora(tmp_path, capsys):
    with pytest.raises(SystemExit) as missing:
        main([str(tmp_path / "nowhere")])
    assert missing.value.code == 2
    (tmp_path / "notes.txt").write_text("")
    with pytest.raises(SystemExit) as empty:
        main([str(tmp_path)])
    assert empty.value.code == 2
    assert "no files in a supported language" in capsys.readouterr().err


def test_the_module_runs_as_a_script(corpus):
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "tree_climber.stress", str(corpus / "app.py"), "-q"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.startswith("files=1 ok=1 failed=0")
    assert stress.__doc__ is not None
