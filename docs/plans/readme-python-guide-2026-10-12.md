# README tidy-up and Python guide (2026-10-12)

Documentation only; no code changes. Follows the Python support epic (#1): #5-#8 are merged, #9-#12 are still open.

## Problems in the current README

- The language list omits Python.
- The API section lists `POST /analyze/def-use` and `POST /analyze/reaching-definitions`, which do not exist. The app serves `GET /`, `GET /health`, and `POST /parse` (which returns the CFG, AST, and def-use edges together).
- Setup step 4 (`source .venv/bin/activate; uv pip install -e .`) is unnecessary: `uv sync` installs the project, and `uv run tree-climber` works.
- The "Documentation" section ends in a dangling colon.
- "Limitations" is one vague sentence from a single author's perspective.
- Nothing says how to check a change (`ruff`, `pyright`, `pytest`, frontend build) although CI runs all of them.

## Plan

1. Tidy `README.md`: add Python with an honest summary of what is and is not modeled, correct the API list, simplify setup, add a "Checks" section, give "Limitations" real content, and finish "Documentation" with links.
2. Add `docs/python-guide.md`: a hands-on guide for exercising each Python feature, with the CLI, a short text dump recipe (the CLI only draws images), and the web API.
3. Every command and every expected output in the guide is run before it is written down; outputs are pasted from real runs.

## Out of scope

Wiring Python into the web UI language selector (tracked in #12), and anything for `match`, classes, lambdas, comprehensions (#9-#11).

## Results

Executive summary: the README now matches the code, and `docs/python-guide.md` walks through 11 Python exercises with outputs pasted from real runs. Documentation only; `ruff format --check`, `ruff check`, `pyright`, and `pytest` (463 passed, 20 xfailed) are unchanged.

- README: Python added with its limits; the two non-existent `/analyze/*` endpoints replaced by the real `GET /`; setup step 4 dropped; "Limitations" and "Documentation" filled in; a "Checks" section lists what CI runs.
- Guide: CLI tour, a text-dump recipe (the CLI only draws images), 11 exercises (straight-line def-use, `if`/`elif`, loops with `else`, the `x = int(s)` exception case, caught `raise`, return through `finally`, `with`, calls, subscript writes, opaque constructs, plus break-it inputs), HTTP API, and the tests.
- Checking the guide against the code corrected three claims I had drafted from memory: `async def` is modeled as a normal function (not opaque), calls are linked by called name only (`obj.f()` links to any `f`), and the web UI's selector lists only C and Java.
- Found, not fixed: the CLI's `--show` option is on by default and has no way to turn it off (no `--no-show`); the web UI's language selector lacks Python (#12).
