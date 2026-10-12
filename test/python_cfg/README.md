# Python CFG Test Samples

Python source files used as input by the tests in this directory. Each file describes its own scenarios in its header.

- `basic_constructs.py` - module-level code and plain functions
- `nested_structures.py` - control structures nested in each other
- `edge_cases.py` - boundary conditions and unusual but valid code
- `data_flow_patterns.py` - def-use patterns, some shaped like source-to-sink flows

`test_python_fixtures.py` runs the last three; the other `test_*.py` files test one construct family each.
