#!/usr/bin/env python3
"""
Tree Climber - Program Analysis Tool

A command-line interface for analyzing source code and generating visualizations
of Abstract Syntax Trees (AST), Control Flow Graphs (CFG), Def-Use Chains (DFG),
and Code Property Graphs (CPG).

Feature parity with tree-climber: https://github.com/bstee615/tree-climber
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import click
import typer
import typer.main
from typer.core import TyperCommand
from typing_extensions import Annotated

from tree_climber import __version__ as VERSION
from tree_climber.cli.commands import (
    SUPPORTED_LAYOUTS,
    AnalysisOptions,
    analyze_source_code,
    run_query,
    run_taint,
)
from tree_climber.cli.options import QueryOptions, TaintOptions
from tree_climber.cli.visualizers.constants import IMAGE_FORMATS
from tree_climber.cli.source import (
    ClipboardSource,
    CodeSource,
    FileSource,
    StdinSource,
    is_stdin_available,
    read_stdin,
)
from tree_climber.language_registry import SUPPORTED_LANGUAGES


def normalize_option(name: str) -> str:
    """Treat `--draw_cfg` and `--draw-cfg` as the same option.

    Click passes the option name without its leading dashes.
    """
    return name.replace("_", "-")


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"Tree Climber v{VERSION}")
        typer.echo("Program analysis tool with AST, CFG, DFG, and CPG visualization")
        raise typer.Exit()


def list_languages_callback(value: bool) -> None:
    if value:
        typer.echo("Supported programming languages:")
        for lang in SUPPORTED_LANGUAGES:
            typer.echo(f"  • {lang}")
        raise typer.Exit()


SUBCOMMANDS: Dict[str, typer.Typer] = {}

FormatOption = Annotated[
    str,
    typer.Option(
        "--format",
        click_type=click.Choice(IMAGE_FORMATS),
        help="Image format of the saved drawings",
    ),
]


class DrawCommand(TyperCommand):
    """The drawing command, which hands `taint ...` and `query ...` to those
    commands so that a file name can still come first (`tree-climber FILE
    --draw-cfg`)."""

    def main(
        self,
        args: Optional[Sequence[str]] = None,
        prog_name: Optional[str] = None,
        complete_var: Optional[str] = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        arguments = list(sys.argv[1:] if args is None else args)
        if arguments and arguments[0] in SUBCOMMANDS:
            name = arguments[0]
            return typer.main.get_command(SUBCOMMANDS[name]).main(
                args=arguments[1:],
                prog_name=f"{prog_name or app.info.name} {name}",
                complete_var=complete_var,
                standalone_mode=standalone_mode,
                windows_expand_args=windows_expand_args,
                **extra,
            )
        return super().main(
            args,
            prog_name,
            complete_var,
            standalone_mode,
            windows_expand_args,
            **extra,
        )


# Create the main Typer app
app = typer.Typer(
    name="tree-climber",
    help="Program analysis tool for generating AST, CFG, DFG, and CPG visualizations",
    add_completion=False,
    rich_markup_mode="rich",
)


@app.command(
    cls=DrawCommand, context_settings={"token_normalize_func": normalize_option}
)
def typer_main(
    version: Annotated[
        Optional[bool],
        typer.Option(
            "--version",
            callback=version_callback,
            is_eager=True,
            help="Show version information and exit",
        ),
    ] = None,
    list_languages: Annotated[
        Optional[bool],
        typer.Option(
            "--list-languages",
            callback=list_languages_callback,
            is_eager=True,
            help="List supported programming languages and exit",
        ),
    ] = None,
    filename: Annotated[
        Optional[Path],
        typer.Argument(
            help="Source code file or directory to analyze, 'clipboard' to read from clipboard, or pipe via stdin",
        ),
    ] = None,
    # Analysis options
    draw_ast: Annotated[
        bool,
        typer.Option("--draw-ast", help="Visualize Abstract Syntax Tree"),
    ] = False,
    draw_cfg: Annotated[
        bool,
        typer.Option("--draw-cfg", help="Visualize Control Flow Graph"),
    ] = False,
    draw_dfg: Annotated[
        bool,
        typer.Option("--draw-dfg", help="Visualize Data Flow Graph/Def-Use Chains"),
    ] = False,
    draw_duc: Annotated[
        bool,
        typer.Option(
            "--draw-duc", help="Visualize Def-Use Chains (alias for --draw-dfg)"
        ),
    ] = False,
    draw_cpg: Annotated[
        bool,
        typer.Option("--draw-cpg", help="Visualize Code Property Graph (AST+CFG+DFG)"),
    ] = False,
    # Language and format options
    language: Annotated[
        Optional[str],
        typer.Option(
            "--language",
            "-l",
            help=f"Programming language ({', '.join(SUPPORTED_LANGUAGES)}). Auto-detected if not specified.",
        ),
    ] = None,
    # Output options
    output_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--output",
            "-o",
            help="Output directory for saved files (default: same as input file)",
        ),
    ] = None,
    show: Annotated[
        bool,
        typer.Option(
            "--show", help="Open the saved visualizations in the default image viewer"
        ),
    ] = False,
    # Verbosity and debugging
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable verbose output"),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Suppress all output except errors"),
    ] = False,
    # Performance options
    timing: Annotated[
        bool,
        typer.Option("--timing", help="Show timing information for each analysis step"),
    ] = False,
    layout: Annotated[
        str,
        typer.Option(
            "--layout",
            "-L",
            help=f"Layout style for visualizations ({', '.join(SUPPORTED_LAYOUTS)}).",
        ),
    ] = "subtree",
    image_format: FormatOption = "png",
):
    """
    Analyze source code and generate program analysis visualizations.

    Examples:

    # AST:\n
    tree-climber test/example.c --draw-ast

    # CFG:\n
    tree-climber test/example.c --draw-cfg

    # CFG + DFG view (CFG nodes + dashed DFG edges):\n
    tree-climber test/example.c --draw-cfg --draw-dfg

    # DFG-only view (Def-Use Chains):\n
    tree-climber test/example.c --draw-dfg\n
    tree-climber test/example.c --draw-duc  # alias for --draw-dfg

    # Combined views with overlays, subtree layout (default):\n
    tree-climber test/example.c --draw-cpg

    # Combined views with overlays, bigraph layout:\n
    tree-climber test/example.c --draw-cpg -L bigraph

    # Specify language and output directory explicitly:\n
    tree-climber test/test.java --language java --draw-ast --draw-cfg --draw-dfg --draw-cpg --output ./out

    # Python files are detected by their .py extension:\n
    tree-climber test/python_cfg/basic_constructs.py --draw-cfg --draw-dfg

    # Read code from clipboard (language must be specified):\n
    tree-climber clipboard --language java --draw-ast
    tree-climber clipboard -l c --draw-cfg --draw-dfg

    # Read code from stdin pipe (language must be specified):\n
    echo 'int main() { return 0; }' | tree-climber - --language c --draw-ast
    cat mycode.java | tree-climber - -l java --draw-cfg
    cat module.py | tree-climber - -l python --draw-cfg --draw-dfg

    # Trace untrusted input to dangerous calls (see tree-climber taint --help):\n
    tree-climber taint app.py\n
    tree-climber taint app.py --rules rules.json --draw-cfg

    # Ask the graph who calls a function, or what a line affects (see tree-climber query --help):\n
    tree-climber query app.py --calls system\n
    tree-climber query app.py --slice-from 12
    """
    # Handle draw_duc as alias for draw_dfg
    draw_dfg = draw_dfg or draw_duc

    # Check for special filenames and stdin input
    stdin_available = is_stdin_available()
    clipboard_requested = filename and str(filename) == "clipboard"
    stdin_requested = filename and str(filename) == "-"

    # Validate input source - exactly one valid input method
    if stdin_requested:
        if not stdin_available:
            typer.echo(
                "Error: Filename '-' specified but no stdin input detected", err=True
            )
            raise typer.Exit(1)
        if Path("-").exists():
            typer.echo(
                "Error: 'stdin' signifies stdin input but a file named 'stdin' exists",
                err=True,
            )
            raise typer.Exit(1)

    if clipboard_requested and Path("clipboard").exists():
        typer.echo(
            "Error: 'clipboard' signifies clipboard input but a file named 'clipboard' exists",
            err=True,
        )
        raise typer.Exit(1)

    if not filename and not stdin_available:
        typer.echo(
            "Error: Must specify filename, 'clipboard' for clipboard input, '-' for stdin, or pipe input via stdin",
            err=True,
        )
        raise typer.Exit(1)

    # Validate inputs
    if not any([draw_ast, draw_cfg, draw_dfg, draw_cpg]):
        typer.echo(
            "Error: At least one visualization option must be specified "
            "(--draw-ast, --draw-cfg, --draw-dfg/--draw-duc, or --draw-cpg)",
            err=True,
        )
        raise typer.Exit(1)

    if quiet and verbose:
        typer.echo("Error: --quiet and --verbose cannot be used together", err=True)
        raise typer.Exit(1)

    if layout not in SUPPORTED_LAYOUTS:
        typer.echo(
            f"Error: Unsupported layout '{layout}'. "
            f"Supported layouts: {', '.join(SUPPORTED_LAYOUTS)}",
            err=True,
        )
        raise typer.Exit(1)

    if language and language not in SUPPORTED_LANGUAGES:
        typer.echo(
            f"Error: Unsupported language '{language}'. "
            f"Supported languages: {', '.join(SUPPORTED_LANGUAGES)}",
            err=True,
        )
        raise typer.Exit(1)

    # Create code source based on input type
    code_source: CodeSource
    if clipboard_requested:
        from tree_climber.cli.clipboard import ClipboardError, get_clipboard_content

        try:
            source_code = get_clipboard_content()
            if not source_code.strip():
                typer.echo("Error: Clipboard is empty", err=True)
                raise typer.Exit(1)
            code_source = ClipboardSource(source_code)
        except ClipboardError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

        # For clipboard input, we need to detect language or require it
        if not language:
            typer.echo(
                "Error: Language must be specified when using 'clipboard' "
                "(cannot auto-detect from clipboard content)",
                err=True,
            )
            raise typer.Exit(1)
    elif stdin_requested or (not filename and stdin_available):
        source_code = read_stdin()
        if not source_code.strip():
            typer.echo("Error: Stdin is empty", err=True)
            raise typer.Exit(1)
        code_source = StdinSource(source_code)

        # For stdin input, we need to detect language or require it
        if not language:
            typer.echo(
                "Error: Language must be specified when using stdin "
                "(cannot auto-detect from piped content)",
                err=True,
            )
            raise typer.Exit(1)
    else:
        # At this point, filename is guaranteed to be not None by validation logic
        assert filename is not None
        code_source = FileSource(filename)

        # Auto-detect language if not specified for file input
        if not language:
            language = code_source.get_language_hint()
            if not language:
                typer.echo(
                    f"Error: Could not auto-detect language for '{filename}'. "
                    f"Please specify with --language option.",
                    err=True,
                )
                raise typer.Exit(1)

    # Set up output directory
    if output_dir is None:
        output_dir = code_source.get_output_dir()

    # Create analysis options
    options = AnalysisOptions(
        draw_ast=draw_ast,
        draw_cfg=draw_cfg,
        draw_dfg=draw_dfg,
        draw_cpg=draw_cpg,
        language=language,
        layout=layout,
        output_dir=output_dir,
        show=show,
        verbose=verbose,
        quiet=quiet,
        timing=timing,
        image_format=image_format,
    )

    # Perform analysis
    try:
        analyze_source_code(code_source, options)
    except Exception as e:
        if verbose:
            import traceback

            typer.echo(f"Error: {e}", err=True)
            typer.echo(traceback.format_exc(), err=True)
        else:
            typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


def resolve_source(filename: Path, language: Optional[str]) -> Tuple[CodeSource, str]:
    """A file, or stdin for `-`, and its language."""
    if language and language not in SUPPORTED_LANGUAGES:
        typer.echo(
            f"Error: Unsupported language '{language}'. "
            f"Supported languages: {', '.join(SUPPORTED_LANGUAGES)}",
            err=True,
        )
        raise typer.Exit(1)
    code_source: CodeSource
    if str(filename) == "-":
        if not language:
            typer.echo("Error: Language must be specified when using stdin", err=True)
            raise typer.Exit(1)
        if not is_stdin_available():
            typer.echo(
                "Error: Filename '-' specified but no stdin input detected", err=True
            )
            raise typer.Exit(1)
        source_code = read_stdin()
        if not source_code.strip():
            typer.echo("Error: Stdin is empty", err=True)
            raise typer.Exit(1)
        return StdinSource(source_code), language
    code_source = FileSource(filename)
    language = language or code_source.get_language_hint()
    if not language:
        typer.echo(
            f"Error: Could not auto-detect language for '{filename}'. "
            f"Please specify with --language option.",
            err=True,
        )
        raise typer.Exit(1)
    return code_source, language


def fail(error: Exception) -> None:
    typer.echo(f"Error: {error}", err=True)
    raise typer.Exit(1)


FileArgument = Annotated[
    Path,
    typer.Argument(help="Source file to analyze, or '-' for stdin (with --language)"),
]
LanguageOption = Annotated[
    Optional[str],
    typer.Option(
        "--language",
        "-l",
        help=f"Programming language ({', '.join(SUPPORTED_LANGUAGES)}). Auto-detected if not specified.",
    ),
]
JsonOption = Annotated[bool, typer.Option("--json", help="Print the result as JSON")]

taint_app = typer.Typer(add_completion=False, rich_markup_mode="rich")


@taint_app.command(context_settings={"token_normalize_func": normalize_option})
def taint(
    filename: FileArgument,
    rules: Annotated[
        str,
        typer.Option(
            "--rules",
            "-r",
            help="'builtin' for the example rules, or a JSON rule file",
        ),
    ] = "builtin",
    language: LanguageOption = None,
    as_json: JsonOption = False,
    finding: Annotated[
        Optional[int],
        typer.Option(
            "--finding", "-f", min=1, help="Only this finding (numbered from 1)"
        ),
    ] = None,
    draw_cfg: Annotated[
        bool,
        typer.Option("--draw-cfg", help="Draw each finding's path on the CFG"),
    ] = False,
    draw_dfg: Annotated[
        bool,
        typer.Option("--draw-dfg", help="Draw each finding's path on the DFG"),
    ] = False,
    output_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--output",
            "-o",
            help="Output directory for images (default: same as input file)",
        ),
    ] = None,
    show: Annotated[
        bool,
        typer.Option("--show", help="Open the saved images in the image viewer"),
    ] = False,
    image_format: FormatOption = "png",
):
    """
    Trace untrusted input to dangerous calls and print each finding with its path.

    Examples:

    # With the built-in example rules:\n
    tree-climber taint app.py

    # With your own rules (JSON, see the Python guide), as JSON output:\n
    tree-climber taint app.py --rules rules.json --json

    # Draw the path of finding 1 on the CFG and the DFG:\n
    tree-climber taint app.py --finding 1 --draw-cfg --draw-dfg -o out
    """
    code_source, language = resolve_source(filename, language)
    options = TaintOptions(
        language=language,
        rules=rules,
        as_json=as_json,
        finding=finding,
        draw_cfg=draw_cfg,
        draw_dfg=draw_dfg,
        output_dir=output_dir or code_source.get_output_dir(),
        show=show,
        image_format=image_format,
    )
    try:
        run_taint(code_source, options)
    except Exception as e:
        fail(e)


query_app = typer.Typer(add_completion=False, rich_markup_mode="rich")


@query_app.command(context_settings={"token_normalize_func": normalize_option})
def query(
    filename: FileArgument,
    calls: Annotated[
        Optional[List[str]],
        typer.Option(
            "--calls", help="Nodes that call this function (repeat for several)"
        ),
    ] = None,
    slice_from: Annotated[
        Optional[int],
        typer.Option(
            "--slice-from",
            min=1,
            help="Nodes whose values depend on the statement on this line",
        ),
    ] = None,
    backward: Annotated[
        bool,
        typer.Option(
            "--backward", help="With --slice-from: the nodes the line depends on"
        ),
    ] = False,
    variable: Annotated[
        Optional[str],
        typer.Option("--variable", help="With --slice-from: follow only this variable"),
    ] = None,
    across_calls: Annotated[
        bool,
        typer.Option(
            "--across-calls/--no-across-calls",
            help="With --slice-from: follow arguments and returns between functions",
        ),
    ] = True,
    language: LanguageOption = None,
    as_json: JsonOption = False,
):
    """
    Answer a question about the graph: who calls a function, or a slice from a line.

    Examples:

    # Which statements call os.system (or anything named system):\n
    tree-climber query app.py --calls system

    # What the statement on line 7 affects, and what it depends on:\n
    tree-climber query app.py --slice-from 7\n
    tree-climber query app.py --slice-from 7 --backward
    """
    if bool(calls) == (slice_from is not None):
        typer.echo("Error: Give exactly one of --calls and --slice-from", err=True)
        raise typer.Exit(1)
    code_source, language = resolve_source(filename, language)
    options = QueryOptions(
        language=language,
        calls=calls or [],
        slice_from=slice_from,
        backward=backward,
        variable=variable,
        across_calls=across_calls,
        as_json=as_json,
    )
    try:
        run_query(code_source, options)
    except Exception as e:
        fail(e)


SUBCOMMANDS.update({"taint": taint_app, "query": query_app})


def main() -> None:
    app()


if __name__ == "__main__":
    main()
