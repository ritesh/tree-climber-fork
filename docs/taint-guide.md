# Taint analysis guide

Taint analysis follows untrusted values (request parameters, environment variables, command-line arguments) through a program and reports where they reach a dangerous call (a shell command, SQL text, `eval`, a format string) without passing through a sanitizer. tree-climber does this for Python, C and Java, one file at a time, from the command line, from Python, over HTTP and in the web UI.

This guide walks through examples you can run. Every program and output below is checked by the test suite (`test/taint/test_taint_guide.py`), so they match what the current code does. The reference for the rule format and the analysis is in the Python guide, under [Taint analysis](./python-guide.md#taint-analysis) and [Tracing user input](./python-guide.md#tracing-user-input).

Setup is the one in the [README](../README.md): after `uv sync`, run the command as `uv run tree-climber` (or activate `.venv` and run `tree-climber`).

## 1. A first run

Save this small Flask app as `app.py`:

```python
import subprocess
import shlex
import sqlite3

from flask import Flask, request

app = Flask(__name__)
db = sqlite3.connect("shop.db")


@app.route("/archive")
def archive():
    name = request.args.get("name", "backup")
    subprocess.run("tar czf /tmp/" + name + ".tgz data", shell=True)
    subprocess.run("tar czf /tmp/" + shlex.quote(name) + ".tgz data", shell=True)


@app.route("/orders")
def orders():
    customer = request.args["customer"]
    return find_orders(customer)


def find_orders(customer):
    query = "SELECT * FROM orders WHERE customer = '%s'" % customer
    return db.execute(query).fetchall()


@app.route("/orders/safe")
def safe_orders():
    customer = request.args["customer"]
    return db.execute("SELECT * FROM orders WHERE customer = ?", (customer,)).fetchall()
```

and run:

```bash
uv run tree-climber taint app.py
```

```
Analyzing: app.py
1. python-command-injection: argument 0 of subprocess.run (line 14)
   line 13   [11] name = request.args.get("name", "backup")
   line 14     --def_use name--> [12] subprocess.run("tar czf /tmp/" + name + ".tgz data", shel...
2. python-sql-injection: argument 0 of db.execute (line 26)
   line 20   [17] customer = request.args["customer"]
   line 21     --def_use customer--> [18] return find_orders(customer)
   line 24     --argument customer--> [19] ENTRY find_orders
   line 25     --def_use customer--> [21] query = "SELECT * FROM orders WHERE customer = '%s'" % cu...
   line 26     --def_use query--> [22] return db.execute(query).fetchall()
2 findings
```

Without `--rules`, the command uses the built-in example rules for the file's language (here, Python: Flask's `request.args`, `request.form`, `request.values` and `request.cookies`, `input()`, `os.getenv`, `sys.argv`; shell commands, `eval`/`exec` and SQL text).

How to read a finding:
- the first line names the rule, the call the value reaches, which of its arguments (counted in the call as written) and the line;
- then the path, one line per step. The first step is the source: the statement that reads untrusted input, or the `ENTRY` of a function whose parameter is a source. Each later step is an edge with the variable it carries: `def_use` (a variable defined at one statement and read at the next), `argument` (into a parameter of a function defined in the file), `return` (back to a caller), `free_variable` (a closure or global), and, with implicit flows, `control`;
- the numbers in brackets are node ids in the CFG.

The second `subprocess.run` is not reported: `shlex.quote` is a sanitizer, and its result is clean. `safe_orders` is not reported either: the SQL rule watches the query text (the first argument), not the parameters.

## 2. Rules for your own code

The built-in rules know nothing about Django or AWS Lambda. Save this as `views.py`:

```python
from django.http import HttpResponse
from django.utils.html import escape


def greet(request):
    name = request.GET.get("name", "world")
    HttpResponse("<h1>Hello " + escape(name) + "</h1>")
    return HttpResponse(content="<h1>Hello " + name + "</h1>")


def lambda_handler(event, context):
    page = event["queryStringParameters"]["page"]
    return {"body": render(page)}


def render(page):
    return eval("f'" + page + "'")
```

With the built-in rules, it has no findings:

