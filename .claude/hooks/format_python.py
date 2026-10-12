#!/usr/bin/env python3
"""PostToolUse hook: format the Python file that was just edited.

Reads the hook's JSON from stdin and, for a `.py` file, runs the project's
pinned ruff (`uv run ruff`, the version CI uses) on that one file. Everything
else is ignored, so unrelated files and Markdown code blocks are never touched.
It never fails the tool call; CI's `ruff format --check` is the gate.
"""

import json
import subprocess
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        path = payload.get("tool_input", {}).get("file_path", "")
    except (ValueError, AttributeError):
        return 0

    if isinstance(path, str) and path.endswith(".py"):
        subprocess.run(["uv", "run", "--quiet", "ruff", "format", path], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
