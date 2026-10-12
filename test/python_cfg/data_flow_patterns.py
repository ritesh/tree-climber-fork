"""
Python CFG test fixture: data-flow patterns for def-use and reaching-definition tests.

Each function is one pattern; the tests check which definition reaches which use. Several
are shaped like untrusted-input flows (a `source()` call, assignments, a `sink()` call),
because that is the surface taint analysis builds on (see the epic "Graph queries and
taint tracking"). The names `source`, `sink` and `sanitize` are placeholders.

- straight_flow(): source -> assignment -> concatenation -> sink, all in one block.
- reassignment_kills(): a tainted variable is overwritten before the sink; only the second
  definition reaches the sink.
- branch_merge(flag): a variable defined differently in both branches; both reach the use.
- one_branch_defines(flag): defined only in the true branch, so the earlier definition also
  reaches the use through the false edge.
- loop_carried(items): an accumulator that depends on itself across iterations.
- flow_through_try(): a definition inside try that reaches the handler's use only through
  the state before the raising statement.
- with_target(): the `as` name is defined by the with header.
- comprehension_flow(items): a comprehension whose result depends on the iterable and not
  on a same-named outer variable.
- match_capture(command): a capture in a case pattern flows into the body and the guard.
- container_write(): a subscript write, which defines and uses the container (a weak
  update), so earlier definitions keep flowing.
- attribute_write(obj): same for an attribute write.
- sanitizer_call(): a call on the path; the analysis sees the assignment but not that the
  call cleans the value (calls are names, not call sites with arguments).
- argument_to_callee(): a value passed to another function. Dataflow does not cross the
  call, so there is no chain from the argument to the callee's parameter.
- return_value(): a value returned by another function; also not connected to the caller.

Expected shape: one subgraph per function; the chains asserted in test_python_fixtures.py.
"""


def straight_flow():
    data = source()
    command = "run " + data
    sink(command)


def reassignment_kills():
    data = source()
    data = "constant"
    sink(data)


def branch_merge(flag):
    if flag:
        value = source()
    else:
        value = "default"
    sink(value)


def one_branch_defines(flag):
    value = "default"
    if flag:
        value = source()
    sink(value)


def loop_carried(items):
    total = ""
    for item in items:
        total = total + item
    sink(total)


def flow_through_try():
    value = "safe"
    try:
        value = source()
        risky(value)
    except ValueError:
        sink(value)


def with_target():
    with open(source()) as handle:
        text = handle.read()
    sink(text)


def comprehension_flow(items):
    item = "outer"
    cleaned = [piece.strip() for piece in items]
    sink(cleaned)
    sink(item)


def match_capture(command):
    match command:
        case [name, *rest] if name:
            sink(name)
            sink(rest)
        case _:
            pass


def container_write():
    table = {}
    table["key"] = source()
    sink(table)


def attribute_write(obj):
    obj.value = source()
    sink(obj)


def sanitizer_call():
    data = source()
    clean = sanitize(data)
    sink(clean)


def argument_to_callee():
    data = source()
    consume(data)


def consume(payload):
    sink(payload)


def return_value():
    data = fetch()
    sink(data)


def fetch():
    return source()
