# Faster taint source discovery (#85), 2026-10-18

## Problem
With data flow shared (#84), source discovery is now almost all of taint's time on ordinary files. On `Lib/test/test_typing.py`, with its data flow already solved, taint takes 0.17 s and `_origins` 0.164 s of it.

`_origins` runs once per rule. For each source it walks every node:
- for a call source, it runs `fnmatchcase` against every call site;
- for an attribute source, it decodes the node's cached bytes and runs the source's regex.

The three built-in Python rules share one source list, so all of this is done three times. The profile on `test_typing.py` shows 116k `re.Pattern.search` calls, 116k `bytes.decode` calls and 42k `fnmatchcase` calls. `Source.attribute_pattern()` also rebuilds its regex string on every call, both here and in each run's `attribute_regions`.

## Plan
In `taint/engine.py` and `taint/rules.py`:
- **Origins once per distinct source.** `_Program.origins(source)` finds and caches each source's origins. `_origins(program, rule)` concatenates them in the rule's source order, so origins, runs and findings keep their order.
- **Call sources by distinct callee text.** `_Program` indexes nodes by the text of each call site's callee, once. A call source matches its pattern against the distinct callee texts, not every site of every node, then takes their nodes in id order.
- **Attribute sources.**
  - The decoded text of each node is cached as a `str` next to the bytes.
  - Each source's longest literal part (for example `args` in `request.args`) is checked with a substring test before the regex runs, so most nodes are rejected without a regex.
  - `attribute_pattern()` comes from a cache keyed by the attribute.
- Parameter sources are unchanged; they only scan function entries.

Not here: sharing one propagation across rules or sources, which is #87.

## Tests
- Origins are found once per source: three rules with the same sources search each node once per source (a spy on the search).
- Origins keep the rule's source order and node order.
- Call sources: a pattern with `*` matches several callee texts; nodes with several matching sites appear once.
- Attribute sources:
  - a node with the literal but no match is not an origin, for example `request.argsx` or `myrequest.args`;
  - a `*` attribute with no literal part still matches;
  - text in strings and comments still doesn't count.
- The taint corpus, guide and engine tests are unchanged.

## Measure
Taint on a prepared graph for `test_typing.py`, `unicodeobject.c` and a Flask-style file, before and after. Also the stress runner's taint stages on CPython `Lib`.

## Results
Executive summary: taint source discovery is about 5× faster, and on ordinary files it was almost all of taint's time. With the data flow already solved, taint on `test_typing.py` takes 0.037 s instead of 0.167 s. Over CPython `Lib`, the stress runner's taint stages take 3.3 s and 3.7 s instead of 16.6 s and 17.1 s. Findings are unchanged on the taint corpus and in the test suite.

| Taint on a graph with solved data flow, best of 5 | master | this branch |
|---|---|---|
| `Lib/test/test_typing.py` | 0.167 s | **0.037 s** |
| `Objects/unicodeobject.c` | 0.013 s | 0.007 s |
| `Lib/http/server.py` | 0.018 s | 0.002 s |
| `Lib/subprocess.py` | 0.014 s | 0.001 s |

| Stress runner, CPython `Lib` (1,790 files, 3 workers, stage seconds summed) | master | this branch |
|---|---|---|
| taint | 16.6 s | **3.3 s** |
| taint-precise | 17.1 s | **3.7 s** |

The files in the taint corpus give the same number of findings before and after. They are too small to time.

- **Origins once per distinct source.** `_Program.origins(source)` caches them. `_origins(program, rule)` concatenates them in the rule's source order, so origins, runs and findings come in the same order as before. The three built-in Python rules share their sources, so each source is now found once instead of three times.
- **Call sources.** `_Program` indexes nodes by the callee text of their call sites, once. A call source then runs `fnmatchcase` on the distinct callee texts (1,245 in `test_typing.py`) instead of on every site of every node (42k).
- **Attribute sources.**
  - Each node's raw text is read once.
  - A substring test on the source's longest literal part (`Source.attribute_literal()`) rejects most nodes before the regex runs.
  - The decoded text is cached per node (`_Program.text`).
  - `attribute_pattern()` comes from an `lru_cache` keyed by the attribute.
- **Not here.** Sharing one propagation across sources and rules is #87.
- **Tests:**
  - rules that share sources find each source once;
  - origins follow the rule's sources, then node order, including where set order would differ;
  - a call pattern matches every callee once per node;
  - an attribute needs more than its literal (`myrequest.args`, `request.argsx`, a string, `args.request`);
  - an attribute of only wildcards checks every node;
  - the attribute literal and the pattern cache.
- **Mutation check:** 9 mutants. The first run caught 6. The new node-order test catches one survivor (dropping `sorted`, hidden because sets of small ints iterate in order). Two are equivalent:
  - dropping the literal prefilter only affects speed;
  - dropping the `lru_cache` leaves `re`'s own cache returning the same compiled pattern.
- **Checks:** ruff format and lint are clean, pyright reports 0 errors, and the suite gives 2,073 passed, 39 xfailed.
