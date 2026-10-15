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
