"""
End-to-end def-use chains for Python, through the reaching-definitions solver.

Chains are described by node text, as {definition: [uses]}, so the tests read
like the code they analyze.
"""

from cfg_helpers import def_use_chains


def test_redefinition_in_straight_line_code():
    code = "x = 1\ny = x\nx = 2\nz = x\n"

    assert def_use_chains(code, "x") == {"x = 1": ["y = x"], "x = 2": ["z = x"]}


def test_parameters_flow_from_the_entry_node():
    code = "def f(a):\n    b = a + 1\n    return b\n"

    assert def_use_chains(code, "a") == {"ENTRY:f": ["b = a + 1"]}
    assert def_use_chains(code, "b") == {"b = a + 1": ["return b"]}


def test_unpacking_defines_every_target():
    code = "a, b = 1, 2\nc = a + b\n"

    assert def_use_chains(code, "a") == {"a, b = 1, 2": ["c = a + b"]}
    assert def_use_chains(code, "b") == {"a, b = 1, 2": ["c = a + b"]}


def test_augmented_assignment_reads_the_previous_definition():
    code = "def f():\n    x = 0\n    x += 1\n    return x\n"

    assert def_use_chains(code, "x") == {
        "x = 0": ["x += 1"],
        "x += 1": ["return x"],
    }


def test_attribute_write_keeps_the_earlier_definition_flowing():
    code = "def f(make, use):\n    obj = make()\n    obj.attr = 1\n    use(obj)\n"

    assert def_use_chains(code, "obj") == {
        "obj = make()": ["obj.attr = 1"],
        "obj.attr = 1": ["use(obj)"],
    }


def test_called_parameters_are_data_dependencies():
    code = "def apply(f, x):\n    return f(x)\n"

    assert def_use_chains(code, "f") == {"ENTRY:apply": ["return f(x)"]}
    assert def_use_chains(code, "x") == {"ENTRY:apply": ["return f(x)"]}


def test_import_defines_a_name():
    code = "import os\nx = os.getcwd()\n"

    assert def_use_chains(code, "os") == {"import os": ["x = os.getcwd()"]}


def test_comprehension_variable_does_not_leak():
    code = "i = 0\nxs = [i for i in range(3)]\nj = i\n"

    assert def_use_chains(code, "i") == {"i = 0": ["j = i"]}
