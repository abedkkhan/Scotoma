"""A small, deliberately bounded code-analysis agent with trace capture."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

from .index import build_index
from .trace import (
    DEPTH_LISTED,
    DEPTH_READ_FULL,
    DEPTH_READ_TRUNCATED,
    DEPTH_SEARCH_HIT,
    TraceRecorder,
)

DEFAULT_MODEL = "gpt-4o-mini"
MAX_READ_CHARS = 8_000
MAX_SEARCH_HITS = 40

SYSTEM_PROMPT = """You are a helpful code-analysis assistant. Answer the user's
question by inspecting the repository with the available tools. Be concise but
technically specific. Base claims on code you actually observe. Do not invent
file contents or APIs."""

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List source files recursively under a repository subdirectory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subdir": {
                        "type": "string",
                        "description": "Repo-relative directory, or '.' for the root.",
                    }
                },
                "required": ["subdir"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 source file. Large files are truncated to 8000 characters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Repo-relative file path."}
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Regex-search source files; returns at most 40 path:line:text hits.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Python regular expression."}
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
        },
    },
]


class RepositoryTools:
    """Safe repository tools that update a trace recorder."""

    def __init__(self, repo_path: str, recorder: TraceRecorder) -> None:
        self.root = Path(repo_path).expanduser().resolve()
        self.recorder = recorder
        self.index = build_index(str(self.root))
        self.units = {unit["path"]: unit for unit in self.index["units"]}

    def _resolve(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("Path escapes repository root")
        return candidate

    def list_files(self, subdir: str) -> tuple[str, str]:
        directory = self._resolve(subdir or ".")
        if not directory.is_dir():
            raise ValueError(f"Not a directory: {subdir}")
        prefix = directory.relative_to(self.root).as_posix()
        paths = [
            path
            for path in self.units
            if prefix == "." or path == prefix or path.startswith(prefix.rstrip("/") + "/")
        ]
        for path in paths:
            self.recorder.examine(path, DEPTH_LISTED)
        result = "\n".join(paths) if paths else "No source files found."
        return result, f"Listed {len(paths)} source files under {subdir or '.'}"

    def read_file(self, path: str) -> tuple[str, str]:
        resolved = self._resolve(path)
        relative = resolved.relative_to(self.root).as_posix()
        if relative not in self.units:
            raise ValueError(f"Not an indexed source file: {path}")
        text = resolved.read_text(encoding="utf-8")
        truncated = len(text) > MAX_READ_CHARS
        result = text[:MAX_READ_CHARS]
        depth = DEPTH_READ_TRUNCATED if truncated else DEPTH_READ_FULL
        self.recorder.examine(relative, depth)
        suffix = " (truncated)" if truncated else ""
        return result, f"Read {len(result):,} characters from {relative}{suffix}"

    def search(self, pattern: str) -> tuple[str, str]:
        try:
            regex = re.compile(pattern)
        except re.error as error:
            raise ValueError(f"Invalid regex: {error}") from error

        hits: list[str] = []
        hit_files: set[str] = set()
        for relative in self.units:
            if len(hits) >= MAX_SEARCH_HITS:
                break
            resolved = self._resolve(relative)
            try:
                lines = resolved.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for line_number, line in enumerate(lines, start=1):
                if regex.search(line):
                    hits.append(f"{relative}:{line_number}: {line.strip()[:300]}")
                    hit_files.add(relative)
                    if len(hits) >= MAX_SEARCH_HITS:
                        break
        for relative in hit_files:
            self.recorder.examine(relative, DEPTH_SEARCH_HIT)
        result = "\n".join(hits) if hits else "No matches found."
        return result, f"Found {len(hits)} hits across {len(hit_files)} files"

    def execute(self, name: str, args: dict[str, Any]) -> tuple[str, str]:
        if name == "list_files":
            return self.list_files(str(args.get("subdir", ".")))
        if name == "read_file":
            return self.read_file(str(args.get("path", "")))
        if name == "search":
            return self.search(str(args.get("pattern", "")))
        raise ValueError(f"Unknown tool: {name}")


def _fallback_model(client: OpenAI, rejected_model: str) -> str:
    available = sorted(model.id for model in client.models.list().data)
    preferences = (
        "gpt-4.1-mini",
        "gpt-4o-mini",
        "gpt-4.1-nano",
        "gpt-5-mini",
    )
    for candidate in preferences:
        if candidate != rejected_model and candidate in available:
            return candidate
    small_models = [
        model
        for model in available
        if model.startswith("gpt-") and any(label in model for label in ("mini", "nano"))
    ]
    if small_models:
        return small_models[0]
    raise RuntimeError(f"No suitable small chat model is available; rejected {rejected_model!r}")


def _completion(client: OpenAI, model: str, messages: list[Any], *, tools: bool = True) -> Any:
    kwargs: dict[str, Any] = {"model": model, "messages": messages}
    if tools:
        kwargs.update({"tools": TOOL_SCHEMAS, "tool_choice": "auto"})
    return client.chat.completions.create(**kwargs)


def run_agent(
    repo_path: str,
    question: str,
    max_tool_calls: int = 12,
    preload_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Answer *question* with a bounded tool loop and return its full trace."""

    if max_tool_calls < 1:
        raise ValueError("max_tool_calls must be at least 1")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set")

    root = Path(repo_path).expanduser().resolve()
    requested_model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)
    recorder = TraceRecorder(question=question, repo_path=str(root), model=requested_model)
    repository_tools = RepositoryTools(str(root), recorder)
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    preload_sections: list[str] = []
    for relative in preload_paths or []:
        resolved = repository_tools._resolve(relative)
        normalized = resolved.relative_to(root).as_posix()
        if normalized not in repository_tools.units:
            raise ValueError(f"Cannot preload non-indexed source file: {relative}")
        content = resolved.read_text(encoding="utf-8")
        recorder.examine(normalized, DEPTH_READ_FULL)
        preload_sections.append(
            f"\n--- PRELOADED FILE: {normalized} ---\n{content}\n--- END FILE: {normalized} ---"
        )
    user_content = question
    if preload_sections:
        user_content += (
            "\n\nThe following repository files have already been read in full. "
            "Use them as primary evidence before using tools. Re-evaluate the "
            "question from scratch. For security questions, explicitly distinguish "
            "which properties the observed code provides: integrity, authenticity, "
            "confidentiality, serialization/encoding, and encryption. State whether "
            "serialized client-held data is readable when the evidence supports it:"
            + "".join(preload_sections)
        )
    messages: list[Any] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    model = requested_model
    try:
        response = _completion(client, model, messages)
    except Exception as original_error:
        try:
            model = _fallback_model(client, requested_model)
            recorder.model = model
            response = _completion(client, model, messages)
        except Exception:
            raise original_error

    calls_used = 0
    while True:
        message = response.choices[0].message
        messages.append(message)
        if not message.tool_calls:
            return recorder.finish(message.content or "")

        for tool_call in message.tool_calls:
            if calls_used >= max_tool_calls:
                tool_result = "Tool-call limit reached. No further repository access is allowed."
            else:
                try:
                    args = json.loads(tool_call.function.arguments or "{}")
                    if not isinstance(args, dict):
                        raise ValueError("Tool arguments must be a JSON object")
                    tool_result, summary = repository_tools.execute(tool_call.function.name, args)
                except (ValueError, OSError, json.JSONDecodeError) as error:
                    args = {}
                    tool_result = f"Tool error: {error}"
                    summary = tool_result
                recorder.record_tool(tool_call.function.name, args, summary)
                calls_used += 1
            messages.append(
                {"role": "tool", "tool_call_id": tool_call.id, "content": tool_result}
            )

        if calls_used >= max_tool_calls:
            messages.append(
                {
                    "role": "system",
                    "content": "You have reached the tool-call limit. Answer now using only the evidence already gathered.",
                }
            )
            response = _completion(client, model, messages, tools=False)
        else:
            response = _completion(client, model, messages)
