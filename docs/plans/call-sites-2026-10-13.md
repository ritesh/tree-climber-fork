# Structured call sites in node metadata (2026-10-13)

Tracks issue #45, the first piece of the graph-queries and taint-tracking epic (#44). Taint tracking needs to know, for each call, what it was given and where its result went; `CFGNodeMetadata.function_calls` is only a list of names.

## Design

A new `call_sites: List[CallSite]` on `CFGNodeMetadata`, in the same order as `function_calls` (source order, outer call before inner). Additive: `function_calls` stays, and is now *derived* from the call sites, so the two cannot disagree. The types live in `cfg_types.py` and are language-agnostic; each language visitor fills them in.

```
CallSite
  callee:       Optional[str]   the name used for call linking; None for calls we cannot name
                                ((*fp)(x), f()(), s->cb(x) in C) -- unchanged from function_calls
  callee_text:  str             the whole callee expression: "os.system", "(*fp)", "f()"
  receiver:     Optional[str]   text of the object in obj.f(): "obj", "a.b"; None for plain calls
  arguments:    List[CallArgument]
  assigned_to:  List[str]       variables defined by assigning the call's result directly
  feeds:        Optional[CallFlow]  the enclosing call this call's result flows into
  span:         start/end byte and (row, column)

CallArgument
  text:     source text of the argument expression
  uses:     variables the argument reads
  keyword:  Optional[str]       name in f(key=value)
  kind:     "positional" | "keyword" | "star" | "double_star"     (*args, **kwargs; Python only)

CallFlow
  call:      int                 index of the enclosing call within the same node's call_sites
  role:      "argument" | "receiver" | "callee"
  position:  Optional[int]       argument index, for role "argument"
```

### Decisions
1. **Every call expression gets a site, named or not.** `function_calls` keeps only the named ones, exactly as before, so call linking and every existing graph is unchanged. A taint sink such as `s->cb(x)` or `(*fp)(x)` is still a call site even though linking cannot resolve it.
2. **`assigned_to` means the call *is* the right-hand side** (through parentheses, `await` and casts): `x = f()`, `x: T = f()`, `a, b = f()`, `x = y = f()`, `x += f()`, `T x = f();`, `with f() as h`, `(x := f())`. In `cmd = "ls " + input()` the call is an operand, not the whole value, so `assigned_to` is empty and the node's definitions and uses still carry that flow. Assigned names are the same names the node defines for those targets (weak updates included).
3. **`feeds` links nested calls.** `f(g(x))`: `g` feeds `f` as argument 0. `a.b(c).d()`: `b` feeds `d` as receiver. A call found anywhere inside an argument expression feeds that argument (`f(1 + g(x))`), but the link stops at a `lambda`, since the lambda's result, not `g`'s, is what the argument receives.
4. **Argument `uses`** are what the language's `get_uses` reports for the argument expression, so the same conventions apply (a called name inside an argument counts as a use in Python; the loop variables of a comprehension argument do not).
5. **Decorators** are calls recorded on the definition statement (as `function_calls` already did). `@cache` gets a site with no arguments: its one argument, the decorated function, is implicit.
6. **Not recorded yet:** Java `new Foo(x)` (never in `function_calls`) and `return f()`; both belong to later issues (constructor calls and interprocedural returns, #46).

## Implementation
- `cfg_types.py`: the three dataclasses with `to_dict()`; `CFGNodeMetadata.call_sites` (default empty); `to_dict` adds a `call_sites` key.
- `visitor.py`: `get_call_sites` is the abstract method; `get_calls` becomes a concrete method deriving the names; `create_node` fills both.
- `cfg/call_sites.py`: shared helpers (spans, assigning flows to nested calls, computing `feeds` by byte ranges).
- Python in `python_calls.py` (`call_nodes` moves there; the visitor keeps it as a static method); C and Java in their visitors.
- Frontend: none; it ignores unknown metadata keys. `/parse` carries the new key through `to_dict`.

## Tests
Per language: names equal `function_calls` and vice versa; receivers; positional, keyword, `*args`, `**kwargs`; chained and nested calls with `feeds`; `assigned_to` for every form above; unnamed callees; spans. A parity test checks that call sites reproduce the old `get_calls` output on every fixture file and on CPython's standard library. Mutation-checked.

## Results

Executive summary: every call in a node is now described by a `CallSite` (name, whole callee text, receiver, arguments with the variables they read, direct assignment targets, the enclosing call it feeds, and a source span) for Python, C and Java, available as `node.metadata.call_sites` and in `/parse` node metadata. Nothing existing changed. `ruff format --check`, `ruff check`, `pyright`, `pytest` pass (946 passed, 20 strict xfails; was 828).

- **No change to existing output**: `function_calls` is derived from the sites, and on 1,094 files (the installed Python 3.12 standard library, plus every C and Java fixture) the `function_calls` of all 208,293 nodes are identical to what master produced before the change.
- **Tests**: `test/test_call_sites.py` (109) for all three languages: callee, callee text and receiver; every argument kind; every `assigned_to` form and the cases that must not count; `feeds` for arguments, receivers and callees, through keyword arguments, comprehensions and lambdas; definition-time calls and decorators; spans (bytes, not characters); serialization; and a check on every fixture file that names, order and `feeds` indexes are consistent. Deep-nesting tests (#55) gained two shapes and now also assert the sites of a 1,500-call chain.
- **Mutation-checked** with 48 deliberate bugs across the new code. All fail tests except: a call being the left side of an assignment and the role order of receiver versus argument (equivalent: neither can happen, as the regions never overlap), and two cache bookkeeping lines (redundant with each other; one is removed). Three real gaps were found and closed: C and Java comments between arguments, and nothing proving the uses cache is used (a visit-count test now does).
- **Performance**: computing each argument's uses naively walks nested calls once per enclosing call; 600 nested calls took 9.3 s. Argument uses are now computed innermost first and reused (`collect_uses` with a cache), so 1,500 nested calls take 1 s. The cached results are the same as uncached ones for all 928,539 call arguments in the standard library and CPython's `Lib/test`, and in unit tests with comprehensions and lambdas.
- Found, not fixed: a comment right after a C label crashes the builder (#58); that is why `real_world_patterns.c` is skipped in the fixture check.

### Behavior to know
- C and Java compute argument uses per argument and so remain quadratic in call nesting depth; not a concern at realistic depth.
- Java `new Foo(x)` is not a call site, as it was never in `function_calls`. `return f()` is not recorded either. Both belong with interprocedural flow (#46). Java `assigned_to` covers plain names only, like `get_definitions`; it should follow #32.
- The call-site types are in `cfg_types.py`; the shared linking helpers are in `cfg/call_sites.py`. `/parse` carries the new `call_sites` key; the frontend ignores unknown metadata keys.
