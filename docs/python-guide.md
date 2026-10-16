# Exercising Python support

A hands-on tour of what Tree Climber does with Python. Every command and every output below was produced by running it against this repository. All commands run from the repository root after `uv sync`.

## What is modeled

| Area | Status |
| --- | --- |
| Module-level code, plain `def` functions, `return` | Modeled |
| `if` / `elif` / `else`, conditional expressions | Modeled (a conditional expression stays inside its statement) |
| `while`, `for`, `async for`, `break`, `continue`, loop `else` | Modeled |
| `try` / `except` / `except*` / `else` / `finally`, `raise` | Modeled |
| `with` / `async with` | Modeled (exception suppression by `__exit__` is not) |
| Calls between functions in the same file | Linked, including calls to a function defined later |
| Def-use chains and reaching definitions | Modeled |
| `async def`, `async for`, `async with` | Modeled like their sync forms |
| `match` / `case` | Modeled: one test per case, captures, guards, no fall-through |
| Nested functions, classes and methods, decorators | Modeled: every function and method is its own subgraph, and the definition is one statement in the enclosing flow |
| Lambdas | Stay inside their statement (by design) |
| Comprehensions, generator expressions | Stay inside their statement; their own variables are local to them |
| `yield`, `yield from`, `await` | Stay inside their statement and do not end the function |
| Closures, `global` / `nonlocal` | Each function's def-use chains stay separate; `analyze_interprocedural` connects them (see [Data flow between functions](#data-flow-between-functions)) |
| Taint analysis | `tree_climber.taint`: sources, sinks with argument positions, call-site sanitizers, across calls (see [Taint analysis](#taint-analysis)) |

Python is available from the CLI, the HTTP API, and the web UI (pick it in the language selector; the editor keeps whatever code was in it, so paste Python in).

## 1. See a graph with the CLI

Save a file:

```python
# classify.py
def classify(items):
    total = 0
    for item in items:
        if item < 0:
            continue
        total = total + item
    return total
```

```bash
uv run tree-climber classify.py --draw-cfg --draw-dfg -o out
```

This writes `out/classify.py_cfg.png` (CFG with dashed red def-use edges) and `out/classify.py_dfg.png`. Look for:

- a green entry box and a pink exit box named `classify`;
- the `for item in items` diamond with `true` (next item) and `false` (exhausted) edges;
- `continue` going back to the `for` diamond, skipping `total = total + item`;
- red edges `total = 0` to `total = total + item` and `return total`, and a self-edge on `total = total + item` (the loop-carried dependency).

`--draw-ast` and `--draw-cpg` (add `-L bigraph` for the alternate layout) work too. Code can come from stdin: `cat classify.py | uv run tree-climber - -l python --draw-cfg`.

Add `--show` to open the saved images in your default image viewer; without it the images are only saved.

## 2. Dump the graph as text

The CLI draws images, and answers a few questions as text (`tree-climber taint` and `tree-climber query`, see [Tracing user input](#tracing-user-input)). To compare against expected edges, paste this into a file such as `dump.py`. It prints CFG edges and def-use chains for Python read from stdin.

```python
import sys

from tree_climber.cfg.builder import CFGBuilder
from tree_climber.dataflow.analyses.def_use import DefUseSolver
from tree_climber.dataflow.analyses.reaching_definitions import (
    ReachingDefinitionsProblem,
)
from tree_climber.dataflow.solver import RoundRobinSolver

builder = CFGBuilder("python")
builder.setup_parser()
cfg = builder.build_cfg(sys.stdin.read())


def name(node_id):
    node = cfg.nodes[node_id]
    kind = node.node_type.name
    text = node.source_text.splitlines()[0] if node.source_text else ""
    return f"{kind}:{text}" if kind in ("ENTRY", "EXIT") else text


print("CFG edges")
for node in cfg.nodes.values():
    for succ in node.successors:
        label = node.edge_labels.get(succ)
        print(f"  {name(node.id)} -> {name(succ)}" + (f"  [{label}]" if label else ""))

reaching = RoundRobinSolver().solve(cfg, ReachingDefinitionsProblem())
chains = DefUseSolver().solve(cfg, reaching).chains
print("Def-use chains")
for var, var_chains in chains.items():
    for chain in var_chains:
        uses = ", ".join(name(u) for u in chain.uses) or "(unused)"
        print(f"  {var}: {name(chain.definition)} => {uses}")
```

Run an exercise with `uv run python dump.py < snippet.py`. Edge order may differ from what is shown below; compare as sets. Edges without a label are ordinary flow.

## 3. Exercises

Each exercise gives a snippet, the output, and what to check.

### Straight-line code and def-use

```python
a = 1
b = a + 1
a = 5
print(a, b)
```

```
CFG edges
  ENTRY:<module> -> a = 1
  a = 1 -> b = a + 1
  b = a + 1 -> a = 5
  a = 5 -> print(a, b)
  print(a, b) -> EXIT:<module>
Def-use chains
  a: a = 1 => b = a + 1
  a: a = 5 => print(a, b)
  b: b = a + 1 => print(a, b)
```

Check: top-level code gets a `<module>` entry and exit. `a = 5` kills the first definition, so `print` depends only on the second `a`.

### if / elif / else

```python
def sign(n):
    if n < 0:
        s = -1
    elif n == 0:
        s = 0
    else:
        s = 1
    return s
```

```
CFG edges
  ENTRY:sign -> n < 0
  n < 0 -> s = -1  [true]
  n < 0 -> n == 0  [false]
  s = -1 -> return s
  n == 0 -> s = 0  [true]
  n == 0 -> s = 1  [false]
  s = 0 -> return s
  s = 1 -> return s
  return s -> EXIT:sign
Def-use chains
  n: ENTRY:sign => n < 0, n == 0
  s: s = 1 => return s
  s: s = 0 => return s
  s: s = -1 => return s
```

Check: each `elif` is its own condition node chained by `false` edges, and all three branches meet at `return s`. Parameters are defined at the function entry.

### Loops: break, continue, else

```python
def find(items, target):
    for item in items:
        if item == target:
            break
    else:
        return -1
    return item
```

```
CFG edges
  ENTRY:find -> for item in items
  for item in items -> item == target  [true]
  for item in items -> return -1  [false]
  item == target -> for item in items  [false]
  item == target -> break  [true]
  break -> return item
  return -1 -> EXIT:find
  return item -> EXIT:find
Def-use chains
  items: ENTRY:find => for item in items
  item: for item in items => item == target, return item
  target: ENTRY:find => item == target
```

Check: the loop's `false` edge goes to the `else` block, while `break` jumps past it to `return item`. `while ... else` behaves the same; a `break` inside a loop's `else` targets the enclosing loop.

### try / except: the exception edge leaves from before the statement

```python
x = 0
try:
    x = int(s)
except ValueError:
    print(x)
```

```
CFG edges
  ENTRY:<module> -> x = 0
  x = 0 -> x = int(s)
  x = 0 -> except ValueError  [exception]
  x = int(s) -> EXIT:<module>
  except ValueError -> EXIT:<module>  [false]
  except ValueError -> print(x)  [true]
  print(x) -> EXIT:<module>
Def-use chains
  x: x = 0 => print(x)
```

Check: the handler is reached from `x = 0`, not from `x = int(s)`, because the assignment never completed when `int(s)` raised. So `print(x)` depends on `x = 0` only. This is the most important property of the exception model. The `except ValueError` node is a handler header: `true` enters the handler, `false` propagates outward (here, to the module exit).

### raise caught by a handler

```python
def check(n):
    try:
        if n < 0:
            raise ValueError(n)
    except ValueError as err:
        return err
    return n
```

```
CFG edges
  ENTRY:check -> n < 0
  ENTRY:check -> except ValueError as err  [exception]
  n < 0 -> return n  [false]
  n < 0 -> raise ValueError(n)  [true]
  raise ValueError(n) -> except ValueError as err  [exception]
  except ValueError as err -> return err  [true]
  except ValueError as err -> EXIT:check  [false]
  return err -> EXIT:check
  return n -> EXIT:check
Def-use chains
  n: ENTRY:check => n < 0, raise ValueError(n), return n
  err: except ValueError as err => return err
```

Check: `raise` has an `exception` edge from itself to the handler; the `as err` name is defined by the handler header.

### return through finally

```python
def f(path):
    try:
        data = read(path)
        return data
    finally:
        close(path)
```

```
CFG edges
  ENTRY:f -> data = read(path)
  ENTRY:f -> close(path)  [exception]
  data = read(path) -> return data
  data = read(path) -> close(path)  [exception]
  return data -> close(path)
  close(path) -> EXIT:f  [return]
Def-use chains
  path: ENTRY:f => data = read(path), close(path)
  data: data = read(path) => return data
```

Check: `return data` goes through `close(path)` before the exit, and there is exactly one `close(path)` node, shared by the normal path, exceptions, and the return. Because that node serves every path, its exit edge carries one label (`return`) even though an exception can also leave through it. This is a documented simplification.

### with

```python
def g(path):
    with open(path) as fh:
        text = fh.read()
    return text
```

```
CFG edges
  ENTRY:g -> with open(path) as fh
  with open(path) as fh -> __exit__  [exception]
  with open(path) as fh -> text = fh.read()
  __exit__ -> EXIT:g  [exception]
  __exit__ -> return text
  text = fh.read() -> __exit__
  return text -> EXIT:g
Def-use chains
  path: ENTRY:g => with open(path) as fh
  fh: with open(path) as fh => text = fh.read()
  text: text = fh.read() => return text
```

Check: a synthetic `__exit__` node runs on normal completion and on exceptions, and `as fh` is a definition.

### Calls between functions

```python
def main():
    return helper(1)

def helper(n):
    return n + 1
```

```
CFG edges
  ENTRY:main -> return helper(1)
  return helper(1) -> EXIT:main
  return helper(1) -> ENTRY:helper  [function_call]
  ENTRY:helper -> return n + 1
  EXIT:helper -> return helper(1)  [function_return]
  return n + 1 -> EXIT:helper
Def-use chains
  n: ENTRY:helper => return n + 1
```

Check: the call node gets a `function_call` edge into `helper` and `helper`'s exit returns to it, even though `helper` is defined after `main`. Calls are matched by the called name only: `obj.f()` is linked to every function named `f`, and a later `f = 1` does not unlink it. Methods are matched the same way, so `self.step()` links to every method named `step`, in any class.

### Writes through subscripts and attributes

```python
items = []
items[0] = 1
print(items)
```

```
CFG edges
  ENTRY:<module> -> items = []
  items = [] -> items[0] = 1
  items[0] = 1 -> print(items)
  print(items) -> EXIT:<module>
Def-use chains
  items: items = [] => items[0] = 1
  items: items[0] = 1 => print(items)
```

Check: `items[0] = 1` both uses and defines `items` (a weak update), so the original definition still flows through it. The dataflow framework supports only strong updates, so this convention keeps earlier definitions alive. Attribute writes (`obj.f = v`) behave the same, and so does a call to a method that changes its receiver: `items.append(v)` defines `items` (and `self.items.append(v)` defines `self`). The methods are `append`, `extend`, `insert`, `add`, `update`, `setdefault`, `appendleft` and `extendleft` (in Java: `add`, `addAll`, `addFirst`, `addLast`, `put`, `putAll`, `putIfAbsent`, `append`, `insert`, `set`, `push`, `offer`, `offerFirst`, `offerLast`); other calls, and a receiver that is a call result (`get().append(v)`), define nothing.

### match

```python
def handle(cmd):
    match cmd:
        case [name, *args] if name:
            result = name
        case {"quit": code}:
            result = code
        case _:
            result = None
    return result
```

```
CFG edges
  ENTRY:handle -> match cmd
  match cmd -> case [name, *args]
  case [name, *args] -> case {"quit": code}  [false]
  case [name, *args] -> capture name, args  [true]
  capture name, args -> if name
  if name -> case {"quit": code}  [false]
  if name -> result = name  [true]
  result = name -> return result
  case {"quit": code} -> capture code  [true]
  case {"quit": code} -> case _  [false]
  capture code -> result = code
  result = code -> return result
  case _ -> result = None  [true]
  result = None -> return result
  return result -> EXIT:handle
Def-use chains
  cmd: ENTRY:handle => match cmd, capture name, args, capture code
  name: capture name, args => if name, result = name
  code: capture code => result = code
  result: result = code => return result
  result: result = None => return result
  result: result = name => return result
```

Check:
- the subject is evaluated once, by the `match cmd` node, and the cases are tried in order through `false` edges;
- a pattern that binds names gets a `capture` node on its `true` edge, so a failed match does not redefine them. The capture reads the subject, so the names it binds depend on it: here it uses `cmd`. When the subject is an expression (`match command.split():`), the `match` node defines a synthetic local, `<match subject>`, and each capture uses that instead, so the subject's calls are not repeated;
- a guard is its own `if` node, and its `false` edge also tries the next case (the names stay bound);
- `case _` is irrefutable, so it has no `false` edge. Without it, the last case's `false` edge would skip to the code after the `match`;
- nothing falls through from one body to the next, and `break`/`continue` in a case target the enclosing loop.

### Nested functions, classes, and decorators

```python
@cache
def total(xs):
    def add(a, b=0):
        return a + b
    return add(len(xs))


class Account:
    def __init__(self, owner):
        self.owner = owner

    def report(self):
        return self.summary()

    def summary(self):
        return self.owner


acct = Account("ann")
acct.report()
```

```
CFG edges
  ENTRY:<module> -> @cache
  @cache -> class Account
  ENTRY:total -> def add(a, b=0)
  def add(a, b=0) -> return add(len(xs))
  ENTRY:add -> return a + b
  EXIT:add -> return add(len(xs))  [function_return]
  return a + b -> EXIT:add
  return add(len(xs)) -> EXIT:total
  return add(len(xs)) -> ENTRY:add  [function_call]
  class Account -> acct = Account("ann")
  ENTRY:Account.__init__ -> self.owner = owner
  EXIT:Account.__init__ -> acct = Account("ann")  [function_return]
  self.owner = owner -> EXIT:Account.__init__
  ENTRY:Account.report -> return self.summary()
  EXIT:Account.report -> acct.report()  [function_return]
  return self.summary() -> ENTRY:Account.summary  [function_call]
  return self.summary() -> EXIT:Account.report
  ENTRY:Account.summary -> return self.owner
  EXIT:Account.summary -> return self.summary()  [function_return]
  return self.owner -> EXIT:Account.summary
  acct = Account("ann") -> ENTRY:Account.__init__  [function_call]
  acct = Account("ann") -> acct.report()
  acct.report() -> EXIT:<module>
  acct.report() -> ENTRY:Account.report  [function_call]
Def-use chains
  a: ENTRY:add => return a + b
  b: ENTRY:add => return a + b
  add: def add(a, b=0) => return add(len(xs))
  xs: ENTRY:total => return add(len(xs))
  self: ENTRY:Account.__init__ => self.owner = owner
  self: ENTRY:Account.report => return self.summary()
  self: ENTRY:Account.summary => return self.owner
  owner: ENTRY:Account.__init__ => self.owner = owner
  Account: class Account => acct = Account("ann")
  acct: acct = Account("ann") => acct.report()
```

(The first node is really two lines, `@cache` and `def total(xs)`; the dump script prints the first line.)

Check:
- every function and method has its own `ENTRY`/`EXIT` pair, including `add`, which is nested in `total`; methods are named `Class.method`;
- where a definition appears in the enclosing flow it is one statement with the header as its text. It defines the name (`add` is used by `return add(...)`), and it runs decorators (`@cache` is a call), default values, and base classes. A decorated module-level `def` appears in the module flow because it runs code; a plain module-level `def` still does not;
- `class Account` is one statement; its methods are not part of the module flow and are reached only by calls;
- `Account("ann")` links to `Account.__init__` (a constructor call), and `self.summary()` links to `Account.summary`;
- nothing inside `add` can raise into, or `return` out of, `total`'s own flow: a nested function body is built in isolation.

Names bound in a class body are class attributes, so they are not defined as variables of the enclosing scope, and a class body's own control flow is not modeled (the class is one statement that runs its calls).

### Closures and global/nonlocal

Def-use chains do not cross function calls (reaching definitions deliberately ignore `function_call` and `function_return` edges, so a callee's locals cannot overwrite the caller's). The consequence: a nested function's read of an enclosing local, and a `global` or `nonlocal` write, are not connected to the definition in the other scope by the chains below. [Data flow between functions](#data-flow-between-functions) adds those connections as separate edges.

```python
def outer():
    count = 0
    def bump():
        nonlocal count
        count = count + 1
    bump()
    return count
```

```
Def-use chains
  bump: def bump() => bump()
  count: count = 0 => return count
```

Check: `return count` depends on `count = 0` only; the `count = count + 1` inside `bump` is not linked to either by the def-use chains. The interprocedural analysis does link them as free-variable flows.

### Still inline: lambdas, comprehensions, yield and await

```python
async def fetch_all(urls, session):
    sizes = [len(b) for b in bodies(urls)]
    async with session.get(urls[0]) as resp:
        text = await resp.text()
    words = {w for w in text.split() if w}
    return sizes, words


def numbers(limit):
    n = 0
    while n < limit:
        got = yield n
        n = n + (got or 1)
```

```
CFG edges
  ENTRY:fetch_all -> sizes = [len(b) for b in bodies(urls)]
  sizes = [len(b) for b in bodies(urls)] -> async with session.get(urls[0]) as resp
  async with session.get(urls[0]) as resp -> __aexit__  [exception]
  async with session.get(urls[0]) as resp -> text = await resp.text()
  __aexit__ -> EXIT:fetch_all  [exception]
  __aexit__ -> words = {w for w in text.split() if w}
  text = await resp.text() -> __aexit__
  words = {w for w in text.split() if w} -> return sizes, words
  return sizes, words -> EXIT:fetch_all
  ENTRY:numbers -> n = 0
  n = 0 -> n < limit
  n < limit -> EXIT:numbers  [false]
  n < limit -> got = yield n  [true]
  got = yield n -> n = n + (got or 1)
  n = n + (got or 1) -> n < limit
Def-use chains
  urls: ENTRY:fetch_all => sizes = [len(b) for b in bodies(urls)], async with session.get(urls[0]) as resp
  session: ENTRY:fetch_all => async with session.get(urls[0]) as resp
  resp: async with session.get(urls[0]) as resp => text = await resp.text()
  text: text = await resp.text() => words = {w for w in text.split() if w}
  sizes: sizes = [len(b) for b in bodies(urls)] => return sizes, words
  words: words = {w for w in text.split() if w} => return sizes, words
  n: n = 0 => n < limit, got = yield n, n = n + (got or 1)
  n: n = n + (got or 1) => n < limit, got = yield n, n = n + (got or 1)
  limit: ENTRY:numbers => n < limit
  got: got = yield n => n = n + (got or 1)
```

Check:
- none of the comprehensions (`[len(b) for b in ...]`, `{w for w in ...}`) or the `await` or `yield` has a graph of its own: each is part of its statement, which holds no further statements, so there is no control flow to show;
- comprehension variables are local: `b` and `w` are not definitions or uses of anything outside, and a variable of the same name outside is unaffected. Only the first iterable (`bodies(urls)`, `text.split()`) is evaluated in the enclosing scope. A walrus inside a comprehension binds in the enclosing scope, so `[y := f(x) for x in xs]` defines `y`;
- `got = yield n` defines `got` from the sent value, and `yield` does not end the function: the loop continues. A generator is one function subgraph; calling it is linked to its entry like any call, although the body really runs when it is iterated;
- `async with` ends in an `__aexit__` node (`__exit__` for a plain `with`), and `async for` is a loop header like `for`, with the same `else` handling;
- a lambda is the same: its calls (`helper` in `lambda v: helper(v)`) count as calls of the statement that contains it, and its parameter is not a use.

### Call sites: what each call was given and where its result goes

Every call in a node is described by a `CallSite` in `node.metadata.call_sites` (and in the `call_sites` key of `/parse` node metadata). `function_calls` is the list of their names.

```python
def handler(request):
    name = request.args.get("name", default=fallback())
    cmd = clean("ls " + name).strip()
    run(cmd, shell=True, *opts)
```

```
'name = request.args.get("name", default=fallback())'
  [0] callee='get' callee_text='request.args.get' receiver='request.args'
      args=[('positional', '"name"', []), ('keyword:default', 'fallback()', ['fallback'])]
      assigned_to=['name'] feeds=None
  [1] callee='fallback' callee_text='fallback' receiver=None
      args=[]
      assigned_to=[] feeds=(0, 'argument', 1)
'cmd = clean("ls " + name).strip()'
  [0] callee='strip' callee_text='clean("ls " + name).strip' receiver='clean("ls " + name)'
      args=[]
      assigned_to=['cmd'] feeds=None
  [1] callee='clean' callee_text='clean' receiver=None
      args=[('positional', '"ls " + name', ['name'])]
      assigned_to=[] feeds=(0, 'receiver', None)
'run(cmd, shell=True, *opts)'
  [0] callee='run' callee_text='run' receiver=None
      args=[('positional', 'cmd', ['cmd']), ('keyword:shell', 'True', []), ('star', 'opts', ['opts'])]
      assigned_to=[] feeds=None
```

Check:
- sites are in source order, an outer call before the calls inside it, and `feeds` points at an index in the same node's list: `fallback()` is argument 1 of the `get` call, and `clean(...)` is the receiver of `.strip()`;
- `callee` is the name used to link calls to functions (the final attribute for `obj.method()`), `callee_text` is the whole callee expression (`request.args.get`, which is what a sink or source rule would match), and `receiver` is the object it is called on;
- an argument carries its text, the variables it reads, and its kind (`positional`, `keyword`, `star` for `*args`, `double_star` for `**kwargs`);
- `assigned_to` is set only when the call is the whole right-hand side of the assignment (`x = f()`, `a, b = f()`, `x = y = f()`, `x += f()`, `with f() as h`, `(x := f())`); in `cmd = "ls " + input()` the call is just an operand, so `assigned_to` is empty and the node's definitions and uses carry that flow;
- a call without a usable name (`f()(x)`, `handlers[k](x)`) is still a site, with `callee=None`, and is left out of `function_calls`;
- the same structure exists for C and Java: `s->cb(x)` and `(*fp)(x)` in C are sites with no name; Java `new Foo(x)` is not a call site yet.

### Data flow between functions

`analyze_interprocedural(cfg)` (in `tree_climber.dataflow.interprocedural`) adds the flow that the solver deliberately does not follow. It returns three lists of edges between the existing def-use islands and changes nothing else:

- `argument_flows`: an argument of a call site flows into a parameter of a function it may call;
- `return_flows`: a `return` node flows into a call site that may call that function;
- `free_variable_flows`: a definition of a closure, `global` or `nonlocal` variable flows into a use of it in another function.

```python
LIMIT = 10

def outer():
    count = 0
    def bump():
        nonlocal count
        count = count + 1
    def peek():
        return count + LIMIT
    bump()
    return peek()
```

```
return    'return count + LIMIT' -> 'return peek()' site 0
free      LIMIT: 'LIMIT = 10' -> 'return count + LIMIT' (global)
free      count: 'count = 0' -> 'count = count + 1' (closure)
free      count: 'count = 0' -> 'return count + LIMIT' (closure)
free      count: 'count = count + 1' -> 'return count + LIMIT' (closure)
```

```python
class Runner:
    def __init__(self, shell):
        self.shell = shell

    def go(self, cmd, check=True):
        return run(cmd)

def run(cmd):
    return cmd

def read():
    return input()

def handler():
    y = read()
    Runner(True).go(y, check=False)
```

```
argument  'return run(cmd)' site 0 argument 0 -> run parameter cmd
argument  'Runner(True).go(y, check=False)' site 0 receiver -> go parameter self
argument  'Runner(True).go(y, check=False)' site 0 argument 0 -> go parameter cmd
argument  'Runner(True).go(y, check=False)' site 0 argument 1 -> go parameter check
argument  'Runner(True).go(y, check=False)' site 1 argument 0 -> Runner parameter shell
return    'return cmd' -> 'return run(cmd)' site 0
return    'return input()' -> 'y = read()' site 0
return    'return run(cmd)' -> 'Runner(True).go(y, check=False)' site 0
```

Check:
- endpoints are call sites (node id plus index into `call_sites`), not variables: to follow a value, combine these edges with the def-use chains in each function (`y = read()` receives the return of `read`; `y` is then used by the `.go(y, ...)` site, whose argument 0 reaches `go`'s parameter `cmd`, then `run`'s `cmd`, then back out through the returns);
- argument index -1 is the receiver, bound to `self`; for a constructor call (`Runner(True)`, registered as `Runner`) the arguments bind to `__init__` after `self`, and its return is not flowed to the call;
- arguments bind as Python binds them: positional by position, keywords by name, `*args` to every positional parameter from the current position on and to `*rest`, `**kwargs` to every named parameter not already bound and to `**rest`, unmatched extras to `*rest` / `**rest`;
- calls are resolved by name, as for the `function_call` edges: a call reaches every function with that name, so a name shared by two functions gives edges to both (a sound over-approximation);
- free variables are flow-insensitive: every definition in a scope reaches every use of it in another function, with no ordering between them (`count = count + 1` and `return count + LIMIT` above are both linked even though `bump()` may run first or never);
- scoping follows Python: locals shadow, `global` and `nonlocal` redirect, class bodies are not scopes, and a name that nothing declares locally is global; in C, any name not declared inside the function is global; Java free variables are not modeled, but Java arguments and returns are;
- `to_dict()` on the result gives the same lists as JSON-friendly dicts.
- for the query API, `CodeGraph.interprocedural_edges()` gives the same flows as `DataFlowEdge`s (see [Edges from other analyses](#edges-from-other-analyses)).

### Querying the graph

`tree_climber.query` answers questions about the graph without a hand-written traversal. Build a `CodeGraph` once, from source or from a `CFG` you already have (`CodeGraph.from_cfg(cfg)`); the same API works for C, Java and Python. The examples below use this program:

```python
def handler(request):
    name = request.args.get("name")
    cmd = build(name)
    if cmd:
        os.system(cmd)
    else:
        cmd = "true"
    return finish(cmd)


def build(text):
    return "ls " + text


def finish(value):
    return value
```

```python
from tree_climber.query import CALL_KINDS, CodeGraph, DataFlowEdge

graph = CodeGraph.from_source("python", SOURCE)  # SOURCE holds the program above
```

Lookups return `CFGNode`s sorted by id; anywhere a node is taken, its id works too.

```python
[n.source_text for n in graph.calling("system")]      # ['os.system(cmd)']
[n.source_text for n in graph.calling("os.system")]   # ['os.system(cmd)']
[n.source_text for n in graph.defining("cmd")]        # ['cmd = build(name)', 'cmd = "true"']
[n.source_text for n in graph.using("cmd")]           # ['cmd', 'os.system(cmd)', 'return finish(cmd)']
[n.source_text for n in graph.by_text("cmd =")]       # ['cmd = build(name)', 'cmd = "true"']
[n.source_text for n in graph.by_type("CONDITION")]   # ['cmd']
[n.source_text for n in graph.functions()]            # ['handler', 'build', 'finish']
graph.function_of(graph.calling("system")[0]).source_text   # 'handler'
[n.id for n in graph.function_nodes("build")]         # [9, 10, 11]
```

`calling` matches the callee name and the whole callee expression, and takes several names (any of them). `by_text` takes a substring, `exact=True`, or a compiled regex. A function is identified by its `ENTRY` node (`function_nodes` given any other node raises `ValueError`); `function_of` and `function_nodes` use the rule that a function is what is reachable from its entry without following call edges.

#### Flow queries

Edges are `flow` (no label), `true`, `false`, `exception`, `function_call` and `function_return`. `labels` keeps only those kinds, `exclude` drops them, and paths also take `avoid`, nodes a path may not pass through.

```python
cond = graph.by_type("CONDITION")[0]
[n.source_text for n in graph.successors(cond, labels=["true"])]    # ['os.system(cmd)']
[n.source_text for n in graph.successors(cond, labels=["false"])]   # ['cmd = "true"']

call = graph.calling("finish")[0]
[(n.source_text, graph.edge_kind(call, n)) for n in graph.successors(call)]
# [('handler', 'flow'), ('finish', 'function_call')]
[n.source_text for n in graph.successors(call, exclude=CALL_KINDS)]  # ['handler']

entry = graph.functions()[0]
len(graph.reachable(entry)), len(graph.reachable(entry, exclude=CALL_KINDS))   # (14, 8)
finish = graph.function_nodes("finish")[0]
graph.can_reach(entry, finish)                          # True
graph.can_reach(entry, finish, exclude=CALL_KINDS)      # False

print(graph.shortest_path(entry, graph.calling("system")[0]))
```

```
[0] ENTRY handler
  --> [2] name = request.args.get("name")
  --> [3] cmd = build(name)
  --> [4] cmd
  --true--> [6] os.system(cmd)
```

`paths(source, target)` lists the paths that visit no node twice, depth first with successors in id order, so a loop cannot make it run forever. It stops at `max_paths` (default 100) and never returns a path longer than `max_length` edges (default: no limit):

```python
done = graph.by_text("return finish(cmd)")[0]
for path in graph.paths(entry, done):
    print(path)
    print()
```

```
[0] ENTRY handler
  --> [2] name = request.args.get("name")
  --> [3] cmd = build(name)
  --> [4] cmd
  --true--> [6] os.system(cmd)
  --> [8] return finish(cmd)

[0] ENTRY handler
  --> [2] name = request.args.get("name")
  --> [3] cmd = build(name)
  --> [4] cmd
  --false--> [7] cmd = "true"
  --> [8] return finish(cmd)
```

`len(graph.paths(entry, done, max_paths=1))` is `1`, and `max_length=4` gives none because both paths have five edges (`max_length=5` gives both). When a call returns exactly `max_paths` paths there may be more.

#### Data-flow queries

`def_use(variable)` maps each definition node to the nodes using it, and `use_def(variable)` each use to the definitions that reach it. They are built on the same reaching-definitions solver and `DefUseSolver` / `UseDefSolver` as the rest of the framework.

```python
graph.def_use("cmd")   # {3: [4, 6, 8], 7: [8]}
graph.use_def("cmd")   # {4: [3], 6: [3], 8: [3, 7]}
```

Slices follow data dependences only (the `if cmd` test is a data use of `cmd`, but a node is not in a slice just because it decides whether another one runs). Both include the node itself; `variable=` starts from one variable of the node.

```python
sink = graph.calling("system")[0]
[n.source_text for n in graph.forward_slice(entry)]
# ['handler', 'name = request.args.get("name")', 'cmd = build(name)', 'cmd', 'os.system(cmd)', 'return finish(cmd)']
[n.source_text for n in graph.backward_slice(sink)]
# ['handler', 'name = request.args.get("name")', 'cmd = build(name)', 'os.system(cmd)']
```

`data_flow_path(source, target)` is the shortest chain of definitions and uses between two nodes; each step shows the variable carried. It returns `None` when the value of the source never reaches the target (here the `else` branch's `cmd` never reaches `os.system`):

```python
build_call = graph.calling("build")[0]
print(graph.data_flow_path(build_call, sink))
print(graph.data_flow_path(graph.by_text('cmd = "true"')[0], sink))
```

```
[3] cmd = build(name)
  --def_use cmd--> [6] os.system(cmd)
None
```

`data_flow_paths` lists them all, with the same `max_paths` / `max_length` bounds. Neither returns a path that comes back to its source node.

#### Control dependence

A node is control dependent on a branch when the edge the branch takes decides whether the node runs. `control_dependences(node)` lists the branches and edge labels a node depends on, `control_dependents(branch)` the nodes a branch decides, and `control=True` adds control dependence to a slice:

```python
system = graph.calling("os.system")[0]
[(n.source_text, label) for n, label in graph.control_dependences(system)]
# [('cmd', 'true')]
[n.source_text for n in graph.control_dependents(graph.by_text("cmd", exact=True)[0])]
# ['os.system(cmd)', 'cmd = "true"']
[n.source_text for n in graph.backward_slice(system)]
# ['handler', 'name = request.args.get("name")', 'cmd = build(name)', 'os.system(cmd)']
[n.source_text for n in graph.backward_slice(system, control=True)]
# ['handler', 'name = request.args.get("name")', 'cmd = build(name)', 'cmd', 'os.system(cmd)']
reset = graph.by_text('cmd = "true"')[0]
[n.source_text for n in graph.backward_slice(reset, control=True)]
# ['handler', 'name = request.args.get("name")', 'cmd = build(name)', 'cmd', 'cmd = "true"']
```

`cmd = "true"` reads nothing, so its data slice is itself; with `control=True` it gets the condition that decides it and everything the condition depends on. A forward slice with `control=True` adds what runs or not depending on a node in it.

Check:
- dependence comes from post-dominators per function (call and return edges are not part of a function's flow), so it follows the CFG's edges for every construct: `if`/`elif`, loops (a loop header depends on its own condition, or on the condition whose edge leads back to it), `match` (each case on the one before it), C and Java `switch` (labels are the case values; a fall-through case depends on every label that reaches it);
- an early `return` makes what follows depend on the condition that did not return;
- exceptions: the CFG sends the exception edge from the node before a statement that may raise, so inside a `try` a statement depends on its predecessor's normal edge (label `flow`), and what follows a `finally` depends on the `finally` (it may re-raise); labels say which edge, so these can be told apart from conditions;
- a node that cannot reach its function's exit (a loop that never ends) has no post-dominator; dependence inside such a loop is still computed, on its own condition.

#### Paths as data

Every path is a `Path` of `PathStep`s: the node, its type and text, the kind of the edge that arrives at it, and the variable a data-flow edge carries. Paths are frozen, hashable and compare by value, so tests can assert on them; `path.nodes`, `path.edges` and `path.texts` give the parts, `str(path)` is the terminal form above, and `path.to_dict()` is JSON-compatible:

```python
json.dumps(graph.data_flow_path(build_call, sink).to_dict())
# {"steps": [{"node": 3, "node_type": "STATEMENT", "text": "cmd = build(name)", "edge": null, "variable": null}, {"node": 6, "node_type": "STATEMENT", "text": "os.system(cmd)", "edge": "def_use", "variable": "cmd"}]}
```

`graph.to_networkx()` returns a `networkx.MultiDiGraph` with the control edges (`layer="control"`, `kind` as above); `data_flow=True` adds the data-flow edges (`layer="data"`, with `source_variable` and `target_variable`). Node attributes are `text`, `node_type`, `function`, `calls`, `definitions` and `uses`.

#### Edges from other analyses

Dataflow does not cross calls, so `forward_slice(name = ...)` stops at the call to `build`. An analysis that connects arguments to parameters and returns to call sites describes its flows as `DataFlowEdge(source, source_variable, target, target_variable, kind)` and passes them to the data-flow queries with `extra_edges=`. The edges are used for that call only; nothing is stored in the graph. Here they are written by hand:

```python
build_entry = [n for n in graph.functions() if n.source_text == "build"][0]
build_ret = graph.by_text('return "ls " + text')[0]
edges = [
    DataFlowEdge(build_call.id, "name", build_entry.id, "text", "argument"),
    DataFlowEdge(build_ret.id, "text", build_call.id, "cmd", "return"),
]
req = graph.by_text("name =")[0]
[n.source_text for n in graph.forward_slice(req)]
# ['name = request.args.get("name")', 'cmd = build(name)', 'cmd', 'os.system(cmd)', 'return finish(cmd)']
[n.source_text for n in graph.forward_slice(req, extra_edges=edges)]
# ['name = request.args.get("name")', 'cmd = build(name)', 'cmd', 'os.system(cmd)', 'return finish(cmd)', 'build', 'return "ls " + text']
print(graph.data_flow_path(req, build_ret, extra_edges=edges))
```

```
[2] name = request.args.get("name")
  --def_use name--> [3] cmd = build(name)
  --argument text--> [9] ENTRY build
  --def_use text--> [11] return "ls " + text
```

`graph.interprocedural_edges()` produces these edges from the interprocedural analysis (see [Data flow between functions](#data-flow-between-functions)), so they need not be written by hand. An argument flows from each variable it reads to the parameter (`argument`); a return flows from the whole `return` node to the variables the call is assigned to, or to a placeholder `<call k>` for call site `k` of the node when the result is not assigned (`return`); a closure or global flows from its definition to its use (`free_variable`):

```python
edges = graph.interprocedural_edges()
# [DataFlowEdge(3, 'name', 9, 'text', 'argument'),
#  DataFlowEdge(8, 'cmd', 12, 'value', 'argument'),
#  DataFlowEdge(11, '<return>', 3, 'cmd', 'return'),
#  DataFlowEdge(14, '<return>', 8, '<call 0>', 'return')]
print(graph.data_flow_path(req, graph.by_text("return value")[0], extra_edges=edges))
```

```
[2] name = request.args.get("name")
  --def_use name--> [3] cmd = build(name)
  --def_use cmd--> [8] return finish(cmd)
  --argument value--> [12] ENTRY finish
  --def_use value--> [14] return value
```

A nested call is an argument too: in `g(read())`, a return into `read()` flows on to `g`'s parameter from `<call 1>`. The receiver of `obj.m()` flows into `self` from the variables the receiver reads.

An edge leaves the facts named `source_variable` at the source node and arrives at `target_variable` at the target (a definition if the node defines it, a use if it uses it). A variable that the node neither defines nor uses, such as a name for "the return value", applies to the whole node; a node with no variables at all (`return 1`) gets one for the edge, so the edge is still followed and the node can start a path or a slice. Unknown node ids raise `KeyError`.

#### A taint tracker in a few lines

The prototype in the taint epic (#44) was 40 lines of traversal over `cfg.nodes` and def-use chains. With the query layer it is a path search that avoids the sanitizers (the full analysis, with call-site sanitizers and argument positions, is [Taint analysis](#taint-analysis)):

```python
SOURCES = {"input", "getenv"}
SINKS = {"system", "eval", "execute"}
SANITIZERS = {"escape", "quote"}

graph = CodeGraph.from_source("python", code)
sanitizers = graph.calling(*SANITIZERS)

for source in graph.calling(*SOURCES):
    for sink in graph.calling(*SINKS):
        path = graph.data_flow_path(source, sink, avoid=sanitizers)
        if path:
            print(" -> ".join(path.texts))
```

On

```python
def run(flag):
    data = input()
    safe = escape(data)
    system(safe)
    cmd = "ls " + data
    if flag:
        data = "constant"
    system(data)
    eval(cmd)
```

it prints

```
data = input() -> system(data)
data = input() -> cmd = "ls " + data -> eval(cmd)
```

`system(safe)` is blocked by `escape`; `system(data)` is found because the reassignment happens on one branch only; a reassignment on every path would kill the flow. `test/query/test_query_taint.py` keeps the original prototype next to this version and checks that they find the same source/sink pairs.

Check, and what is approximate:
- the data-flow model is statement-level, like the def-use chains: every variable a statement uses flows into every variable it defines (`cmd = build(name)` makes `cmd` depend on `build` as well as `name`). Extra edges are the exception: they follow the variable they name;
- flow queries follow call and return edges like any other edge, and a path need not return to the call site it entered from. Pass `exclude=CALL_KINDS` to stay inside one function. Calls are linked by name, so `obj.f()` reaches every function named `f`;
- slices and data-flow paths do not cross calls unless you pass `extra_edges` (`graph.interprocedural_edges()` for all calls in the file); they have no control dependence unless you pass `control=True` (see [Control dependence](#control-dependence));
- a weak update (`d["k"] = v`, `obj.f = v`, `items.append(v)`) defines and uses the root name, so a path continues through it, as in the def-use chains;
- `paths` and `data_flow_paths` are depth first, cut off at `max_paths`, and `shortest_path` breaks ties toward lower node ids; none of them knows whether a path is feasible.

### Taint analysis

`tree_climber.taint` is the analysis the query-layer tracker above sketches, at the level of call sites: a sanitizer cleans the value it returns, not the whole statement (`eval(escape(x))` and `cmd = "ls " + escape(x)` are clean), a sink watches particular arguments, sources can be calls, parameters or attributes, and taint follows calls into functions and back. It works for Python, C and Java. The [taint analysis guide](./taint-guide.md) walks through running it on examples in all three; this section is the reference.

```python
from tree_climber.taint import analyze_source, builtin_rules

APP = '''
import os
import shlex
from flask import request


def ping():
    host = request.args.get("host")
    run("ping -c 1 " + host)
    run("ping -c 1 " + shlex.quote(host))


def run(command):
    os.system(command)


def search(cursor):
    term = request.args["q"]
    cursor.execute("SELECT * FROM t WHERE name = ?", (term,))
    cursor.execute("SELECT * FROM t WHERE name = '" + term + "'")
'''
for finding in analyze_source("python", APP.lstrip(), builtin_rules("python")):
    print(finding)
```

```
python-command-injection: argument 0 of os.system
[7] host = request.args.get("host")
  --def_use host--> [8] run("ping -c 1 " + host)
  --argument command--> [10] ENTRY run
  --def_use command--> [12] os.system(command)

python-sql-injection: argument 0 of cursor.execute
[15] term = request.args["q"]
  --def_use term--> [17] cursor.execute("SELECT * FROM t WHERE name = '" + term + ...
```

The parameterized query is not reported: its second argument is not watched. `builtin_rules(language)` returns example rule sets (command injection, `eval`/`exec`, SQL text, and C format strings); they are starting points, not complete lists for any framework.

Rules can be written in Python (`Rule`, `Source`, `Sink`, `Sanitizer`), as a dict, or as JSON (`RuleSet.from_json`, `RuleSet.load(path)`; for YAML, parse it yourself and pass the dict to `RuleSet.from_dict`):

```json
{"rules": [{
  "id": "eval",
  "languages": ["python"],
  "sources": [{"call": "input"}, {"parameter": "expr", "function": "calc*"}],
  "sinks": [{"call": "eval", "arguments": [0]}],
  "sanitizers": [{"call": "ast.literal_eval"}]
}]}
```

- a call pattern is a glob matched against the whole callee: `eval` is a plain `eval(...)` call, `os.system` the function through its module, `*.execute` a method of any object;
- sources: `call` (the call's result), `parameter` (a name or position) of the functions matching `function`, or `attribute` (`request.args`, `request.*`; matched in the code, not in strings or comments, and not where the statement writes to it);
- sinks: `arguments` lists positional indexes and keyword names (`[0, "sql"]`); without it, every argument is watched; a `*args` argument counts as any position; the object a method is called on is not an argument;
- sanitizers: the call's result is clean, whatever it was given.

On

```python
import ast


def calculate(expr):
    return eval(expr)


x = input()
eval(ast.literal_eval(x))
eval("1 + 1", {"x": x})
```

the rule above reports one finding, from the parameter: `calculate -> return eval(expr)`. A finding has `rule`, `source` and `sink` node ids, `sink_call`, `argument` and `path` (a query `Path`), and `to_dict()` for JSON.

How taint moves:
- inside a statement, call results are worked out innermost first: a source call is tainted, a sanitizer is clean, a call to a function defined in the file is tainted when one of its `return`s is, and any other call passes on the taint of its arguments and receiver (`x.strip()`, `clean(x)`);
- a variable a call is assigned to takes the call's taint; other definitions take the statement's (a tainted variable read outside any call, or a tainted call that is not inside another); a weak update (`d["k"] = ...`, `x += ...`, `items.append(...)`) keeps the earlier taint;
- between statements, def-use chains (so a reassignment on every path kills the taint) and the flows of [Data flow between functions](#data-flow-between-functions): arguments into parameters, returns into callers, closures and globals;
- each source occurrence is followed on its own, so each finding has one source; a sink argument reached from one source by several paths is one finding, with the first path found.

Two options make the analysis more precise, at some cost to soundness or speed; both are off by default:

- `implicit_flows=True`: when a condition, loop header or `match`/`switch` reads a tainted value, what is defined or returned in the code it decides is tainted too, through nested branches (edge kind `control` in the path). `if x == "a": cmd = "safe"` taints `cmd`. Exceptions are not implicit flows, and a sink argument is not tainted by the branch around it (only definitions and returns are).
- `field_sensitive=True`: a write into a field or a constant key taints only that field (`.secret`, `["k"]`), reads of other fields stay clean, and earlier fields are kept across writes to others. A read of the whole value (`system(d)`, `e = d`) is tainted when any field is and gives a value tainted as a whole; a variable passed as-is to a function defined in the file (including `self` to a method) keeps its fields there. Keys that are not literals read or write the whole value, and only the first level is tracked (`self.items[0] = x` taints `self.items`).

```python
from tree_climber.taint import Rule, Sink, Source

rule = Rule("r", sources=[Source(call="input")], sinks=[Sink(call="system")])
code = '''
d = {}
d["k"] = input()
d["other"] = "safe"
system(d["other"])
system(d["k"])
'''
for finding in analyze_source("python", code.lstrip(), rule, field_sensitive=True):
    print(finding.path)
```

```
[3] d["k"] = input()
  --def_use d[k]--> [4] d["other"] = "safe"
  --def_use d[k]--> [6] system(d["k"])
```

Without the option, both `system` calls are reported.

Check, and what is approximate:
- over-approximations: unknown calls pass taint through; a container or object is one value unless `field_sensitive` (`d["k"] = tainted` taints `d`, `self.x = tainted` taints `self`, `items.append(tainted)` taints `items`); closures and globals are flow-insensitive; calls are resolved by name, and a function is analysed once for all its callers: with `def wrap(a): return a`, `t = wrap(input())` makes every `wrap(...)` result tainted, so `system(wrap("safe"))` is reported too;
- under-approximations: aliasing (two names for one object), output parameters (C's `fgets(buf, ...)` or `snprintf(cmd, ...)` do not taint `buf` or `cmd`), dynamic features (`getattr`, `exec` of strings), calls through function pointers, and branching on tainted data unless `implicit_flows`; Java writes into fields and arrays define nothing in the CFG (#32), so taint written there is lost with or without `field_sensitive`;
- attribute sources are matched as text in the statement, outside string literals and comments.

### Tracing user input

The same analysis runs from the command line, the HTTP API and the web UI. Save the program from [Taint analysis](#taint-analysis) (the text of `APP`) as `app.py`:

```bash
uv run tree-climber taint app.py
```

```
Analyzing: app.py
1. python-command-injection: argument 0 of os.system (line 13)
   line 7    [7] host = request.args.get("host")
   line 8      --def_use host--> [8] run("ping -c 1 " + host)
   line 12     --argument command--> [10] ENTRY run
   line 13     --def_use command--> [12] os.system(command)
2. python-sql-injection: argument 0 of cursor.execute (line 19)
   line 17   [15] term = request.args["q"]
   line 19     --def_use term--> [17] cursor.execute("SELECT * FROM t WHERE name = '" + term + ...
2 findings
```

Each finding is numbered, names the sink call and its watched argument, and lists its path: the source line first, then one step per edge (`def_use`, `argument` into a parameter, `return` into a caller, `free_variable`) with the variable it carries. The bracketed numbers are node ids.

- `--rules builtin` (the default) uses the example rules for the file's language; `--rules rules.json` loads your own, in the JSON format above. YAML files are refused (PyYAML is not a dependency): write the same structure as JSON. A rule file with no rule for the file's language is an error, not "no findings".
- `--json` prints `{"findings": [...]}`, each finding as `Finding.to_dict()` (the path in the [Paths as data](#paths-as-data) format).
- `--finding N` keeps only finding N. `--draw-cfg` and `--draw-dfg` draw each finding (or only N) on the CFG or DFG with its path in orange: the path's nodes filled, and one bold numbered edge per step labeled with its kind and variable. `uv run tree-climber taint app.py --finding 1 --draw-cfg --draw-dfg -o out` writes `out/app.py_finding1_cfg.png` and `out/app.py_finding1_dfg.png`; `--show` opens them.
- `-` reads the code from stdin (`cat app.py | uv run tree-climber taint - -l python`).

`tree-climber query` answers the two most common questions without writing Python. Who calls a function (matched like `CodeGraph.calling`, by name or whole callee; `--calls` can be repeated):

```bash
uv run tree-climber query app.py --calls system
```

```
Calls to system: 1 node
   line 13   [12] os.system(command)  (in run)
```

What a line affects (`--slice-from N`, a forward slice) or depends on (`--backward`). Slices follow arguments and returns into other functions unless you pass `--no-across-calls`, and `--variable NAME` follows one variable:

```bash
uv run tree-climber query app.py --slice-from 7
uv run tree-climber query app.py --slice-from 13 --backward --no-across-calls
```

```
Forward slice from line 7: 5 nodes
   line 7    [7] host = request.args.get("host")  (in ping)
   line 8    [8] run("ping -c 1 " + host)  (in ping)
   line 9    [9] run("ping -c 1 " + shlex.quote(host))  (in ping)
   line 12   [10] ENTRY run  (in run)
   line 13   [12] os.system(command)  (in run)
Backward slice from line 13: 2 nodes
   line 12   [10] ENTRY run  (in run)
   line 13   [12] os.system(command)  (in run)
```

The slice starts from the nodes that begin on the line (or, for a line inside a statement, that statement). `--json` prints `{"nodes": [{"node", "node_type", "text", "line", "function"}, ...]}`.

Over HTTP (see [HTTP API](#4-http-api)), `POST /taint` and `POST /query` take the same `source_code` and `language` as `/parse`:

```bash
curl -s localhost:8000/taint -H 'content-type: application/json' \
  -d '{"language": "python", "source_code": "import os\nos.system(input())\n"}'
```

```json
{"success":true,"findings":[{"rule":"python-command-injection","source":3,"sink":3,"sink_call":"os.system","argument":0,"path":{"steps":[{"node":3,"node_type":"STATEMENT","text":"os.system(input())","edge":null,"variable":null}]}}],"error":null}
```

`/taint` takes an optional `rules` object (the JSON rule format; the built-in example rules when omitted). `/query` takes `"kind": "calls"` with `names`, or `"kind": "slice"` with `line` and optionally `backward`, `variable` and `across_calls` (default true), and returns `nodes` as in `--json`. Node ids are those `/parse` returns for the same code, so a client can map a path onto the graph and onto source spans. Errors (bad rules, a line with no statement) come back as `"success": false` with `error`.

In the web UI, the panel under the editor and the graph lists the findings of the built-in rules for the code in the editor (the Python sample has one). Select a finding to highlight its path: its nodes and numbered steps on the graph, and each node's code in the editor (the source and the sink darker). Select it again, or edit the code, to clear it.

What this does not do:
- one file at a time: a project such as a Django or aiohttp app has to be checked file by file, and a value that crosses files (a helper in another module, a view registered elsewhere) is not followed;
- the CLI and the web UI use the example rules unless given others; framework sources such as Django's `request.GET` or aiohttp's `request.query` need rules of your own (`{"attribute": "request.GET"}`);
- the web UI only uses the built-in rules, and maps paths onto the editor by byte offsets, so on lines with non-ASCII characters the highlight can be shifted.

## 4. HTTP API

```bash
uv run -m uvicorn tree_climber.viz.app:app --port 8000
```

```bash
curl -s localhost:8000/parse -H 'content-type: application/json' \
  -d '{"language": "python", "source_code": "x = 1\nprint(x)\n"}'
```

The response has `success`, `cfg` (`function_name`, `entry_node_ids`, `exit_node_ids`, `nodes`), `ast`, and `dfg` (`edges` from definition to use, labeled with the variable). An unsupported language such as `"cobol"` is rejected with a validation error. `POST /taint` and `POST /query` are described in [Tracing user input](#tracing-user-input). `GET /` lists the supported languages and `GET /health` returns `{"status": "healthy"}`.

## 5. Run the Python tests

```bash
uv run pytest test/python_cfg -q
```

Each test file documents its own expected graphs as edge sets. `test/python_cfg/basic_constructs.py` is a fixture covering a docstring, an import, every parameter kind, and calls between functions.

## 6. Try to break it

Half-typed code is the normal case in an editor, so the visitor must not crash on it. Try incomplete or unusual input and confirm you get a graph instead of an error:

- `break` or `continue` outside a loop: the node appears with no outgoing edge.
- An empty file: the graph has a `<module>` entry and exit.
- A file with only `def` statements: no `<module>` graph, only one graph per function.
- A truncated `try:` or `with` header.
