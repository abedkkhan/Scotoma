"""Build a compact, static territory index for a source repository."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

MAX_FILE_SIZE = 400 * 1024
MAX_SIGNATURE_LENGTH = 600

SKIP_DIRECTORIES = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
}

SKIP_FILES = {
    "bun.lock",
    "bun.lockb",
    "composer.lock",
    "cargo.lock",
    "gemfile.lock",
    "npm-shrinkwrap.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "yarn.lock",
}

LANGUAGES = {
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cs": "C#",
    ".css": "CSS",
    ".go": "Go",
    ".h": "C/C++ Header",
    ".hpp": "C++ Header",
    ".html": "HTML",
    ".java": "Java",
    ".js": "JavaScript",
    ".jsx": "JavaScript JSX",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".lua": "Lua",
    ".m": "Objective-C",
    ".php": "PHP",
    ".pl": "Perl",
    ".py": "Python",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".scala": "Scala",
    ".sh": "Shell",
    ".sql": "SQL",
    ".svelte": "Svelte",
    ".swift": "Swift",
    ".ts": "TypeScript",
    ".tsx": "TypeScript JSX",
    ".vue": "Vue",
}

JS_IMPORT_RE = re.compile(
    r"(?:\bimport\s+(?:[^;\n]*?\s+from\s+)?|\bexport\s+[^;\n]*?\s+from\s+|"
    r"\brequire\s*\(\s*|\bimport\s*\(\s*)"
    r"[\"']([^\"']+)[\"']"
)

# This intentionally favors precision over parsing every language dialect.
GENERIC_SYMBOL_PATTERNS = (
    re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", re.M),
    re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)", re.M),
    re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)", re.M),
    re.compile(r"^\s*(?:public\s+)?(?:final\s+)?(?:data\s+)?class\s+([A-Za-z_]\w*)", re.M),
    re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)", re.M),
    re.compile(r"^\s*def\s+([A-Za-z_]\w*)", re.M),
)


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _is_binary(path: Path) -> bool:
    try:
        sample = path.read_bytes()[:8192]
    except OSError:
        return True
    if b"\x00" in sample:
        return True
    if not sample:
        return False
    control_bytes = sum(byte < 9 or 13 < byte < 32 for byte in sample)
    return control_bytes / len(sample) > 0.30


def _first_doc_line(node: ast.AST) -> str | None:
    docstring = ast.get_docstring(node, clean=True)
    if not docstring:
        return None
    return " ".join(docstring.splitlines()[0].split())


def _python_metadata(
    text: str,
) -> tuple[list[str], list[str], str | None, list[str], list[str], list[str]]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, TypeError):
        return [], [], None, [], [], []

    symbols = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    imports: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            module = node.module or ""
            if module:
                imports.append(f"{prefix}{module}")
            else:
                # ``from . import sessions`` semantically imports ``.sessions``;
                # retaining only "." destroys the dependency edge downstream.
                imports.extend(f"{prefix}{alias.name}" for alias in node.names)

    class_summaries: list[str] = []
    top_level_functions: list[str] = []
    symbol_docs: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = [
                child
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            # Public API names are usually stronger embedding terms than
            # constructors and protocol helpers, so preserve them first.
            methods.sort(key=lambda method: method.name.startswith("_"))
            method_names = [method.name for method in methods]
            class_summaries.append(
                f"{node.name}({', '.join(method_names)})" if method_names else node.name
            )
            class_doc = _first_doc_line(node)
            if class_doc:
                symbol_docs.append(f"{node.name}: {class_doc}")
            for method in methods:
                method_doc = _first_doc_line(method)
                if method_doc:
                    symbol_docs.append(f"{node.name}.{method.name}: {method_doc}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            top_level_functions.append(node.name)
            function_doc = _first_doc_line(node)
            if function_doc:
                symbol_docs.append(f"{node.name}: {function_doc}")

    return (
        _unique(symbols),
        _unique(imports),
        ast.get_docstring(tree, clean=True),
        class_summaries,
        top_level_functions,
        symbol_docs,
    )


def _generic_symbols(text: str) -> list[str]:
    symbols: list[str] = []
    for pattern in GENERIC_SYMBOL_PATTERNS:
        symbols.extend(pattern.findall(text))
    return _unique(symbols)


def _make_signature(
    path: str,
    docstring: str | None,
    symbols: list[str],
    class_summaries: list[str] | None = None,
    top_level_functions: list[str] | None = None,
    symbol_docs: list[str] | None = None,
) -> str:
    parts = [f"Path: {path}"]
    if docstring:
        compact_docstring = " ".join(docstring.split())[:200].rstrip()
        parts.append(f"Module: {compact_docstring}")
    if class_summaries:
        parts.append(f"Classes: {'; '.join(class_summaries)}")
    if top_level_functions:
        parts.append(f"Functions: {', '.join(top_level_functions)}")
    elif symbols and not class_summaries:
        parts.append(f"Symbols: {', '.join(symbols)}")
    if symbol_docs:
        parts.append(f"Docs: {'; '.join(symbol_docs)}")
    signature = " | ".join(parts)
    if len(signature) <= MAX_SIGNATURE_LENGTH:
        return signature
    return signature[: MAX_SIGNATURE_LENGTH - 1].rstrip() + "…"


def _build_unit(path: Path, root: Path) -> dict[str, Any] | None:
    extension = path.suffix.lower()
    language = LANGUAGES.get(extension)
    if language is None or path.name.lower() in SKIP_FILES:
        return None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size > MAX_FILE_SIZE or _is_binary(path):
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    relative_path = path.relative_to(root).as_posix()
    docstring: str | None = None
    class_summaries: list[str] = []
    top_level_functions: list[str] = []
    symbol_docs: list[str] = []
    if extension == ".py":
        (
            symbols,
            imports,
            docstring,
            class_summaries,
            top_level_functions,
            symbol_docs,
        ) = _python_metadata(text)
    else:
        symbols = _generic_symbols(text)
        imports = _unique(JS_IMPORT_RE.findall(text)) if extension in {".js", ".jsx", ".ts", ".tsx"} else []

    return {
        "path": relative_path,
        "language": language,
        "size_bytes": size,
        "loc": sum(1 for line in text.splitlines() if line.strip()),
        "symbols": symbols,
        "imports": imports,
        "signature": _make_signature(
            relative_path,
            docstring,
            symbols,
            class_summaries,
            top_level_functions,
            symbol_docs,
        ),
    }


def build_index(repo_path: str) -> dict[str, Any]:
    """Return a deterministic index of eligible source files in *repo_path*.

    Raises:
        FileNotFoundError: if the supplied path does not exist.
        NotADirectoryError: if the supplied path is not a directory.
    """

    root = Path(repo_path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Repository does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Repository path is not a directory: {root}")

    units: list[dict[str, Any]] = []
    for path in root.rglob("*"):
        try:
            relative_parts = path.relative_to(root).parts
        except ValueError:
            continue
        if any(part in SKIP_DIRECTORIES for part in relative_parts):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        unit = _build_unit(path, root)
        if unit is not None:
            units.append(unit)

    units.sort(key=lambda unit: unit["path"])
    return {
        "repo_path": str(root),
        "unit_count": len(units),
        "total_loc": sum(unit["loc"] for unit in units),
        "units": units,
    }
