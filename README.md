# tree-climber

Tree Climber is a comprehensive static analysis framework for generating Control Flow Graphs (CFGs) and performing dataflow analysis on source code. It supports multiple programming languages through Tree-sitter parsers and provides both programmatic APIs and interactive web visualization.

## Goals

- Clean architecture and thorough test coverage.
- Semi- (and eventually fully-)automated analyses written by coding agents.
- Interactive, detailed, high-quality visualizations for educational and exploration purposes.

## Supported Languages

- **C**: CFG generation with control structures, loops, and functions
- **Java**: CFG generation for Java language constructs
- **Python**: Module-level code and functions, `if`/`while`/`for` (with `break`, `continue`, and loop `else`), `match`, `try`/`except`/`finally`, `raise`, `with`, nested functions, classes and methods, and decorators. Lambdas, comprehensions, `yield` and `await` stay inside their statement, and closures are connected across scopes by the interprocedural analysis (arguments, returns and free variables). See the [Python guide](./docs/python-guide.md).
- **Extensible**: Framework designed to easily add new language support

Run `tree-climber --list-languages` to see what your install supports.

## Architecture

Tree Climber parses source code with tree-sitter and builds a control flow graph with one visitor per language. It then computes data flow: reaching definitions, def-use chains, flows between functions, and control dependence. On top of these, `CodeGraph` answers queries and the taint engine follows untrusted input. The CLI, the web API and the editor present the results.

[docs/architecture.md](./docs/architecture.md) explains it level by level. It covers the layers, one program followed through each of them, and the algorithms behind them.

## Installation

This project uses `uv` for Python dependency management and `bun` for frontend dependencies.

### Prerequisites

