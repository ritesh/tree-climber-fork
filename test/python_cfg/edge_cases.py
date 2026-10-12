"""
Python CFG test fixture: boundary conditions and unusual but valid code.

Each function is one scenario. They are not meant to run.

- only_pass(): a body that is only `pass`.
- only_docstring(): a body that is only a docstring (one expression statement).
- unreachable_after_return(x): statements after `return` and after `raise`; they have no
  predecessor and the CFG must not crash or invent edges to them.
- while_true(limit): `while True` with a `break`; the header keeps a false edge, as for
  any loop.
- one_line_compound(x): `if x: return 1` and `for i in x: use(i)` written on one line,
  and two statements separated by `;`.
- bare_raise(): a bare `raise` inside an except clause, and an uncaught raise.
- return_in_finally(): a `return` inside `finally`, which wins over the try's return.
- empty_loop_bodies(xs): loops whose body is only `pass` or only `continue`.
- many_handlers(x): several except clauses, one bare, with `else` and `finally`.
- chained_and_unpacking(): chained assignment, tuple/star unpacking, augmented assignment,
  annotated assignment with and without a value, and the walrus operator.
- conditional_expressions(a, b): `x if c else y` nested, and a name containing "else".
- delete_and_scope(): `del`, `global` and `nonlocal` statements (they define nothing).
- decorator_stack(): stacked decorators with arguments, on a function and on a class.
- generators_and_async(): an async generator using async for, async with, await, yield.
- Empty(): a class with only `pass`.
- Slots(): a class with class-level assignments and a method, no `__init__`.

Expected shape: a subgraph per function, no exceptions raised while building, and every
node that is not code after a return/raise reachable from some entry.
"""


def only_pass():
    pass


def only_docstring():
    """Nothing else."""


def unreachable_after_return(x):
    if x:
        return 1
        dead = 2
    raise ValueError(x)
    dead_too = 3


def while_true(limit):
    n = 0
    while True:
        n = n + 1
        if n > limit:
            break
    return n


def one_line_compound(x):
    if x: return 1
    for i in x: use(i)
    a = 1; b = 2
    return a + b


def bare_raise():
    try:
        risky()
    except Exception:
        log()
        raise
    raise RuntimeError("unreachable normally")


def return_in_finally():
    try:
        return 1
    finally:
        return 2


def empty_loop_bodies(xs):
    for x in xs:
        pass
    while xs:
        continue
    return xs


def many_handlers(x):
    try:
        y = int(x)
    except ValueError as err:
        y = -1
        report(err)
    except (TypeError, KeyError):
        y = -2
    except:
        y = -3
    else:
        y = y + 1
    finally:
        done()
    return y


def chained_and_unpacking():
    a = b = 1
    c, (d, *e) = 1, (2, 3, 4)
    a += b
    f: int = 3
    g: int
    if (h := a + f) > 2:
        return h
    return c, d, e, g


def conditional_expressions(a, b):
    elsewhere = a if b else (b if a else None)
    return elsewhere


def delete_and_scope():
    global counter
    value = 1
    del value

    def inner():
        nonlocal_name = 1
        return nonlocal_name

    return inner


@first
@second(1, flag=True)
def decorator_stack():
    pass


@register("x")
class Decorated:
    def method(self):
        return 1


async def generators_and_async(sessions):
    async with sessions.open() as session:
        async for item in session:
            value = await item.get()
            yield value


class Empty:
    pass


class Slots:
    __slots__ = ("a", "b")
    default = compute()

    def total(self):
        return self.a + self.b
