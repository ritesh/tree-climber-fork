"""Example rule sets for common injection flaws.

They are examples, not complete lists of sources and sinks for any framework:
start from them and add what your code uses.
"""

from typing import Any, Dict, List, Optional

from tree_climber.taint.rules import RuleSet

PYTHON_SOURCES: List[Dict[str, Any]] = [
    {"call": "input"},
    {"call": "os.getenv"},
    {"call": "os.environ.get"},
    {"attribute": "sys.argv"},
    {"attribute": "request.args"},
    {"attribute": "request.form"},
    {"attribute": "request.values"},
    {"attribute": "request.cookies"},
]

C_SOURCES: List[Dict[str, Any]] = [
    {"call": "getenv"},
    {"parameter": "argv", "function": "main"},
]

JAVA_SOURCES: List[Dict[str, Any]] = [
    {"call": "*.getParameter"},
    {"call": "*.getHeader"},
    {"call": "*.getQueryString"},
    {"call": "System.getenv"},
    {"call": "*.readLine"},
]

EXAMPLES: Dict[str, Any] = {
    "rules": [
        {
            "id": "python-command-injection",
            "description": "Example: untrusted input in a shell command.",
            "languages": ["python"],
            "sources": PYTHON_SOURCES,
            "sinks": [
                {"call": "os.system", "arguments": [0, "command"]},
                {"call": "os.popen", "arguments": [0, "cmd"]},
                {"call": "subprocess.*", "arguments": [0, "args"]},
            ],
            "sanitizers": [{"call": "shlex.quote"}],
        },
        {
            "id": "python-code-injection",
            "description": "Example: untrusted input evaluated as code.",
            "languages": ["python"],
            "sources": PYTHON_SOURCES,
            "sinks": [
                {"call": "eval", "arguments": [0]},
                {"call": "exec", "arguments": [0]},
            ],
        },
        {
            "id": "python-sql-injection",
            "description": "Example: untrusted input built into SQL text (query "
            "parameters, the second argument, are safe).",
            "languages": ["python"],
            "sources": PYTHON_SOURCES,
            "sinks": [
                {"call": "*.execute", "arguments": [0, "sql", "operation"]},
                {"call": "*.executemany", "arguments": [0, "sql", "operation"]},
            ],
        },
        {
            "id": "c-command-injection",
            "description": "Example: untrusted input in a shell command.",
            "languages": ["c"],
            "sources": C_SOURCES,
            "sinks": [
                {"call": "system", "arguments": [0]},
                {"call": "popen", "arguments": [0]},
                {"call": "exec*"},
            ],
        },
        {
            "id": "c-format-string",
            "description": "Example: untrusted input used as a format string.",
            "languages": ["c"],
            "sources": C_SOURCES,
            "sinks": [
                {"call": "printf", "arguments": [0]},
                {"call": "fprintf", "arguments": [1]},
                {"call": "sprintf", "arguments": [1]},
                {"call": "snprintf", "arguments": [2]},
                {"call": "syslog", "arguments": [1]},
            ],
        },
        {
            "id": "java-command-injection",
            "description": "Example: untrusted input in a command.",
            "languages": ["java"],
            "sources": JAVA_SOURCES,
            "sinks": [{"call": "*.exec", "arguments": [0]}],
        },
        {
            "id": "java-sql-injection",
            "description": "Example: untrusted input built into SQL text.",
            "languages": ["java"],
            "sources": JAVA_SOURCES,
            "sinks": [
                {"call": "*.executeQuery", "arguments": [0]},
                {"call": "*.executeUpdate", "arguments": [0]},
                {"call": "*.execute", "arguments": [0]},
                {"call": "*.prepareStatement", "arguments": [0]},
            ],
        },
    ]
}


def builtin_rules(language: Optional[str] = None) -> RuleSet:
    """The example rules, for one language or all of them."""
    rules = RuleSet.from_dict(EXAMPLES)
    return RuleSet(tuple(rules.for_language(language)))