- Python 3.12
- [uv](https://github.com/astral-sh/uv) package manager
- [bun](https://bun.sh/) for frontend dependencies

### Setup

1. Clone the repository:
```bash
git clone https://github.com/bstee615/tree-climber
cd tree-climber
```

2. Install dependencies:
```bash
# Install dependencies on Ubuntu
sudo apt install -y graphviz graphviz-dev
uv sync
```

3. (For web frontend) Install frontend dependencies:
```bash
cd src/tree_climber/viz/frontend
bun install
```

`uv sync` also installs the `tree-climber` command; run it with `uv run tree-climber`, or activate `.venv` to use it directly.

## Usage

### CLI

CLI is available as a command, `tree-climber`. Run the CLI against a file or directory. Use the flags below to pick which graphs to generate and how to render them. The language is detected from the file extension (`.c`, `.h`, `.java`, `.py`, `.pyi`); use `-l` to set it for stdin or clipboard input.

Example:

```bash
tree-climber test/example.c --draw-cfg --draw-cpg
```

Python works the same way, for example `tree-climber my_module.py --draw-cfg --draw-dfg`. See the [Python guide](./docs/python-guide.md) for exercises that show what is modeled.

Example CFG | Example CPG (Code Property Graph, including AST + CFG + DFG edges)
-- | --
![Example CFG](./test/example.c_cfg.png) | ![Example CPG](./test/example.c_cpg.png)

An alternative view of the CPG is available which draws the AST and CFG separately, with edges connecting CFG <-> AST nodes. Use the option `-L bigraph`.

Example bigraph CPG
--
![Example bigraph CPG](./test/example.c_cpg_bigraph.png)

Options also accept underscores (`--draw_cfg`), for compatibility with earlier versions. Try `tree-climber --help` to see all options, `tree-climber --version`, or `tree-climber --list-languages`.

Graphs are saved as PNG files next to the input, or in the directory given with `-o`. `--format svg` (or `pdf`) saves them in that format instead; SVG is much faster to draw for large files, and a large PNG is drawn at a lower resolution to keep it under 25 megapixels.

Two commands answer questions as text: `tree-climber taint app.py` traces untrusted input to dangerous calls and prints each finding with its path (`--rules rules.json` for your own rules, `--json`, and `--draw-cfg`/`--draw-dfg` to draw a finding's path), and `tree-climber query app.py --calls system` or `--slice-from 12` lists the callers of a function or a slice from a line. See the [taint analysis guide](./docs/taint-guide.md) and [Tracing user input](./docs/python-guide.md#tracing-user-input).

### Web Application

The project includes a webapp for visualizing and interacting with CFG/DFGs, inspired by https://godbolt.org.
To run it easily, open the project in VSCode and launch the config named "Run Server and Frontend".

<img width="1849" height="811" alt="image" src="https://github.com/user-attachments/assets/2cde36a0-94e3-49f0-980c-7331784c06c7" />

#### Start the Backend Server

```bash
# Run FastAPI server with hot reload
uv run -m uvicorn tree_climber.viz.app:app --reload --host 0.0.0.0 --port 8000

# Or use the VS Code task: "Run FastAPI Server"
```

#### Start the Frontend

```bash
# Navigate to frontend directory
cd src/tree_climber/viz/frontend

# Start development server
bun dev

# Or use the VS Code task: "Run Frontend"
```

#### Access the Application Locally

- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs

#### API Endpoints

The FastAPI backend provides the following endpoints:

- `POST /parse` - Parse source code (`{"source_code": ..., "language": "c" | "java" | "python"}`) and return the CFG, AST, and def-use edges as JSON (`"include_ast": false` leaves out the AST)
- `POST /taint` - Taint findings for source code, with their paths (built-in example rules, or `rules` in the request)
- `POST /query` - The nodes calling a function, or a slice from a line
- `GET /` - API version and supported languages
- `GET /health` - Health check endpoint

## Limitations

- The analysis is intraprocedural; function calls are linked to functions of the same name in the same file.
- Variable updates through fields, subscripts, and pointers are approximated, because the dataflow framework only supports strong updates.
- Python: a nested function's reads of enclosing variables are not connected to their definitions. See the [Python guide](./docs/python-guide.md).
- C and Java: see the [limitations section of the language extension guide](./docs/plans/extending-languages.md).

## Development

### Adding New Languages

1. Create a new visitor class in `src/tree_climber/cfg/languages/`
2. Implement language-specific CFG construction logic
3. Register the language in `src/tree_climber/language_registry.py` (name, display name, file extensions, visitor path). The CLI, web API, and CFG builder all read from it.
4. Add the language to the list in `src/tree_climber/viz/frontend/src/LanguageSelector.tsx` so it appears in the web UI, and a sample program for it to `src/sampleCode.ts` (each language keeps its own editor buffer, starting from its sample)
5. Add test cases in the `test/` directory

### Adding New Analyses

1. Create a new analysis class in `src/tree_climber/dataflow/analyses/`
2. Implement the dataflow problem interface
3. Add API endpoints in `src/tree_climber/viz/app.py`
4. Update frontend to display analysis results

### Frontend Development

The frontend is built with:
- **React**: UI framework
- **Cytoscape.js**: Graph visualization
- **Monaco Editor**: Code editing
- **Vite**: Build tool and dev server

### Backend Development

The backend uses:
- **FastAPI**: Web framework
- **Tree-sitter**: Source code parsing
- **Pydantic**: Data validation

### CLI Development

The CLI uses:
- **Typer**: Terminal display and argument parsing
- **GraphViz**: Graph visualization

### Checks

CI runs these on every pull request; run them before pushing:

```bash
uv run ruff format --check
uv run ruff check
uv run pyright
uv run pytest
(cd src/tree_climber/viz/frontend && bun install --frozen-lockfile && bun run build)
```

### Stress testing

`python -m tree_climber.stress` runs every analysis (CFG, data flow, interprocedural flows, control dependence, taint) over a directory of real code and reports crashes, timeouts and the slowest files:

```bash
uv run python -m tree_climber.stress path/to/project --language python --json report.json
```

Each file runs in a worker process with a time limit (`--timeout`, `--jobs`), so a crash or a hang is reported for that file and the run goes on. With `--baseline FILE` (known failures), it exits with 1 only on new ones. The weekly `Stress` workflow runs it on pinned revisions of CPython's `Lib`, typeshed and Black's tests, with `.github/stress-baseline.json`, and runs the Hypothesmith property tests (`test/test_property.py`) with many more examples (`HYPOTHESIS_PROFILE=stress`). Start it by hand from the Actions tab.

## Documentation

- [Architecture](./docs/architecture.md): how the project is built, level by level, with the algorithms behind it
- [Python guide](./docs/python-guide.md): what is modeled and how to exercise it
- [Taint analysis guide](./docs/taint-guide.md): running taint analysis on Python, C and Java, with rules of your own
- [Extending languages](./docs/plans/extending-languages.md): adding a language, and per-language limitations
- `docs/plans/`: design plans and results for each piece of work
