# Make the CLI `--show` flag do something (2026-10-12)

Found while writing the Python guide (#38).

## Problem

`--show` ("Display visualizations interactively") defaults to `True` and is a plain flag, so it cannot be turned off, and nothing reads it: `AnalysisOptions.show` is passed along but never used. The flag is a no-op that looks like it controls something.

## Decision

Make it real and opt-in. `--show` opens each saved image with the system's default viewer (`typer.launch`, which is Click's `launch`) after the analysis. The default becomes `False`, which matches what actually happens today, so existing invocations (and headless runs) behave the same. If the viewer cannot be launched (headless machine, no viewer), print a warning and still exit 0, since the images were saved.

## Changes

- `__main__.py`: default `show` to `False`.
- `commands.py`: collect the saved paths, and after the visualizations call `typer.launch` on each when `options.show`.
- Tests: `--show` launches every saved image (launch patched), is off by default, and a failed launch warns without failing.

## Results

Executive summary: `--show` now opens the saved images and is off by default. `ruff format --check`, `ruff check`, `pyright`, `pytest` pass (466 passed, 20 xfailed; was 463).

- Behavior change: none for existing invocations, since the flag was a no-op and images were always saved.
- 3 new tests in `test/cli/test_cli.py`: off by default, opens every saved image (ast, cfg, dfg, cpg, in order), and a failed launch warns without failing.
- Mutation-checked with 4 deliberate bugs (default on, never launching, no warning, dropping the DFG path). The first run missed the last one because the test did not request `--draw-dfg`; I added it and all 4 are now caught.
- The Python guide's `--show` note is updated.
