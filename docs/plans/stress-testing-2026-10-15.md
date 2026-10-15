# Stress testing against real corpora (#56), 2026-10-15

## Problem
Unit tests cover the constructs we thought of. The first ad-hoc run over CPython's test suite found #55, but the script lives only in the issue, it predates the interprocedural layer, control dependence and taint, and nothing runs it again.

## Plan

### `python -m tree_climber.stress`
A module in the package (so it is type-checked, tested, and runnable from any checkout):

```
python -m tree_climber.stress ROOT... [--language L] [--stages ...] [--timeout S]
    [--jobs N] [--baseline FILE] [--json FILE]
```

- Collects files under each ROOT by extension (the language registry's), optionally one language.
- Runs each file through the stages, in order: `cfg` (parse and build), `dataflow` (reaching definitions and def-use), `interprocedural`, `control` (control dependence), `taint` (built-in rules), `taint-precise` (built-in rules with `implicit_flows` and `field_sensitive`). `--stages` picks a subset; the default is all of them.
- A per-file timeout (`SIGALRM`, so the timed-out file is reported and the run goes on). `--jobs N` runs files in worker processes; a worker that dies (a segfault in the parser, the recursion limit's C-level overflow) is reported as a crash of that file, not of the run.
- Report: totals (files, lines, CFG nodes, seconds per stage), failures grouped by stage and error with one example traceback each, timeouts, slowest files. `--json` writes the same as data.
- `--baseline FILE`: a JSON list of known failures (`{"file", "stage", "error"}`, each with the issue it is tracked in). The exit status is 1 when there is a failure or timeout not in the baseline; baseline entries that now pass are reported so they can be removed.

### Scheduled CI
`.github/workflows/stress.yml`, weekly and on `workflow_dispatch`, not on pull requests: one job per pinned corpus, each run with `--jobs`, a timeout and its baseline, uploading the JSON report as an artifact.
- CPython `Lib` at a pinned tag (stdlib and `Lib/test`, including `test_grammar.py`, `test_patma.py` and the deliberately invalid `badsyntax_*` files);
- typeshed at a pinned commit (`.pyi` stubs, never stress-tested);
- Black's `tests/data` at a pinned tag (oddly formatted code, close to what the editor sends).

C and Java corpora are left for later: the C builder already has known crashes (#64).

### Property tests with Hypothesmith
`hypothesis` and `hypothesmith` in the dev group. A test that builds, analyses and runs taint on generated programs (`from_grammar()` and `from_node()`), and on prefixes of them, as the editor sends half-written code. `derandomize=True` with a small example count on every PR, so CI is deterministic; a `stress` Hypothesis profile with many more examples for the scheduled job.

### Crashes found
Each new crash is reproduced, then fixed here if small and local to one visitor, or else filed as an issue and listed in the baseline.

## Tests
- The module: file collection and language filter, each stage run, a crash and a timeout reported (with a fake stage), grouping, baseline matching (new failure fails, known passes, fixed reported), a worker death under `--jobs`, JSON report shape.
- The property tests themselves.

## Results
Executive summary: `python -m tree_climber.stress` runs all six stages over a corpus, one file at a time in worker processes, and reports crashes, timeouts (the in-process alarm, and a kill when a worker stops answering), dying workers and the slowest files, with a baseline of known failures (`.github/stress-baseline.json`, empty). A weekly `Stress` workflow runs it on pinned CPython `Lib` (v3.12.7), typeshed (`86d68f8`) and Black's `tests` (25.1.0), and runs the Hypothesmith property tests with 1,000 examples each. On every pull request the property tests run 20 derandomized examples each (about 10 s). The Python analyses pass all three corpora; the runs found one performance bug, fixed here, and one remaining slowdown, filed as #70.

| Corpus | Files | Lines | Failures | Wall (4 workers) | Slowest |
|---|---|---|---|---|---|
| CPython `Lib` v3.12.7 (Python) | 1,790 | 0.89M | 0 | 44 s | 3.0 s, `test_typing.py` |
| typeshed `86d68f8` | 5,478 | 374k | 0 (3 timeouts at 60 s before the fix) | 145 s | 130 s, `winerror.pyi` |
| Black 25.1.0 `tests` | 234 | 24k | 0 | 3 s | 1.7 s, `test_black.py` |
| Hypothesmith, 3 × 1,000 examples | | | 0 | 527 s | |

- **Fixed: data flow on long stubs.** `RoundRobinSolver` deep-copied each node's OUT set on every visit, and `DataflowFact.__hash__`/`__eq__` sorted and compared attribute dicts. `commctrl.pyi` (1,522 lines) went from 56 s to 4 s after a shallow copy, plus a hash and equality on `(variable_name, node_id)` for `ReachingDefinition`. The full suite is unchanged (1,700 passed).
- **Filed: #70.** Reaching definitions are still O(N²) on N distinct module-level definitions (`winerror.pyi`, 7,270 lines: 130 s). The workflow uses a 300 s per-file timeout until that is fixed.
- **Not run in CI: C.** CPython's `Lib/test/clinic.test.c` crashes in `visit_labeled_statement`, at the same site as #58. C and Java corpora wait for the C crash fixes (#58, #64); the workflow runs `--language python`.
- **Tests.** `test/test_stress.py` (16 tests) covers collection, stages, failures, the alarm being restored, a worker dying (`os._exit`), a worker ignoring the alarm (killed after the grace period), baseline comparison, the summary and report, and `main` exit codes and JSON. `test/test_property.py` has 3 property tests.
- **Mutation check of `stress.py`.** 19 mutations. 3 survived at first: the alarm not being cleared after a successful file, the failure-group ordering, and failed files excluded from the slowest list. The tests were strengthened for all three. The third exposed a real bug: the slowest list was cut to its top N before failed files were removed, so a slow failure could hide the real slowest files. That is fixed, and all 19 mutations are now caught.
- **Not done.** The tree-sitter-python corpus (not `.py` files), Ruff's parser fixtures, PyPI top packages and the research datasets from the issue are left for later. The three corpora above cover stdlib and test-suite code, stubs, and odd formatting.
- Checks: ruff format and lint clean, pyright 0 errors, 1,700 passed, 20 xfailed.
