"""
Tests for `yield`, `yield from`, `await`, and the async statement forms.

`yield` and `await` are expressions, so each stays inside its statement and does not
end the function. The async statements share the handlers of their sync forms.
"""

import pytest
from cfg_helpers import build_cfg, def_use_chains, edges, entry_names, node_by_text

from tree_climber.ast_utils import parse_source_to_ast
from tree_climber.cfg.cfg_types import NodeType
from tree_climber.cfg.languages.python import PythonCFGVisitor


def bindings(source: str):
    root = parse_source_to_ast(source, "python").root_node
    statement = next(c for c in root.children if c.is_named and c.type != "comment")
    visitor = PythonCFGVisitor()
    return (
        sorted(visitor.get_definitions(statement)),
        sorted(visitor.get_uses(statement)),
        visitor.get_calls(statement),
    )


class TestYield:
    @pytest.mark.parametrize(
        "source, definitions, uses, calls",
        [
            ("yield", [], [], []),
            ("yield x", [], ["x"], []),
            ("yield x, y", [], ["x", "y"], []),
            ("x = yield", ["x"], [], []),
            ("x = yield y", ["x"], ["y"], []),
            ("yield from g(x)", [], ["g", "x"], ["g"]),
            ("x = yield from g(y)", ["x"], ["g", "y"], ["g"]),
            ("x = (yield f(y))", ["x"], ["f", "y"], ["f"]),
        ],
    )
    def test_bindings(self, source, definitions, uses, calls):
        assert bindings(source) == (definitions, uses, calls)

    def test_yield_does_not_end_the_function(self):
        cfg = build_cfg("def gen(xs):\n    yield 1\n    yield 2\n    return 3\n")

        assert edges(cfg) == {
            ("ENTRY:gen", "yield 1", None),
            ("yield 1", "yield 2", None),
            ("yield 2", "return 3", None),
            ("return 3", "EXIT:gen", None),
        }

    def test_a_generator_is_one_function_subgraph(self):
        cfg = build_cfg("def gen():\n    yield 1\n\ndef plain():\n    return 1\n")

        assert entry_names(cfg) == ["gen", "plain"]

    def test_yield_in_a_loop_with_a_sent_value(self):
        cfg = build_cfg(
            "def gen(xs):\n"
            "    for x in xs:\n"
            "        got = yield x\n"
            "        if got:\n"
            "            yield from other(got)\n"
        )

        found = edges(cfg)
        assert ("for x in xs", "got = yield x", "true") in found
        assert ("got = yield x", "got", None) in found
        assert ("got", "yield from other(got)", "true") in found
        assert ("yield from other(got)", "for x in xs", None) in found
        assert ("got", "for x in xs", "false") in found

    def test_the_sent_value_is_defined_by_the_yield(self):
        code = "def gen():\n    value = yield\n    yield value\n"

        assert def_use_chains(code, "value") == {"value = yield": ["yield value"]}

    def test_a_yield_in_a_try_may_raise_from_before_it(self):
        cfg = build_cfg(
            "def gen():\n"
            "    x = 0\n"
            "    try:\n"
            "        x = yield x\n"
            "    except GeneratorExit:\n"
            "        done(x)\n"
        )

        assert ("x = 0", "except GeneratorExit", "exception") in edges(cfg)

    def test_yield_inside_with_goes_through_the_exit_node(self):
        cfg = build_cfg(
            "def gen(p):\n"
            "    with open(p) as fh:\n"
            "        yield fh.read()\n"
            "    done = 1\n"
        )

        found = edges(cfg)
        assert ("yield fh.read()", "__exit__", None) in found
        assert ("__exit__", "done = 1", None) in found

    def test_a_call_to_a_generator_function_is_linked_to_it(self):
        cfg = build_cfg("def gen():\n    yield 1\n\nitems = gen()\n")

        assert ("items = gen()", "ENTRY:gen", "function_call") in edges(cfg)