```bash
uv run tree-climber taint views.py
```

```
Analyzing: views.py
No findings
```

Save these rules as `rules.json`:

```json
{
  "rules": [
    {
      "id": "django-xss",
      "description": "Request data in an HTML response",
      "languages": ["python"],
      "sources": [{"attribute": "request.GET"}, {"attribute": "request.POST"}],
      "sinks": [{"call": "HttpResponse", "arguments": [0, "content"]}],
      "sanitizers": [{"call": "escape"}]
    },
    {
      "id": "lambda-code-injection",
      "description": "Lambda event data evaluated as code",
      "languages": ["python"],
      "sources": [{"parameter": "event", "function": "*_handler"}],
      "sinks": [{"call": "eval", "arguments": [0]}]
    }
  ]
}
```

```bash
uv run tree-climber taint views.py --rules rules.json
```

```
Analyzing: views.py
1. django-xss: argument 0 of HttpResponse (line 8)
   line 6    [6] name = request.GET.get("name", "world")
   line 8      --def_use name--> [8] return HttpResponse(content="<h1>Hello " + name + "</h1>")
2. lambda-code-injection: argument 0 of eval (line 17)
   line 11   [9] ENTRY lambda_handler
   line 12     --def_use event--> [11] page = event["queryStringParameters"]["page"]
   line 13     --def_use page--> [12] return {"body": render(page)}
   line 16     --argument page--> [13] ENTRY render
   line 17     --def_use page--> [15] return eval("f'" + page + "'")
2 findings
```

What each part of a rule means:
- `languages`: the rule applies to files in these languages (`python`, `c`, `java`); leave it out for all. `--rules` refuses a file with no rule for the file's language, so a typo cannot pass as "no findings".
- `sources`, one key each:
  - `call`: the result of the call is untrusted (`input`, `*.getParameter`);
  - `parameter`: a parameter, by name or position (`0` is the first), of the functions whose name matches `function` (a glob; `*` for every function);
  - `attribute`: reading this attribute is untrusted (`request.GET`; `*` stands for one name, as in `request.*`). It is matched in the code text, not in strings or comments, and a statement that writes to it does not count.
- `sinks`: `call` is the dangerous call, `arguments` the positions and keyword names it must not receive untrusted data in (`[0, "content"]` covers both `HttpResponse(x)` and `HttpResponse(content=x)`). Without `arguments`, every argument is watched.
- `sanitizers`: the result of the call is clean, whatever it was given. It cleans only that result: `escape(name)` is clean, `name` stays tainted.

A call pattern is a glob matched against the whole callee as written: `eval` matches `eval(...)` only, `os.system` matches `os.system(...)` but not `system(...)` after `from os import system`, and `*.execute` matches a method called `execute` on anything. If a rule finds nothing, check the callee text first.

The rule file is JSON. YAML is not supported (PyYAML is not a dependency); convert it to JSON, or load it yourself and pass the dict to `RuleSet.from_dict` (section 5).

## 3. C and Java

The built-in C rules treat `getenv` and `main`'s `argv` as sources, and look for command injection (`system`, `popen`, `exec*`) and format strings (`printf`, `fprintf`, `sprintf`, `snprintf`, `syslog`). Save this as `logger.c`:

```c
#include <stdio.h>
#include <stdlib.h>
#include <syslog.h>

void log_message(const char *message) {
    syslog(LOG_INFO, message);
    syslog(LOG_INFO, "%s", message);
}

int main(int argc, char *argv[]) {
    char command[256];
    const char *home = getenv("HOME");

    if (argc < 2) {
        return 1;
    }
    log_message(argv[1]);
    printf(home);
    snprintf(command, sizeof command, "ls %s", argv[1]);
    system(command);
    return 0;
}
```

```bash
uv run tree-climber taint logger.c
```

```
Analyzing: logger.c
1. c-format-string: argument 1 of syslog (line 6)
   line 10   [4] ENTRY main
   line 17     --def_use argv--> [11] log_message(argv[1]);
   line 5      --argument message--> [0] ENTRY log_message
   line 6      --def_use message--> [2] syslog(LOG_INFO, message);
2. c-format-string: argument 0 of printf (line 18)
   line 12   [7] const char *home = getenv("HOME");
   line 18     --def_use home--> [12] printf(home);
2 findings
```

