# Bump GitHub Actions off Node 20, 2026-10-15

## Problem
The first `Stress` run warned that `actions/checkout@v4`, `actions/setup-python@v5`, `actions/upload-artifact@v4` and `astral-sh/setup-uv@v4` target Node 20, which GitHub has deprecated (they are forced onto Node 24 for now).

## Plan
Move both workflows to the current majors, which run on Node 24: `checkout@v7`, `setup-python@v7`, `upload-artifact@v7`, `setup-uv@v7`. `oven-sh/setup-bun@v2` already runs on Node 24 and stays. Check each major's breaking changes against the inputs we use, then run CI and a dispatched `Stress` run on the branch.

## Results
Executive summary: all four actions bumped in `ci.yml` and `stress.yml`, with no input changes.
- `checkout` v5–v7: Node 24, credentials stored in a separate file, ESM internals, fork PRs blocked for `pull_request_target`/`workflow_run` (neither is used). The inputs we use (`repository`, `ref`, `path`, `sparse-checkout`, `persist-credentials`) are unchanged.
- `setup-python` v6: Node 24 (runner 2.327.1 or later); v7: ESM internals only.
- `upload-artifact` v7: a new `archive` input, default `true` (zipped, as before).
- `setup-uv` v5–v7: `version: "latest"` is still accepted (checked in the v7 bundle).
