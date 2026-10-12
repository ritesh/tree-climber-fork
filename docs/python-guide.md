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
| `async def` | Modeled like `def` |
| Classes (and their methods), decorated functions, nested `def`, `match` | **One opaque statement** each: the CFG node is the whole construct and its body is not analyzed (#9, #10) |
| Lambdas, comprehensions | Stay inside their statement; their own variables are not reported (#10, #11) |

Python is available from the CLI and the HTTP API. The web UI's language selector does not list it yet (#12).

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

`--show` is on by default and cannot be switched off; in a headless shell the images are still saved.

## 2. Dump the graph as text

The CLI only draws images. To compare against expected edges, paste this into a file such as `dump.py`. It prints CFG edges and def-use chains for Python read from stdin.

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

Check: the call node gets a `function_call` edge into `helper` and `helper`'s exit returns to it, even though `helper` is defined after `main`. Calls are matched by the called name only: `obj.f()` is linked to every function named `f`, and a later `f = 1` does not unlink it. Methods inside classes are not analyzed.

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

Check: `items[0] = 1` both uses and defines `items` (a weak update), so the original definition still flows through it. The dataflow framework supports only strong updates, so this convention keeps earlier definitions alive. Attribute writes (`obj.f = v`) behave the same.

### Constructs that are opaque today

```python
def outer(xs):
    class A:
        pass
    sq = [v * v for v in xs]
    key = lambda v: v + 1
    match xs:
        case [first, *rest]:
            print(first)
    return sq
```

```
CFG edges
  ENTRY:outer -> class A:
  class A: -> sq = [v * v for v in xs]
  sq = [v * v for v in xs] -> key = lambda v: v + 1
  key = lambda v: v + 1 -> match xs:
  match xs: -> return sq
  return sq -> EXIT:outer
Def-use chains
  xs: ENTRY:outer => sq = [v * v for v in xs], match xs:
  sq: sq = [v * v for v in xs] => return sq
```

Check: `class` and `match` each collapse to a single node, so `print(first)` is not a separate step and `first`/`rest` do not appear as definitions. The comprehension and lambda stay inside their statements and their own variable (`v`) is not reported. A decorated function and a function nested in another function likewise become one statement of the enclosing flow, with no graph of their own and no call links into them. These gaps are tracked as #9, #10, and #11; anything that differs from this section is a bug.

## 4. HTTP API

```bash
uv run -m uvicorn tree_climber.viz.app:app --port 8000
```

```bash
curl -s localhost:8000/parse -H 'content-type: application/json' \
  -d '{"language": "python", "source_code": "x = 1\nprint(x)\n"}'
```

The response has `success`, `cfg` (`function_name`, `entry_node_ids`, `exit_node_ids`, `nodes`), `ast`, and `dfg` (`edges` from definition to use, labeled with the variable). An unsupported language such as `"cobol"` is rejected with a validation error. `GET /` lists the supported languages and `GET /health` returns `{"status": "healthy"}`.

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