class TestAwait:
    @pytest.mark.parametrize(
        "source, definitions, uses, calls",
        [
            ("await f(y)", [], ["f", "y"], ["f"]),
            ("x = await f(y)", ["x"], ["f", "y"], ["f"]),
            ("x = await y", ["x"], ["y"], []),
            ("await a.b(c)", [], ["a", "c"], ["b"]),
            ("return await f()", [], ["f"], ["f"]),
        ],
    )
    def test_bindings(self, source, definitions, uses, calls):
        assert bindings(
            f"async def g():\n    {source}\n".split("\n", 1)[1].strip()
        ) == (
            definitions,
            uses,
            calls,
        )

    def test_await_is_an_ordinary_statement(self):
        cfg = build_cfg("async def f(s):\n    data = await s.get()\n    return data\n")

        assert entry_names(cfg) == ["f"]
        assert edges(cfg) == {
            ("ENTRY:f", "data = await s.get()", None),
            ("data = await s.get()", "return data", None),
            ("return data", "EXIT:f", None),
        }

    def test_await_may_raise_into_the_enclosing_try(self):
        cfg = build_cfg(
            "async def f():\n"
            "    try:\n"
            "        await work()\n"
            "    except Exception:\n"
            "        pass\n"
        )

        assert ("ENTRY:f", "except Exception", "exception") in edges(cfg)

    def test_an_awaited_call_is_linked_to_the_coroutine(self):
        cfg = build_cfg(
            "async def work():\n    return 1\n\nasync def main():\n    await work()\n"
        )

        found = edges(cfg)
        assert ("await work()", "ENTRY:work", "function_call") in found
        assert ("EXIT:work", "await work()", "function_return") in found


class TestAsyncStatements:
    def test_async_for_is_a_loop_with_an_else(self):
        cfg = build_cfg(
            "async def f(urls):\n"
            "    async for u in urls:\n"
            "        if bad(u):\n"
            "            break\n"
            "    else:\n"
            "        done = 1\n"
            "    return done\n"
        )

        found = edges(cfg)
        header = "async for u in urls"
        assert node_by_text(cfg, header).node_type == NodeType.LOOP_HEADER
        assert (header, "bad(u)", "true") in found
        assert (header, "done = 1", "false") in found
        assert ("break", "return done", None) in found
        assert ("done = 1", "return done", None) in found

    def test_async_for_defines_its_target_and_uses_the_iterable(self):
        code = "async def f(urls):\n    async for u in urls:\n        use(u)\n"

        assert def_use_chains(code, "u") == {"async for u in urls": ["use(u)"]}
        assert def_use_chains(code, "urls") == {"ENTRY:f": ["async for u in urls"]}

    def test_async_with_is_an_implicit_try_finally(self):
        cfg = build_cfg(
            "async def f():\n"
            "    async with lock() as held:\n"
            "        return held\n"
            "    after = 1\n"
        )

        found = edges(cfg)
        assert ("async with lock() as held", "__aexit__", "exception") in found
        assert ("return held", "__aexit__", None) in found
        assert ("__aexit__", "EXIT:f", "return") in found

    def test_async_with_defines_its_target(self):
        code = "async def f():\n    async with lock() as held:\n        use(held)\n"

        assert def_use_chains(code, "held") == {
            "async with lock() as held": ["use(held)"]
        }

    def test_a_whole_async_function_together(self):
        cfg = build_cfg(
            "async def main(urls):\n"
            "    async with session() as s:\n"
            "        async for u in urls:\n"
            "            data = await s.get(u)\n"
            "            if data:\n"
            "                break\n"
            "        else:\n"
            "            data = None\n"
            "    return data\n"
        )

        found = edges(cfg)
        assert ("async with session() as s", "async for u in urls", None) in found
        assert ("data", "break", "true") in found
        assert ("break", "__aexit__", None) in found
        assert ("data = None", "__aexit__", None) in found
        assert ("__aexit__", "return data", None) in found


@pytest.mark.parametrize(
    "source",
    [
        "async def f(",
        "async def f():\n    await",
        "async def f():\n    async for",
        "async def f():\n    async with",
        "def g():\n    yield",
        "def g():\n    x = yield from",
        "def g():\n    yield from",
    ],
)
def test_half_typed_code_still_builds_a_graph(source):
    assert build_cfg(source).nodes
