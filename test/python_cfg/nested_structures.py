"""
Python CFG test fixture: control structures nested inside each other.

Each function is one scenario. They are not meant to run; the tests build the CFG and
check edges and reachability.

- if_in_while(n): an if/else inside a while loop; both branches return to the loop header.
- while_in_if(n): a while loop inside the true branch of an if.
- nested_for(rows): two for loops; `continue` targets the inner loop and `break` leaves
  only the inner loop, so the outer loop keeps going.
- break_in_inner_else(rows): a `break` in the else clause of an inner for loop targets the
  OUTER loop, because the else clause runs after the inner loop context is gone.
- try_in_loop(items): try/except/finally inside a for loop, with `continue` in the handler
  and `break` in the body; both route through the shared finally block.
- loop_in_try(items): a loop inside a try body; an exception in the loop reaches the handler.
- return_through_two_finallys(path): `return` inside nested try/finally blocks passes
  through both finally blocks, innermost first.
- with_in_loop(paths): `with` inside a loop, with a `return` inside the with body.
- match_in_loop(events): a match inside a loop; `break` and `continue` in case bodies target
  the loop.
- nested_match(a, b): a match inside a case body.
- deep_nesting(data): for > if > while > try, with an else on every level that has one.
- Outer / Outer.Inner: classes nested in classes, with methods that contain control flow.
- closure_factory(step): a function that defines a nested function containing a loop and
  returns it.

Expected shape: one subgraph per function and method (so Outer.method and
Outer.Inner.method are separate entries), and every node reachable from some entry.
"""


def if_in_while(n):
    total = 0
    while n > 0:
        if n % 2 == 0:
            total = total + n
        else:
            total = total - n
        n = n - 1
    return total


def while_in_if(n):
    if n > 0:
        while n > 0:
            n = n - 1
    else:
        n = 0
    return n


def nested_for(rows):
    count = 0
    for row in rows:
        for cell in row:
            if cell is None:
                continue
            if cell < 0:
                break
            count = count + cell
    return count


def break_in_inner_else(rows):
    found = None
    for row in rows:
        for cell in row:
            if cell:
                found = cell
                break
        else:
            break
    return found


def try_in_loop(items):
    done = 0
    for item in items:
        try:
            if item is None:
                break
            value = int(item)
        except ValueError:
            continue
        finally:
            done = done + 1
        use(value)
    return done


def loop_in_try(items):
    try:
        for item in items:
            use(item)
    except KeyError:
        return None
    return len(items)


def return_through_two_finallys(path):
    try:
        try:
            return read(path)
        finally:
            close(path)
    finally:
        log(path)


def with_in_loop(paths):
    for path in paths:
        with open(path) as handle:
            if handle.closed:
                return path
            data = handle.read()
    return None


def match_in_loop(events):
    for event in events:
        match event:
            case ["quit"]:
                break
            case ["skip", _]:
                continue
            case [kind, payload] if payload:
                handle(kind, payload)
            case _:
                pass
    return len(events)


def nested_match(a, b):
    match a:
        case 1:
            match b:
                case 2:
                    return "both"
                case _:
                    return "first"
        case _:
            return "none"


def deep_nesting(data):
    result = 0
    for row in data:
        if row:
            while row:
                try:
                    result = result + row.pop()
                except IndexError:
                    break
            else:
                result = result + 1
        else:
            result = result - 1
    return result


class Outer:
    def method(self, flag):
        if flag:
            return 1
        return 0

    class Inner:
        def method(self, items):
            for item in items:
                if item:
                    return item
            return None


def closure_factory(step):
    def advance(value, limit):
        while value < limit:
            value = value + step
        return value

    return advance
