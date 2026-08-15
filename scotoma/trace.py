"""Normalized, vendor-neutral trace primitives for agent investigations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEPTH_LISTED = 0.05
DEPTH_SEARCH_HIT = 0.25
DEPTH_READ_TRUNCATED = 0.60
DEPTH_READ_FULL = 1.00


@dataclass
class TraceRecorder:
    """Accumulate a normalized trace while preserving maximum seen depth."""

    question: str
    repo_path: str
    model: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    examined: dict[str, float] = field(default_factory=dict)

    def examine(self, path: str, depth: float) -> None:
        self.examined[path] = max(depth, self.examined.get(path, 0.0))

    def record_tool(self, tool: str, args: dict[str, Any], result_summary: str) -> None:
        self.tool_calls.append(
            {"tool": tool, "args": args, "result_summary": result_summary}
        )

    def finish(self, answer: str) -> dict[str, Any]:
        return {
            "question": self.question,
            "repo_path": self.repo_path,
            "answer": answer,
            "model": self.model,
            "tool_calls": self.tool_calls,
            "examined": dict(sorted(self.examined.items())),
        }
