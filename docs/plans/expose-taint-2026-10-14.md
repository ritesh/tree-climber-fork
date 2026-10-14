# Expose taint analysis and queries (#50), 2026-10-14

Part of #44. Builds on the query API (#47) and the taint analysis (#48); only their public APIs are used.

## Problem
`tree_climber.taint` and `tree_climber.query` are only reachable from Python. #50 asks for them in the CLI, the HTTP API and the web UI, and for a "Tracing user input" section in the Python guide.

## Plan

### CLI
The CLI is one Typer command whose first argument is a file, so a plain Typer group would turn `tree-climber test/example.c --draw-cfg` into "no such command". Instead the existing command gets a command class that hands `taint ...` and `query ...` to their own commands and runs everything else as before (`--help`, `--version`, the draw options and the existing tests are unchanged). A file literally named `taint` or `query` can be given as `./taint`.

- `tree-climber taint FILE [--rules builtin|rules.json] [--json] [--draw-cfg] [--draw-dfg] [--finding N] [-o DIR] [--show] [-l LANG]`
  - Prints each finding: rule, sink call, argument, and its path, one step per line with the source line number.
  - `--rules` defaults to `builtin` (the example rule sets). A JSON file is loaded with `RuleSet.load`. A `.yaml`/`.yml` file is rejected with a message to use JSON (PyYAML is not a dependency). A rule file with no rule for the file's language is an error, so it cannot pass silently as "no findings".
  - `--json` prints `{"findings": [Finding.to_dict(), ...]}`.
  - `--draw-cfg` / `--draw-dfg` draw the CFG / DFG image of each finding (or only `--finding N`) with the path highlighted: path nodes filled and outlined, and one bold numbered edge per path step labeled with its edge kind and variable. Files are `<name>_finding<N>_cfg.png` / `_dfg.png`.
  - `-` reads stdin (with `--language`).
- `tree-climber query FILE --calls NAME` (repeatable): the nodes that call NAME, with line and enclosing function.
- `tree-climber query FILE --slice-from LINE [--backward] [--variable V] [--no-across-calls]`: the forward (or backward) slice from the nodes starting on LINE; by default it crosses calls (`interprocedural_edges()`), `--no-across-calls` stays in one function. `--json` for both.
- The CFG/DFG visualizers get a `graph()` method (build without drawing) so the highlight reuses them; `visualize()` is unchanged in behavior.

### Shared helpers
`src/tree_climber/reporting.py`: rule loading (`builtin` / JSON / YAML rejection), the line of a node, nodes on a line, the slice from a line, and the JSON dict of a node. Used by both the CLI and the API so they agree.

### API
- `POST /taint` `{source_code, language, rules?}`: `rules` is a rule-set dict (the JSON format); omitted means the built-in example rules. Response `{success, findings, error}`, findings as `Finding.to_dict()` (paths in the shared `Path` format, node ids as in `/parse`).
- `POST /query` `{source_code, language, kind: "calls"|"slice", names?, line?, backward?, variable?, across_calls?}`. Response `{success, nodes, error}`.
- Validation like `/parse` (language via the registry; pydantic for the shape); bad rules come back as `success: false` with the error.

### Web UI
After each `/parse`, the graph also calls `/taint` with the built-in rules. A findings panel lists them; selecting one highlights its path in the graph (nodes and steps, a step with no drawn edge gets a temporary edge) and every node span of the path in the editor. Selecting it again, or editing the code, clears the highlight. The Python sample gets a small vulnerable function so the panel has something to show.

### Docs
"Tracing user input" in `docs/python-guide.md`: the CLI commands with real output, the JSON shape, the API calls, the web UI, and what the analysis does not do (single file).

## Tests
- CLI (typer `CliRunner`): text and JSON output of `taint` on the guide's example, `--rules` with builtin / JSON / YAML / missing / malformed / no rule for the language, stdin, drawing (`--draw-cfg`, `--draw-dfg`, `--finding N`, out-of-range N), the highlight on the graph object (colors, labels, added edges), `query --calls` and `--slice-from` (forward, backward, across calls or not, variable, a line with no node), the existing draw commands still working and `--help` listing the new commands.
- API: the endpoint coroutines called directly as in `test/viz/test_api.py` (httpx, needed by `TestClient`, is not installed): findings, custom rules, bad rules, node ids matching `/parse`, both query kinds, validation errors.
- The guide's new examples pinned in a test.
- Mutation-check the new Python code.
- Run `taint` over a sample of the standard library for crashes and time.
- Drive the web UI with Playwright: select a finding, check the graph and editor highlights, screenshot.