`syslog(LOG_INFO, "%s", message)` is safe: the format is the second argument, and it is a constant. `system(command)` is a real injection that is missed: `snprintf` writes into `command` through a pointer, and output parameters are not followed (see section 7).

The built-in Java rules take servlet parameters and headers, `System.getenv` and `readLine` as sources, and look for `exec` and SQL text. Save this as `Search.java`:

```java
import java.io.IOException;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;

public class Search extends HttpServlet {
    private Connection connection;

    protected void doGet(HttpServletRequest request, HttpServletResponse response)
            throws IOException {
        String term = request.getParameter("q");
        try {
            ResultSet rows = find(term);
            PreparedStatement safe = connection.prepareStatement(
                "SELECT name FROM products WHERE name = ?");
            safe.setString(1, term);
            safe.executeQuery();
        } catch (SQLException e) {
            response.sendError(500);
        }
    }

    private ResultSet find(String term) throws SQLException {
        String sql = "SELECT name FROM products WHERE name = '" + term + "'";
        return connection.createStatement().executeQuery(sql);
    }
}
```

```bash
uv run tree-climber taint Search.java
```

```
Analyzing: Search.java
1. java-sql-injection: argument 0 of connection.createStatement().executeQuery (line 29)
   line 15   [5] String term = request.getParameter("q");
   line 17     --def_use term--> [6] ResultSet rows = find(term);
   line 27     --argument term--> [13] ENTRY find
   line 28     --def_use term--> [15] String sql = "SELECT name FROM products WHERE name = '" +...
   line 29     --def_use sql--> [16] return connection.createStatement().executeQuery(sql);
1 finding
```

The prepared statement is not reported: its SQL is a constant, and `setString` is not a sink.

## 4. JSON output, CI and pictures

`--json` prints the findings as data, with the path's node ids, types, text, edges and variables:

```bash
uv run tree-climber taint logger.c --json | jq -r '.findings[] | "\(.rule) \(.sink_call): \(.path.steps[0].text)"'
```

```
c-format-string syslog: main
c-format-string printf: const char *home = getenv("HOME");
```

The command exits with 0 whether or not it finds anything. To fail a CI step on findings, test the JSON: `jq -e '.findings == []'` exits with 1 when there are any.

```bash
uv run tree-climber taint app.py --json | jq -e '.findings == []' > /dev/null || echo "taint findings"
```

```
taint findings
```

To see a finding on the graph, draw it: `--draw-cfg` and `--draw-dfg` draw the CFG and the data-flow graph with the path in orange, and `--finding N` picks one finding (`--show` opens the images):

```bash
uv run tree-climber taint logger.c --finding 2 --draw-cfg -o out
```

```
Analyzing: logger.c
2. c-format-string: argument 0 of printf (line 18)
   line 12   [7] const char *home = getenv("HOME");
   line 18     --def_use home--> [12] printf(home);
2 findings
Saved finding 2 on the CFG: out/logger.c_finding2_cfg.png
```

Code can also come from stdin, with its language: `cat app.py | uv run tree-climber taint - -l python`.

## 5. From Python

`analyze_source(language, code, rules)` returns the findings. Rules can be built in Python:

```python
from tree_climber.taint import Rule, Sanitizer, Sink, Source, analyze_source

rule = Rule(
    "log-injection",
    sources=[Source(call="input"), Source(parameter="user", function="audit")],
    sinks=[Sink(call="logger.*", arguments=[0])],
    sanitizers=[Sanitizer(call="strip_newlines")],
)

CODE = '''
import logging

logger = logging.getLogger(__name__)


def strip_newlines(text):
    return text.replace("\\n", " ")


def audit(user, action):
    logger.info("%s did %s", user, action)
    logger.info("user " + strip_newlines(user) + " did " + action)
    logger.warning("user " + user)


name = input()
logger.info("login: " + name)
'''

for finding in analyze_source("python", CODE.lstrip(), rule):
    print(finding.rule, finding.sink_call, finding.argument)
    print(finding.path)
```

