# Taint analysis guide, 2026-10-14

## Problem
Taint analysis (#48, #49) and its CLI, API and UI (#50) are documented only as sections of `docs/python-guide.md`, a guide about Python CFGs. Someone who wants to check a C or Java program, or write rules for their own framework, has to piece it together from reference-style sections whose examples are almost all Python.

## Plan
- A task-oriented `docs/taint-guide.md`, every example run for real:
  - quick start: `tree-climber taint` on a small Flask app, and how to read a finding;
  - rules for your own code: a JSON rule file with a parameter source, an attribute source, a keyword-argument sink and a sanitizer, run with `--rules`;
  - C (argv, `getenv`, format strings) and Java (servlet parameters into SQL) with the built-in rules;
  - `--json` for scripts and CI, drawing a finding;
  - the Python API (`analyze_source`, rules in Python, `Finding` fields), the precision options (`implicit_flows`, `field_sensitive`, Python API only);
  - why a finding is missing or unexpected: the approximations, with what to do about each.
- The reference sections in the Python guide stay; they and the README link to the new guide.
- `test/taint/test_taint_guide.py` runs every example and checks that the guide shows each program and its output verbatim, so the guide cannot drift from the code.

## Results
Executive summary: `docs/taint-guide.md` walks through taint analysis in seven sections: a first run on a Flask app and how to read a finding; a JSON rule file for Django and AWS Lambda code (attribute, parameter and keyword-argument rules, a sanitizer); C (argv into `syslog`, `getenv` into `printf`) and Java (a servlet parameter into SQL through a helper method); `--json` with `jq`, failing CI on findings, and drawing a finding; the Python API with rules built in Python and `implicit_flows`; HTTP and the web UI (pointing to the Python guide); and what is missed or over-reported, with what to do about each. The README and the Python guide's taint section link to it.

- Every program, command and output is real. `test/taint/test_taint_guide.py` reads the guide itself: it saves each file the guide names, runs each command block in a temporary directory and compares it with the output block that follows it (stdout and stderr), and runs each Python block, comparing its output. 11 tests (the `jq` ones are skipped where `jq` is not installed).
- The guide is honest about misses: `logger.c` contains a real command injection (`snprintf` into a buffer, then `system`) that the analysis misses, and the guide says why.
- Drift checks: changing a node id in an output, a rule in `rules.json`, a printed value of the Python example, the `jq -e` flag, or `No findings` each fails the tests (5 of 5 caught). The first draft's outputs, written before running, were wrong in three places and the tests caught all three.
- Checks: ruff format and lint clean, pyright 0 errors, 1681 passed, 20 xfailed.
