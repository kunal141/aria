"""
Code Intelligence — Week 10

Parses Python files using the stdlib `ast` module (no external deps).
Extracts functions, classes, imports, and builds a dependency graph.

Three capabilities:
  1. parse_file()      — extract structured metadata from a .py file
  2. build_dep_graph() — map which module imports which across a directory
  3. ingest_repo()     — chunk code by function/class boundary and store in Chroma

Code chunking is different from text chunking:
  - Text → split by word count
  - Code → split by function/class (each is a natural semantic unit)
  This produces chunks like "def kpi_node(state) -> dict: ..." that embed meaningfully.
"""
import ast
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from aria.knowledge.ingestion import get_collection, _doc_id, _ef


# ─────────────────────────────────────────────────────────────────────────────
# Data types
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FunctionInfo:
    name: str
    args: list[str]
    docstring: Optional[str]
    line_start: int
    line_end: int
    source: str          # the raw source lines for this function


@dataclass
class ClassInfo:
    name: str
    methods: list[str]
    docstring: Optional[str]
    line_start: int
    line_end: int
    source: str


@dataclass
class FileInfo:
    path: str
    module_name: str             # e.g. "aria.skills.kpi_skill"
    imports: list[str]           # other modules this file imports
    functions: list[FunctionInfo]
    classes: list[ClassInfo]
    top_level_docstring: Optional[str]


# ─────────────────────────────────────────────────────────────────────────────
# AST Parser
# ─────────────────────────────────────────────────────────────────────────────

def _get_source_lines(source_lines: list[str], node) -> str:
    return "".join(source_lines[node.lineno - 1: node.end_lineno])


def _get_docstring(node) -> Optional[str]:
    """Extract docstring from a function or class AST node."""
    if (node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)):
        return node.body[0].value.value.strip()
    return None


def _extract_imports(tree: ast.Module) -> list[str]:
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return list(set(imports))


def parse_file(path: str) -> Optional[FileInfo]:
    """
    Parse a single Python file and return structured metadata.
    Returns None if the file cannot be parsed.
    """
    p = Path(path)
    if not p.exists() or p.suffix != ".py":
        return None

    try:
        source = p.read_text(encoding="utf-8")
        source_lines = source.splitlines(keepends=True)
        tree = ast.parse(source, filename=str(p))
    except SyntaxError:
        return None

    # Module name from path (best effort)
    module_name = str(p).replace(os.sep, ".").replace("/", ".").removesuffix(".py")

    # Top-level docstring
    top_doc = _get_docstring(tree) if tree.body else None

    imports = _extract_imports(tree)

    functions = []
    classes = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            args = [a.arg for a in node.args.args]
            functions.append(FunctionInfo(
                name=node.name,
                args=args,
                docstring=_get_docstring(node),
                line_start=node.lineno,
                line_end=node.end_lineno,
                source=_get_source_lines(source_lines, node),
            ))
        elif isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            classes.append(ClassInfo(
                name=node.name,
                methods=methods,
                docstring=_get_docstring(node),
                line_start=node.lineno,
                line_end=node.end_lineno,
                source=_get_source_lines(source_lines, node),
            ))

    return FileInfo(
        path=str(p),
        module_name=module_name,
        imports=imports,
        functions=functions,
        classes=classes,
        top_level_docstring=top_doc,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Dependency Graph
# ─────────────────────────────────────────────────────────────────────────────

def build_dep_graph(root_dir: str) -> dict[str, list[str]]:
    """
    Walk a directory, parse every .py file, and return a dependency graph:
    { module_name: [list of modules it imports] }
    Only includes aria.* imports (filters out stdlib + third-party).
    """
    graph: dict[str, list[str]] = {}
    root = Path(root_dir)

    for py_file in root.rglob("*.py"):
        info = parse_file(str(py_file))
        if info is None:
            continue
        # Relative module name within the repo
        try:
            rel = py_file.relative_to(root)
            mod = ".".join(rel.with_suffix("").parts)
        except ValueError:
            mod = info.module_name

        aria_imports = [imp for imp in info.imports if imp.startswith("aria")]
        graph[mod] = aria_imports

    return graph


# ─────────────────────────────────────────────────────────────────────────────
# Code Ingestion — function/class boundary chunking into Chroma
# ─────────────────────────────────────────────────────────────────────────────

def _code_chunk_id(file_path: str, symbol: str) -> str:
    return _doc_id(f"code::{file_path}", hash(symbol) % 10000)


def ingest_repo(root_dir: str, week_added: int = 10) -> dict:
    """
    Walk all .py files in root_dir. For each file:
      - Each function → one chunk (name + args + docstring + source)
      - Each class    → one chunk (name + methods + docstring + first 20 lines of source)
    Stores in the same Chroma collection as documents, with doc_type="code".
    Returns summary counts.
    """
    collection = get_collection()
    root = Path(root_dir)
    counts = {"files": 0, "functions": 0, "classes": 0}

    documents, ids, metadatas = [], [], []

    for py_file in root.rglob("*.py"):
        info = parse_file(str(py_file))
        if info is None:
            continue
        counts["files"] += 1

        try:
            rel_path = str(py_file.relative_to(root))
        except ValueError:
            rel_path = str(py_file)

        for fn in info.functions:
            # Chunk = signature line + docstring + first 30 lines of source
            chunk = f"FILE: {rel_path}\nDEF: {fn.name}({', '.join(fn.args)})\n"
            if fn.docstring:
                chunk += f"DOC: {fn.docstring}\n"
            chunk += fn.source[:1200]  # cap at 1200 chars per chunk

            cid = _code_chunk_id(rel_path, f"fn::{fn.name}::{fn.line_start}")
            documents.append(chunk)
            ids.append(cid)
            metadatas.append({
                "source": rel_path,
                "doc_type": "code",
                "symbol": fn.name,
                "symbol_type": "function",
                "line_start": fn.line_start,
                "week_added": week_added,
            })
            counts["functions"] += 1

        for cls in info.classes:
            chunk = f"FILE: {rel_path}\nCLASS: {cls.name}\nMETHODS: {', '.join(cls.methods)}\n"
            if cls.docstring:
                chunk += f"DOC: {cls.docstring}\n"
            chunk += cls.source[:1200]

            cid = _code_chunk_id(rel_path, f"cls::{cls.name}::{cls.line_start}")
            documents.append(chunk)
            ids.append(cid)
            metadatas.append({
                "source": rel_path,
                "doc_type": "code",
                "symbol": cls.name,
                "symbol_type": "class",
                "line_start": cls.line_start,
                "week_added": week_added,
            })
            counts["classes"] += 1

    if documents:
        collection.upsert(documents=documents, ids=ids, metadatas=metadatas)

    return counts


# ─────────────────────────────────────────────────────────────────────────────
# Dependency graph printer (for display)
# ─────────────────────────────────────────────────────────────────────────────

def print_dep_graph(graph: dict[str, list[str]]) -> None:
    print("Dependency Graph (aria.* imports only):")
    for mod, deps in sorted(graph.items()):
        if deps:
            print(f"  {mod}")
            for dep in sorted(deps):
                print(f"    └─ {dep}")