```
log-injection logger.warning 0
[7] ENTRY audit
  --def_use user--> [11] logger.warning("user " + user)
log-injection logger.info 0
[12] name = input()
  --def_use name--> [13] logger.info("login: " + name)
```

`analyze_source` takes a `Rule`, a list of rules, or a `RuleSet`. `RuleSet.load("rules.json")` reads a rule file, `RuleSet.from_dict(...)` a parsed one (from YAML, for example), and `builtin_rules("python")` the built-in rules. A `Finding` has `rule` (the rule id), `source` and `sink` (node ids), `sink_call`, `argument`, `path` (a query `Path` whose `steps` have `node`, `edge` and `variable`), and `to_dict()` for JSON. With a CFG you already built, call `analyze(cfg, rules, language)` instead.

Two options make the analysis more precise, and are only available from Python. `implicit_flows=True` follows decisions made on tainted data: here the command does not contain the input, but which command runs depends on it:

```python
from tree_climber.taint import analyze_source, builtin_rules

CODE = '''
import os

level = input()
if level == "debug":
    flags = "-v"
else:
    flags = "-q"
os.system("make " + flags)
'''
rules = builtin_rules("python")
print(analyze_source("python", CODE.lstrip(), rules))
for finding in analyze_source("python", CODE.lstrip(), rules, implicit_flows=True):
    print(finding)
```

```
[]
python-command-injection: argument 0 of os.system
[3] level = input()
  --def_use level--> [4] level == "debug"
  --control--> [6] flags = "-v"
  --def_use flags--> [8] os.system("make " + flags)
```

`field_sensitive=True` keeps fields and constant keys apart, so `d["k"] = input()` does not taint `d["other"]`; see [Taint analysis](./python-guide.md#taint-analysis) in the Python guide for an example and the details of both options.

## 6. Over HTTP and in the web UI

The API server (`uv run -m uvicorn tree_climber.viz.app:app --port 8000`) has `POST /taint`, which takes `source_code`, `language` and optionally `rules` (the JSON rule format), and returns the findings as `--json` does. The web UI lists the built-in rules' findings for the code in the editor, and highlights a finding's path on the graph and in the code when you select it. See [Tracing user input](./python-guide.md#tracing-user-input) for both.

## 7. When a finding is missing, or should not be there

The analysis is approximate in both directions. What it misses, and what to do about it:
- **Values that cross files.** Each file is analysed alone: a helper imported from another module, or a view registered elsewhere, is not followed. Make the boundary a source or a sink: a `parameter` source on the view functions, or a sink on the helper call.
- **Output parameters.** C's `fgets(buf, ...)`, `snprintf(cmd, ...)` and similar calls do not taint the buffer they write (as in `logger.c` above). To catch these, you can make the formatting call a sink itself, for example `{"call": "snprintf", "arguments": [3, 4, 5]}` in a rule of your own, at the cost of reports where the buffer is never used dangerously.
- **Aliasing, dynamic code and function pointers.** Two names for one object, `getattr`, `exec` of strings, and calls through function pointers are not followed.
- **Java fields and arrays.** Writes into fields and array elements are not modeled, so taint stored in `this.x` or `a[i]` is lost.
- **Branches on tainted data**, unless `implicit_flows=True` (section 5).
- **Callee text that does not match.** Patterns match the callee as written: `system(...)` after `from os import system` needs a `system` pattern, not `os.system`.

What it reports that may be safe:
- **Calls it does not know pass taint through.** `int(x)` or `len(x)` of a tainted value is tainted. Add such calls as sanitizers if their results are safe for your sinks.
- **Containers and objects are one value**, unless `field_sensitive=True`: `d["k"] = tainted` taints all of `d`, and `self.x = tainted` taints `self`.
- **A function is analysed once for all callers.** If one call of `def wrap(a): return a` gets tainted data, every `wrap(...)` result is tainted.
- **Sinks cannot look at other arguments.** `subprocess.run(args, shell=False)` is reported like `shell=True`; a rule cannot tell them apart.

The [Python guide](./python-guide.md#taint-analysis) lists the approximations in full.
