"""Normalize Claude Code and Codex JSONL sessions into Scotoma traces."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .trace import (
    DEPTH_LISTED,
    DEPTH_READ_FULL,
    DEPTH_READ_TRUNCATED,
    DEPTH_SEARCH_HIT,
    TraceRecorder,
)

_PATH = re.compile(r"(?:^|[\s'\"`])((?:[\w.@+-]+/)+[\w.@+(), -]+\.[A-Za-z0-9]+)")
_READ_NAMES = {"read", "read_file", "readfile"}
_SEARCH_NAMES = {"grep", "search", "ripgrep", "rg"}
_LIST_NAMES = {"glob", "list", "list_files", "find"}


def _events(raw: bytes) -> list[dict[str, Any]]:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        raise ValueError("The session log is empty")
    try:
        value = json.loads(text)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return value.get("events", [value])
    except json.JSONDecodeError:
        pass
    parsed = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSONL on line {number}: {error.msg}") from error
        if isinstance(item, dict):
            parsed.append(item)
    return parsed


def _content(event: dict[str, Any]) -> Any:
    message = event.get("message")
    if isinstance(message, dict):
        return message.get("content")
    payload = event.get("payload")
    if isinstance(payload, dict) and isinstance(payload.get("message"), dict):
        return payload["message"].get("content")
    return event.get("content")


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") in {"text", "output_text", "input_text"}
        ).strip()
    return ""


def _relative_path(value: Any, repo_path: str) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.replace("\\", "/").strip().strip("'\"`")
    root = str(Path(repo_path).resolve()).replace("\\", "/").rstrip("/")
    if candidate.startswith(root + "/"):
        candidate = candidate[len(root) + 1 :]
    # Absolute paths in local transcripts will not share the temporary server
    # root. Preserve their suffix so it can be matched against indexed paths.
    candidate = str(PurePosixPath(candidate)).lstrip("./")
    return candidate if candidate and candidate != "." else None


def _reconcile(path: str, known: set[str]) -> str | None:
    if path in known:
        return path
    matches = [item for item in known if item.endswith("/" + path) or path.endswith("/" + item)]
    if len(matches) == 1:
        return matches[0]
    basename = PurePosixPath(path).name
    matches = [item for item in known if PurePosixPath(item).name == basename]
    return matches[0] if len(matches) == 1 else None


def _tool_blocks(event: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any], str]]:
    content = _content(event)
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict) or block.get("type") not in {"tool_use", "function_call"}:
                continue
            yield str(block.get("name", "")), block.get("input") or block.get("arguments") or {}, ""
    item = event.get("item") or event.get("payload")
    if isinstance(item, dict) and item.get("type") in {"function_call", "tool_call"}:
        args = item.get("arguments") or item.get("input") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"raw": args}
        yield str(item.get("name", "")), args, ""


def parse_transcript(
    raw: bytes,
    repo_path: str,
    indexed_paths: Iterable[str],
    question: str | None = None,
    vendor: str = "auto",
) -> dict[str, Any]:
    """Parse a Claude Code/Codex session and return a normalized trace."""
    events = _events(raw)
    known = set(indexed_paths)
    user_texts: list[str] = []
    assistant_texts: list[str] = []
    model = vendor if vendor != "auto" else "imported-agent"
    tools: list[tuple[str, dict[str, Any], str]] = []
    for event in events:
        role = event.get("type") or event.get("role")
        content_text = _text(_content(event))
        if role in {"user", "input", "user_message"} and content_text:
            user_texts.append(content_text)
        if role in {"assistant", "output", "assistant_message"} and content_text:
            assistant_texts.append(content_text)
        message = event.get("message")
        if isinstance(message, dict):
            model = message.get("model") or model
        tools.extend(_tool_blocks(event))

    result_texts = [str(event.get("result", "")).strip() for event in events if event.get("result")]
    failure = next(
        (text for text in result_texts if "not logged in" in text.lower()),
        None,
    )
    if failure:
        raise ValueError(f"Claude Code session did not run: {failure}")

    resolved_question = (question or (user_texts[0] if user_texts else "Imported agent investigation")).strip()
    answer = assistant_texts[-1].strip() if assistant_texts else (result_texts[-1] if result_texts else "")
    if not answer:
        raise ValueError("No final agent answer was found in the uploaded session log")
    recorder = TraceRecorder(resolved_question, repo_path, str(model))
    for name, args, summary in tools:
        lowered = name.lower().split(".")[-1]
        values = [args.get(key) for key in ("file_path", "path", "filename")]
        raw_path = next((value for value in values if isinstance(value, str)), None)
        if lowered in _READ_NAMES and raw_path:
            path = _relative_path(raw_path, repo_path)
            matched = _reconcile(path, known) if path else None
            if matched:
                truncated = any(key in args for key in ("limit", "offset", "line_end"))
                recorder.examine(matched, DEPTH_READ_TRUNCATED if truncated else DEPTH_READ_FULL)
        elif lowered in _SEARCH_NAMES | _LIST_NAMES:
            serialized = json.dumps(args, ensure_ascii=False)
            hits = {_reconcile(match, known) for match in _PATH.findall(serialized + " " + summary)}
            depth = DEPTH_SEARCH_HIT if lowered in _SEARCH_NAMES else DEPTH_LISTED
            for hit in hits - {None}:
                recorder.examine(hit, depth)
        recorder.record_tool(name, args, summary or "Imported from session log")
    trace = recorder.finish(answer)
    trace["source"] = {"vendor": vendor, "event_count": len(events), "imported": True}
    return trace
