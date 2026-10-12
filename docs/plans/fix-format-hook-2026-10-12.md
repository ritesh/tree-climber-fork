# Fix the Claude Code format hook (2026-10-12)

Tracks GitHub issue #26.

## Problem

`.claude/settings.json` ran a bare `ruff format` after every Edit, MultiEdit, and Write. Two defects:

1. It formatted the **whole working tree** (no file argument), not the edited file.
2. It used whichever `ruff` is on `PATH`. In the cloud sessions that was 0.16.8, while the project pins 0.12.1 (what `uv run ruff` and CI use).

Together these reformatted unrelated files after nearly every edit: Python code blocks inside `docs/plans/extending-languages.md` and `docs/plans/test-plans/01-c-cfg-comprehensive-testing.md`, and `reaching_definitions.py`, which the pinned ruff already considers formatted. Each PR since #13 needed those reverted by hand.

## Design

A small committed script, `.claude/hooks/format_python.py`, reads the hook's JSON from stdin and, for a `.py` file, runs `uv run --quiet ruff format <that file>`. Everything else is ignored. It never fails a tool call; CI's `ruff format --check` is the gate.

The hook command is `python3 "${CLAUDE_PROJECT_DIR:-.}"/.claude/hooks/format_python.py`. `CLAUDE_PROJECT_DIR` is the variable Claude Code documents for hook commands, but it is not present in the tool shell's environment in these sessions, so the default falls back to the working directory instead of failing with a path of `/.claude/...`.

## Verification limits (read this)

- **The live hook was not observed.** Claude Code loads hook configuration when a session starts, so this change cannot take effect inside the session that made it. The script and the configured command are tested directly; the first edit in a new session is the real check.
- `CLAUDE_PROJECT_DIR` could not be confirmed in a real hook environment; the fallback exists because of that.

## Tests

`test/hooks/test_format_python_hook.py` (18 tests): formats only the edited `.py` and leaves a sibling untouched; leaves Markdown code blocks alone; runs `uv run --quiet ruff format <path>` (checked with a stand-in `uv` that records its arguments, so a bare `ruff` from `PATH` fails the test); ignores non-Python files; tolerates garbage, empty, non-object, and path-less input and a file ruff cannot parse; the configured command works with `CLAUDE_PROJECT_DIR` set and unset; and no hook is a bare `ruff format`.

## Results

Executive summary: the hook formats only the edited Python file with the pinned ruff. CI-equivalent checks pass locally (`ruff format --check`, `ruff check`, `pyright`, `pytest`: 334 passed, 20 xfailed; was 316).

- 18 new tests; mutation-checked with 7 deliberate bugs (bare `ruff` from `PATH`, formatting the whole tree, no `.py` check, propagating ruff's exit code, unhandled non-object JSON, unguarded non-string path, and the command without the `${...:-.}` default), each applied and each caught.