## Results

Executive summary: the taint analysis and the two common queries are now usable without Python. `tree-climber taint FILE` prints findings with their paths (text or JSON) and draws a finding's path on the CFG/DFG image; `tree-climber query FILE --calls NAME | --slice-from LINE` answers "who calls X" and "what does line N affect / depend on"; `POST /taint` and `POST /query` return the same data as JSON; the web UI lists findings and highlights the selected one in the graph and the editor; the Python guide has a "Tracing user input" section whose commands and outputs are pinned by tests. The existing draw command is unchanged (the existing CLI tests pass unmodified).

Verified:
- Checks: `ruff format --check src test`, `ruff check src test`, `pyright src test` (0 errors), `pytest test` 1576 passed, 20 xfailed (baseline 1495 passed, 20 xfailed: 81 new tests). Frontend: `bun run build` passes; `bun run lint` reports 25 problems (18 errors, 7 warnings), the same 25 as on master before this change (none in the new code).
- Tests: 62 CLI tests (`test/cli/test_taint_query.py`: output text and JSON, every `--rules` error, stdin, language override, drawing and the highlight on the graph objects, query kinds and errors, the subcommand dispatch, the real entry point, the guide's program, commands, outputs and API response), 19 API tests in `test/viz/test_api.py` (endpoint coroutines called directly, as the existing tests do; `httpx`, which `TestClient` needs, is not installed).
- Mutation check: 50 mutants of the new Python code (reporting, commands, dispatch, highlight, endpoints). First run: 40 caught, 10 survived. Fixes: four tests added (multi-line node text, drawn images carry the highlight, `-l` overrides the extension, a step without an edge kind); one helper simplified after checking that no node span nests inside another on 58 files (the "innermost spanning node" choice was unreachable), and its two replacement mutants are caught. Final: 46 caught, 4 survived, all equivalent through the CLI: a `None` line in a finding path (finding paths only contain nodes with an AST node), the lower bound of `--finding` (Typer's `min=1` rejects 0 first), `--show` without drawing (nothing saved to open), and the pre-existing `draw_cfg` guard in `CFGVisualizer.visualize` (only called when it holds).
- Real code: `taint --json` plus two queries on all 686 non-test files of the CPython 3.12 standard library (310,500 lines): no crash or error, 57.7 s for taint in total, median 0.025 s per file, slowest 1.28 s (`tkinter/__init__.py`; 1.5 s end to end from the shell). 45 findings with the example rules, many through the documented over-approximations (a container or module object is one value: `sys.argv[:0] = ...` taints `sys`).
- PyGoat (80 files) and DVPWA (21 files), per file: no errors, under 1 s each in total. The example rules find nothing (their sources are Flask's `request.args`, not Django's `request.GET` or aiohttp's `request.post()`). With a framework rule file (Django/aiohttp attributes as sources, `*.raw`, `*.execute`, `subprocess.*`, `eval`, `pickle.loads` as sinks), PyGoat gives 9 findings in `introduction/views.py` and `introduction/mitre.py` (SQL built from `request.POST` into `objects.raw`, `subprocess.Popen`, `eval`, `pickle.loads`); DVPWA gives none: its SQL injection crosses files (the view reads `request.post()`, the DAO in another module runs the query).
- Web UI with Playwright (Chromium): with the Python sample, the panel lists one finding; selecting it marks 4 graph nodes and adds 3 numbered step edges (`1: def_use host`, `2: argument command`, `3: def_use command`), and decorates 4 editor ranges (source and sink darker); selecting it again clears both, and editing the code clears the selection and re-runs the analysis.

Limitations:
- Rules are JSON; a `.yaml` file is refused with a message (the issue's example says `rules.yaml`; PyYAML is not a dependency).
- One file at a time, as the analysis is; the web UI uses the built-in rules only.
- The editor maps node byte offsets as character offsets (as the existing cursor highlight does), so highlights shift on lines with non-ASCII text.
- In the test environment Monaco's loader could not reach cdn.jsdelivr.net, so the Playwright run served Monaco's files from `node_modules` by intercepting those requests; the app itself was not changed for this.
