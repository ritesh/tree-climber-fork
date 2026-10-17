"""FastAPI server for parsing source code and returning Control Flow Graphs in JSON format.

This server provides endpoints to parse source code from various programming languages
and return their Control Flow Graph (CFG) representation in JSON format.
"""

import logging
import os
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from tree_climber.ast_utils import ast_to_json
from tree_climber.cfg.builder import CFGBuilder
from tree_climber.dataflow.analyses.def_use import DefUseSolver
from tree_climber.dataflow.analyses.reaching_definitions import (
    ReachingDefinitionsProblem,
)
from tree_climber.dataflow.solver import WorklistSolver
from tree_climber.language_registry import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    get_language,
)
from tree_climber.query import CodeGraph
from tree_climber.reporting import (
    BUILTIN_RULES,
    load_rules,
    node_to_dict,
    rules_from_dict,
    slice_from_line,
)
from tree_climber.taint import analyze

# CORS configuration
CORS_ORIGINS = [
    "http://localhost:3000",  # React default dev server
    "http://localhost:5173",  # Vite default dev server
    "http://localhost:5174",  # Vite fallback port
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
]

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

__version__ = "0.0.0"
app = FastAPI(
    title="Tree Climber CFG API",
    description="Parse source code and return Control Flow Graphs in JSON format",
    version=__version__,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class SourceRequest(BaseModel):
    """Source code and its language, as every analysis endpoint takes them"""

    source_code: str = Field(..., description="The source code to parse")
    language: str = Field(
        default=DEFAULT_LANGUAGE,
        description="The programming language of the source code",
        json_schema_extra={"enum": [*SUPPORTED_LANGUAGES]},
    )

    @field_validator("language")
    @classmethod
    def language_must_be_supported(cls, value: str) -> str:
        get_language(value)
        return value


class ParseRequest(SourceRequest):
    """Request model for parsing source code"""

    include_ast: bool = Field(
        default=True,
        description="Include the AST; it is most of the response on large files",
    )


class ParseResponse(BaseModel):
    """Response model for parsed CFG and AST"""

    success: bool = Field(description="Whether the parsing was successful")
    cfg: Optional[Dict[str, Any]] = Field(
        default=None, description="The Control Flow Graph in JSON format"
    )
    ast: Optional[Dict[str, Any]] = Field(
        default=None, description="The Abstract Syntax Tree in JSON format"
    )
    dfg: Optional[Dict[str, Any]] = Field(
        default=None, description="The Data Flow Graph in JSON format"
    )
    # Error message if parsing failed
    error: Optional[str] = Field(
        default=None, description="Error message if parsing failed"
    )


class TaintRequest(SourceRequest):
    """Request model for taint analysis"""

    rules: Optional[Dict[str, Any]] = Field(
        default=None,
        description='A rule set ({"rules": [...]}, as in a JSON rule file); '
        "the built-in example rules when omitted",
    )


class TaintResponse(BaseModel):
    """Response model for taint findings"""

    success: bool = Field(description="Whether the analysis ran")
    findings: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Findings: rule, source and sink node ids, sink_call, "
        "argument, and path (steps with node id, edge kind and variable)",
    )
    error: Optional[str] = Field(
        default=None, description="Error message if the analysis failed"
    )


class QueryRequest(SourceRequest):
    """Request model for a graph query"""

    kind: Literal["calls", "slice"] = Field(
        description="calls: the nodes calling any of `names`; slice: the slice "
        "from the statement on `line`"
    )
    names: List[str] = Field(default_factory=list, description="For calls")
    line: Optional[int] = Field(default=None, ge=1, description="For slice")
    backward: bool = Field(default=False, description="For slice: backward")
    variable: Optional[str] = Field(
        default=None, description="For slice: follow only this variable"
    )
    across_calls: bool = Field(
        default=True, description="For slice: follow arguments and returns"
    )


class QueryResponse(BaseModel):
    """Response model for a graph query"""

    success: bool = Field(description="Whether the query ran")
    nodes: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Nodes: id, node_type, text, line, enclosing function",
    )
    error: Optional[str] = Field(
        default=None, description="Error message if the query failed"
    )


