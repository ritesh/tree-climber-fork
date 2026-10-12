# Python tests, fixtures, wiring and docs (2026-10-12)

Closes the cross-cutting issue #12 of the Python epic (#1). Most of its checklist landed with the visitor issues; this finishes the rest and records the epic's results.

## What was already done (verified, not redone)
- `.py`/`.pyi` detection, `--language python`, `/parse` accepting `python`, README "Supported Languages" and the Python guide: PRs for #4, #5, #38 and #40.
- Python DFG tests (`test_python_dfg.py`), and the regression test for `else` in identifiers and ternaries (`elsewhere = x`, in `test_python_control_flow.py`), plus the C/Java regressions from #3.

## Remaining, and what this change does
1. **Fixtures**, mirroring `test/c_cfg/` and `test/java_cfg/`: `nested_structures.py`, `edge_cases.py`, `data_flow_patterns.py`, each describing its scenarios in its own header, with a minimal `test/python_cfg/README.md`, and `test_python_fixtures.py` to run them.
   - `data_flow_patterns.py` is shaped for the taint epic (#44): source -> assignment -> sink patterns whose def-use chains are asserted, including the known limits (no flow across calls, sanitizers invisible). When the epic changes those, the tests that pin the limits should change with it.
   - The odd formatting, unused names and undefined names in these files are the point, so they are excluded from `ruff` and `pyright` in `pyproject.toml`. A test guards the fixture's one-line statements against being reformatted.
2. **CLI help examples** for Python, and tests that the documented example and stdin input work.
3. **Frontend sample code**: the editor had one shared buffer seeded with a C sample, so choosing Python parsed C as Python. Each language now keeps its own buffer, starting from its own sample (`sampleCode.ts`); an existing shared buffer is migrated to whichever language loads first.
4. **Docs**: a Python section in `docs/plans/extending-languages.md` (limitations, like the C and Java ones) and fixes to its stale steps (`.pyi`, where tests live); the README step for adding a language mentions the sample; the umbrella plan `docs/plans/python-support-2026-10-12.md` is ported from the planning branch with its Results filled in.

## Results

Executive summary: #12 is done and the Python epic's milestone 1 is complete. `ruff format --check`, `ruff check`, `pyright`, `pytest` (640 passed, 20 strict xfails) pass, and `bun run build` passes.

- Fixtures and tests: 58 tests in `test_python_fixtures.py` over 3 new fixtures (nested structures, edge cases, data-flow patterns) plus the existing one. Reading the CFGs of the fixtures to write expectations was a review of its own and found nothing wrong: break/continue targets in nested loops and loop `else`, jumps through one and two `finally` blocks, matches inside loops and cases, and unreachable code all behave as designed. One expectation I wrote was wrong (`a = b = 1` does not reach the walrus condition, because `a += b` kills it); the code was right.
- CLI: 2 new tests.
- Frontend: verified in a real browser (Chromium via Playwright, outside the repo) through the network: a fresh Python profile parses the Python sample; switching python -> c -> java -> python parses each language's sample; a legacy shared buffer migrates to `tree_climber_code_c` and is removed. Not verified: typing in the Monaco editor (loads from a CDN that is blocked in this sandbox), so saving edits to the per-language key is untested.
- Docs: described above.

### Behavior to know
- Existing users' single saved buffer is moved to the language that loads first after the upgrade (their stored selected language).
- `extend-exclude` / pyright `exclude` list the three fixture files by name; a new fixture with intentionally odd code has to be added there.
