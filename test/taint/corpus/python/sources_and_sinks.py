"""
The built-in Python sources and sinks: `input`, `os.getenv`,
`os.environ.get`, `sys.argv` and Flask's `request.args`/`form`/`values`/
`cookies`; `os.system`, `os.popen`, `subprocess.*`, `eval`/`exec` and SQL text
in `*.execute`/`*.executemany`. Query parameters, other positions and
keywords, attributes named in strings or comments, and writes to an
attribute source are not findings.
"""

import os
import subprocess
import sys

from flask import request


def environment():
    # ruleid: python-command-injection
    os.system(os.getenv("EDITOR"))
    # ruleid: python-command-injection
    os.popen(os.environ.get("PAGER"))


def arguments():
    # ruleid: python-command-injection
    subprocess.run(sys.argv[1], shell=True)
    # ruleid: python-command-injection
    subprocess.check_output(args=sys.argv[2:])
    # ok: python-command-injection
    subprocess.run("ls", cwd=sys.argv[1])


def flask_view():
    # ruleid: python-command-injection
    os.system("ping " + request.args.get("host"))
    # ruleid: python-code-injection
    exec(request.form["code"])
    # ruleid: python-command-injection
    os.system(request.values["cmd"])
    # ruleid: python-command-injection
    os.system(request.cookies.get("theme"))


def named_not_read():
    # ok: python-command-injection
    os.system("echo request.args")  # request.args


def written_not_read():
    request.args = {}
    # ok: python-command-injection
    os.system("true")


def sql(cursor):
    term = request.args["q"]
    # ruleid: python-sql-injection
    cursor.execute("SELECT * FROM t WHERE name = '" + term + "'")
    # ruleid: python-sql-injection
    cursor.execute(sql="SELECT * FROM t WHERE name = '%s'" % term)
    # ruleid: python-sql-injection
    cursor.executemany("INSERT INTO t VALUES ('" + term + "')", [])
    # ok: python-sql-injection
    cursor.execute("SELECT * FROM t WHERE name = ?", (term,))
    # ok: python-sql-injection
    cursor.execute("SELECT * FROM t WHERE name = %(name)s", {"name": term})