@app.get("/")
async def root():
    """Root endpoint providing API information"""
    return {
        "message": "Tree Climber CFG API",
        "version": __version__,
        "supported_languages": SUPPORTED_LANGUAGES,
        "endpoints": {
            "/parse": "POST - Parse source code and return CFG and AST in JSON format",
            "/taint": "POST - Taint findings with their paths",
            "/query": "POST - Nodes calling a function, or a slice from a line",
            "/health": "GET - Health check endpoint",
        },
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.post("/parse", response_model=ParseResponse)
def parse_source_code(request: ParseRequest) -> ParseResponse:
    """Parse source code and return a CFG and AST in JSON format.

    Args:
        request: ParseRequest containing source code, language and whether to
            include the AST

    Returns:
        ParseResponse containing the CFG and AST in JSON format or error message
    """
    try:
        logger.info(
            f"Parsing {len(request.source_code)} bytes of {request.language} code"
        )

        # Create and setup CFG builder
        builder = CFGBuilder(request.language)
        builder.setup_parser()
        if not builder.parser:
            raise HTTPException(
                status_code=500,
                detail=f"Parser for {request.language} not set up correctly.",
            )

        # Parse source code to get AST
        tree = builder.parser.parse(bytes(request.source_code, "utf8"))
        if not tree:
            raise HTTPException(status_code=400, detail="Failed to parse source code.")

        # Convert AST to dictionary for JSON serialization
        ast_dict = ast_to_json(tree.root_node) if request.include_ast else None

        # Build CFG from AST
        cfg = builder.build_cfg(tree=tree)

        logger.info(
            f"CFG built successfully: function={cfg.function_name}, "
            f"nodes={len(cfg.nodes)}"
        )

        # Analyze reaching definitions
        problem = ReachingDefinitionsProblem()

        solver = WorklistSolver()
        result = solver.solve(cfg, problem)

        # Analyze def-use chains
        def_use_analyzer = DefUseSolver()
        def_use_result = def_use_analyzer.solve(cfg, result)

        # Convert CFG to JSON-serializable dictionary
        cfg_dict = cfg.to_dict()

        return ParseResponse(
            success=True, cfg=cfg_dict, ast=ast_dict, dfg=def_use_result.to_dict()
        )

    except Exception as e:
        logger.error(f"Error parsing source code: {str(e)}")
        return ParseResponse(success=False, error=str(e))


@app.post("/taint", response_model=TaintResponse)
def taint_source_code(request: TaintRequest) -> TaintResponse:
    """Run taint rules (the built-in example rules by default) on source code.
    Node ids are those `/parse` returns for the same code."""
    try:
        if request.rules is None:
            rules = load_rules(BUILTIN_RULES, request.language)
        else:
            rules = rules_from_dict(request.rules, request.language)
        graph = CodeGraph.from_source(request.language, request.source_code)
        findings = analyze(graph.cfg, rules, request.language)
        return TaintResponse(
            success=True, findings=[finding.to_dict() for finding in findings]
        )
    except Exception as e:
        logger.error(f"Error in taint analysis: {str(e)}")
        return TaintResponse(success=False, error=str(e))


@app.post("/query", response_model=QueryResponse)
def query_source_code(request: QueryRequest) -> QueryResponse:
    """Answer a query on source code. Node ids are those `/parse` returns."""
    try:
        graph = CodeGraph.from_source(request.language, request.source_code)
        if request.kind == "calls":
            if not request.names:
                raise ValueError("A calls query needs names")
            nodes = graph.calling(*request.names)
        else:
            if request.line is None:
                raise ValueError("A slice query needs a line")
            nodes = slice_from_line(
                graph,
                request.line,
                backward=request.backward,
                variable=request.variable,
                across_calls=request.across_calls,
            )
        return QueryResponse(
            success=True, nodes=[node_to_dict(graph, node) for node in nodes]
        )
    except Exception as e:
        logger.error(f"Error in query: {str(e)}")
        return QueryResponse(success=False, error=str(e))


if os.environ.get("ENABLE_DEBUGPY", "0") == "1":
    import debugpy

    debugpy.listen(("0.0.0.0", 5678))
    logger.info("debugpy listening on 5678")
