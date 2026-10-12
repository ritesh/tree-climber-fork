# Single language registry (2026-10-12)

Tracks GitHub issue #4, a prerequisite for Python support (#1).

## Problem

Adding a language means editing unrelated places that must agree:

| Place | What it holds |
|---|---|
| `cfg/builder.py:get_visitor` | name -> visitor class (if/elif chain) |
| `cli/visualizers/constants.py` | `SUPPORTED_LANGUAGES`, `DEFAULT_LANGUAGE`, an unused `LANGUAGE_EXTENSIONS` |
| `cli/source.py:get_language_hint` | a second, separate extension map |
| `viz/app.py` | `SUPPORTED_LANGUAGES`, `DEFAULT_LANGUAGE`, the `SupportedLanguage` enum, and a dead "unsupported language" 400 branch (the enum already yields a 422) |
| `viz/frontend/src/LanguageSelector.tsx` | value/label list |

`dataflow/main.py` hardcodes `CFGBuilder("java")`, but it is a `__main__` demo with a Java snippet, not a registration, so it stays.

## Design

New module `src/tree_climber/language_registry.py` (not under `cfg/languages/`, which holds the visitors):

- `LanguageSpec(name, display_name, extensions, visitor)` frozen dataclass. `name` is the registry key and, by convention, the tree-sitter grammar name (true for `c` and `java`, and for `python` later). `visitor` is a `"module:Class"` string imported lazily, preserving today's lazy imports.
- `LANGUAGES`: ordered mapping of name to spec; `SUPPORTED_LANGUAGES` and `DEFAULT_LANGUAGE` derive from it.
- `get_language(name)`, `create_visitor(name)`, `language_for_extension(suffix)`. Unsupported names raise `ValueError("Unsupported language: ...")` as today.

Consumers:
- `CFGBuilder` uses `create_visitor`.
- CLI constants re-export `SUPPORTED_LANGUAGES`/`DEFAULT_LANGUAGE` (public names unchanged); the unused `LANGUAGE_EXTENSIONS` is removed; `FileSource.get_language_hint` uses `language_for_extension`.
- API: `ParseRequest.language` becomes a `str` with a validator against the registry, and `json_schema_extra` keeps the enum values in the OpenAPI schema. Invalid values still produce a 422. The dead 400 branch is removed. This avoids a dynamically built `Enum`, which pyright cannot use as a type.
- Frontend keeps its own label list; that single label is the one manual step left, as the issue states.

## Tests

`test/test_language_registry.py`: registry contents and order, extension lookup (case-insensitive, unknown returns `None`), no extension claimed twice, `create_visitor` and unsupported-name errors, every registered language has a loadable grammar and visitor, and CLI/API lists equal the registry. Plus an API test that an unsupported language is rejected.

## Out of scope

Reading the supported list from the API in the frontend; moving `dataflow/main.py`'s demo.

## Results

Executive summary: adding a language now takes one `LanguageSpec` entry in `language_registry.py`, a visitor class, and one label in `LanguageSelector.tsx`. CI-equivalent checks pass: `ruff format --check`, `ruff check`, `pyright`, `pytest` (137 passed, 20 strict xfails; was 111 passed).

- Added `src/tree_climber/language_registry.py`. `CFGBuilder`, CLI (language list, `--language` validation, extension auto-detection), and API (request validation, OpenAPI enum, root endpoint) read from it.
- Removed duplicates: the `get_visitor` if/elif chain, the CLI's second extension map in `source.py`, the unused `LANGUAGE_EXTENSIONS`, the `SupportedLanguage` enum, and the dead 400 branch in `/parse`.
- API behavior verified over real HTTP with uvicorn: an unsupported language is a 422 (as before, now with the message "Unsupported language: cobol"), omitted language defaults to `c`, Java parses, and the OpenAPI schema still lists `enum: [c, java]`.
- New `test/test_language_registry.py` checks every registered language's grammar, visitor and builder generically, plus extension lookup, uniqueness, and that CLI and API lists equal the registry.
- README and `docs/plans/extending-languages.md` describe the registry step.
- Left alone: `dataflow/main.py` (a `__main__` demo with a Java snippet) and the frontend language list (needs only a label).

### Noticed, not changed
- `main()` calls `typer.run(typer_main)`, so the `languages` and `version` subcommands defined with `@app.command()` are unreachable from the `tree-climber` entry point.
- Both visitors raise on an empty program ("Translation unit must have at least one entry node") instead of returning an empty CFG.
