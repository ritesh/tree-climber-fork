# Web API speed (#83), 2026-10-17

## Problem
On `Lib/test/test_typing.py` (348 KB, 7,735 CFG nodes), `/parse` takes 4.7 s and returns 28 MB, of which the AST is 26 MB. `/taint` takes 3.2 s. Three things make the editor slow on large files:
1. `/parse`, `/taint` and `/query` are `async def` but do only synchronous, CPU-bound work, so each request blocks the event loop. While one runs, every other request waits, `/health` included.
2. The AST is in every `/parse` response, but the frontend never reads it: it keeps `result.ast` and nothing uses it. Its 1.6 s `ast_to_json` and its 26 MB are wasted on every keystroke.
3. The editor calls `/parse` and `/taint` on every keystroke. Stale responses are dropped in the browser, but the server still computes every one of them.

Sending `text` only for leaf nodes, as #83 suggested, would save only 10% (26.0 MB to 23.3 MB): the size comes from the number of nodes and their fields, not from the repeated text. It would also change the AST for clients that read it, so it is not done here.

## Plan
- **Thread pool.** Make the three endpoints plain `def`, so FastAPI runs them in its thread pool and the event loop stays free. The work is still limited by the GIL, but `/health` and the other requests are no longer queued behind it.
- **`include_ast`** on `/parse`, default `true` so existing clients are unchanged. When `false`, the response has no AST and `ast_to_json` is not run. The frontend sends `false`.
- **Frontend:**
  - debounce analysis 300 ms after the last edit;
  - abort the previous `/parse` and `/taint` requests with an `AbortController` when a newer edit arrives.
- Not here: a cache shared between `/parse`, `/taint` and `/query`. That is the shared data flow of #84.

## Tests
- The endpoints are not coroutine functions; the existing API tests call them directly.
- `/parse` with `include_ast=false` returns the CFG and DFG and no AST, and does not call `ast_to_json`. The default still returns the AST.
- The frontend builds (`bun run build`, including `tsc`).

## Measure
`/parse` time and response size on `test_typing.py`, with and without the AST. Also `/health` latency while a `/parse` of that file runs, on a real uvicorn server, before and after.

## Results
Executive summary: the editor's `/parse` on `test_typing.py` now takes 3.1 s and returns 4.7 MB, against 8.0 s and 28 MB. While it runs, `/health` answers within 0.5 s instead of waiting 7.8 s. The three analysis endpoints run in FastAPI's thread pool. `/parse` takes `include_ast` (default `true`), and the frontend, which never read the AST, sends `false`. The editor now waits 300 ms after the last edit before it analyses, and aborts the requests of older edits.

Measured on a real uvicorn server with `Lib/test/test_typing.py` (348 KB, 7,735 CFG nodes):

| | master | this branch |
|---|---|---|
| `/parse`, AST included | 8.0 s, 28.1 MB | 8.2 s, 28.7 MB |
| `/parse`, `include_ast: false` (what the editor sends) | 8.3 s, 28.1 MB (flag ignored) | **3.1 s, 4.7 MB** |
| Worst `/health` latency during `/parse` with the AST | 6.9 s | 2.1 s |
| Worst `/health` latency during `/parse` without the AST | 7.8 s | **0.5 s** |

- **What remains blocking.** With the AST, `/health` can still wait about 2 s: FastAPI encodes the 28 MB response on the event loop after the endpoint returns. Clients that need the AST of a large file pay that cost; the editor no longer does.
- **Leaf-only AST text is not done.** It saves 10% (26.0 MB to 23.3 MB) and would change the AST for clients that read it.
- **Request models.** A new base, `SourceRequest` (source and language), is shared by `ParseRequest`, `TaintRequest` and `QueryRequest`. Only `/parse` takes `include_ast`.
- **Frontend.**
  - `updateGraph` debounces by 300 ms.
  - Each analysis has an `AbortController`, which a newer edit aborts.
  - The unused `ast` field and its types are removed from `GraphData`.
  - `bun run build` passes. `bun run lint` reports the same 25 problems as master and none new.
- **Tests.**
  - The endpoints are plain functions.
  - `include_ast: false` skips `ast_to_json` and still returns the CFG and DFG; the AST is included by default.
  - Only `/parse` takes the flag.
  - The tests that awaited the endpoints now call them directly.
- **Mutation check:** 7 mutants, all caught.
- **Checks:** ruff format and lint are clean, pyright reports 0 errors, and the suite gives 1,933 passed, 39 xfailed.
- **Not done here.** A cache shared between `/parse`, `/taint` and `/query` belongs to the shared data flow of #84.
