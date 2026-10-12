# Add Python to the web UI language selector (2026-10-12)

Part of #12. Found while writing the Python guide (#38).

## Problem

`LanguageSelector.tsx` lists only C and Java, so the web UI cannot request Python even though `/parse` supports it.

## Change

Add `{ value: 'python', label: 'Python' }` to the selector. The value is both the API language and the Monaco editor language id, and Monaco has a `python` id, so nothing else is needed.

## Out of scope

The editor holds a single stored code buffer shared by all languages (so switching language does not swap in language-specific sample code). That is existing behavior for Java and is left alone. Frontend lint (#29).

## Results

Executive summary: Python is selectable in the web UI and renders its CFG. `bun run build` (tsc + vite) succeeds.

- Verified in a real browser (Chromium via Playwright, outside the repo): the select lists `c`, `java`, `python`; choosing Python sends `/parse` with `language: "python"`, the response succeeds with 6 CFG nodes, and the graph renders ENTRY, `t = 0`, the `for x in xs` loop header, `t = t + x`, `return t`, EXIT with dashed def-use edges (screenshot checked).
- The Monaco editor pane stayed on "Loading..." in the sandbox because the editor library loads from a CDN that is blocked here; this is unrelated to the change, and the stored code was injected through `localStorage` instead. Typing in the editor was therefore not tested.
- README and the Python guide no longer say the UI lacks Python.
