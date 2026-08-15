"""Explainable relevance, coverage, and blind-spot ranking for agent traces."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import deque
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
from openai import OpenAI

EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_CACHE_PATH = "embeddings_cache.json"
SOURCE_ROOTS = {"src", "lib", "python"}
STOPWORDS = {
    "about", "after", "again", "against", "also", "and", "any", "are",
    "because", "been", "before", "being", "between", "both", "but", "can",
    "could", "did", "does", "each", "for", "from", "had", "has", "have",
    "how", "into", "its", "may", "might", "not", "our", "should", "that",
    "the", "their", "then", "there", "these", "they", "this", "through",
    "was", "were", "what", "when", "where", "which", "while", "who", "why",
    "will", "with", "would", "your",
}
# Underscores are separators so ``test_session_interface`` contributes three
# lexical terms instead of one opaque identifier.
WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9]+")

SEMANTIC_WEIGHT = 0.40
STRUCTURAL_WEIGHT = 0.25
LEXICAL_WEIGHT = 0.35


def _cache_key(text: str, model: str = EMBEDDING_MODEL) -> str:
    return hashlib.sha256(f"{model}\0{text}".encode("utf-8")).hexdigest()


def _load_cache(path: Path) -> dict[str, list[float]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def embed_texts(
    texts: list[str],
    cache_path: str = DEFAULT_CACHE_PATH,
    model: str = EMBEDDING_MODEL,
) -> tuple[list[list[float]], int]:
    """Embed texts with a persistent model-aware cache.

    Returns the vectors and the number of embedding API requests made. Missing
    texts are batched, so a fresh coverage run normally makes one request and a
    repeat run makes zero.
    """

    path = Path(cache_path).expanduser()
    cache = _load_cache(path)
    keys = [_cache_key(text, model) for text in texts]
    missing: list[tuple[str, str]] = []
    seen_missing: set[str] = set()
    for key, text in zip(keys, texts, strict=True):
        if key not in cache and key not in seen_missing:
            missing.append((key, text))
            seen_missing.add(key)

    api_calls = 0
    if missing:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for uncached embeddings")
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        # Keep batches comfortably below provider input-count and token limits.
        for offset in range(0, len(missing), 100):
            batch = missing[offset : offset + 100]
            response = client.embeddings.create(model=model, input=[text for _, text in batch])
            api_calls += 1
            ordered = sorted(response.data, key=lambda item: item.index)
            if len(ordered) != len(batch):
                raise RuntimeError("Embedding API returned an unexpected vector count")
            for (key, _), item in zip(batch, ordered, strict=True):
                cache[key] = item.embedding
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, separators=(",", ":")) + "\n", encoding="utf-8")

    return [cache[key] for key in keys], api_calls


def _cosine_scores(question_vector: list[float], unit_vectors: list[list[float]]) -> list[float]:
    question = np.asarray(question_vector, dtype=float)
    units = np.asarray(unit_vectors, dtype=float)
    question_norm = np.linalg.norm(question)
    unit_norms = np.linalg.norm(units, axis=1)
    denominators = unit_norms * question_norm
    raw = np.divide(
        units @ question,
        denominators,
        out=np.zeros(len(units), dtype=float),
        where=denominators != 0,
    )
    minimum = float(raw.min())
    maximum = float(raw.max())
    if math.isclose(minimum, maximum):
        return [1.0 if maximum > 0 else 0.0 for _ in raw]
    return [float((score - minimum) / (maximum - minimum)) for score in raw]


def _module_aliases(path: str) -> set[str]:
    pure = PurePosixPath(path)
    if pure.suffix != ".py":
        return set()
    parts = list(pure.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    aliases = {".".join(parts)} if parts else set()
    if parts and parts[0] in SOURCE_ROOTS and len(parts) > 1:
        aliases.add(".".join(parts[1:]))
    return aliases


def _python_relative_target(importer: str, imported: str) -> list[str]:
    level = len(imported) - len(imported.lstrip("."))
    module = imported[level:]
    importer_path = PurePosixPath(importer)
    base = importer_path.parent
    for _ in range(max(0, level - 1)):
        base = base.parent
    module_parts = [part for part in module.split(".") if part]
    target = base.joinpath(*module_parts)
    return [f"{target.as_posix()}.py", f"{target.as_posix()}/__init__.py"]


def _resolve_import(importer: str, imported: str, paths: set[str], aliases: dict[str, str]) -> str | None:
    if imported.startswith(".") and importer.endswith(".py"):
        for candidate in _python_relative_target(importer, imported):
            if candidate in paths:
                return candidate
        return None
    if importer.endswith(".py"):
        parts = imported.split(".")
        for end in range(len(parts), 0, -1):
            candidate = aliases.get(".".join(parts[:end]))
            if candidate:
                return candidate
    if imported.startswith("."):
        base = PurePosixPath(importer).parent.joinpath(imported)
        for suffix in ("", ".js", ".jsx", ".ts", ".tsx"):
            candidate = f"{base.as_posix()}{suffix}"
            if candidate in paths:
                return candidate
    return None


def build_dependency_graph(units: list[dict[str, Any]]) -> dict[str, set[str]]:
    paths = {unit["path"] for unit in units}
    aliases: dict[str, str] = {}
    for path in sorted(paths):
        for alias in _module_aliases(path):
            aliases.setdefault(alias, path)
    graph = {path: set() for path in paths}
    for unit in units:
        for imported in unit.get("imports", []):
            target = _resolve_import(unit["path"], imported, paths, aliases)
            if target and target != unit["path"]:
                graph[unit["path"]].add(target)
                graph[target].add(unit["path"])
    return graph


def structural_scores(
    units: list[dict[str, Any]], examined: dict[str, float]
) -> tuple[dict[str, float], int]:
    graph = build_dependency_graph(units)
    seeds = [path for path, depth in examined.items() if depth >= 0.5 and path in graph]
    distances: dict[str, int] = {path: 0 for path in seeds}
    queue = deque(seeds)
    while queue:
        current = queue.popleft()
        if distances[current] >= 3:
            continue
        for neighbor in graph[current]:
            if neighbor not in distances:
                distances[neighbor] = distances[current] + 1
                queue.append(neighbor)
    scores = {
        unit["path"]: (0.5 ** distances[unit["path"]] if unit["path"] in distances else 0.0)
        for unit in units
    }
    edge_count = sum(len(neighbors) for neighbors in graph.values()) // 2
    return scores, edge_count


def _question_words(question: str) -> set[str]:
    return {
        _normalize_word(word)
        for word in WORD_RE.findall(question.lower())
        if len(word) >= 3 and word not in STOPWORDS
    }


def _normalize_word(word: str) -> str:
    """Apply deliberately small morphology rules without conflating sign/signal."""

    word = word.lower()
    if len(word) > 5 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 4 and word.endswith("ed"):
        return word[:-2]
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def lexical_score(question_words: set[str], unit: dict[str, Any]) -> float:
    if not question_words:
        return 0.0
    haystack = " ".join(
        [unit["path"], *unit.get("symbols", []), unit.get("signature", "")]
    ).lower()
    unit_words = {_normalize_word(word) for word in WORD_RE.findall(haystack)}
    return len(question_words & unit_words) / len(question_words)


def calculate_coverage(
    index: dict[str, Any],
    trace: dict[str, Any],
    cache_path: str = DEFAULT_CACHE_PATH,
) -> dict[str, Any]:
    units = index["units"]
    texts = [trace["question"], *[unit["signature"] for unit in units]]
    vectors, api_calls = embed_texts(texts, cache_path=cache_path)
    semantic = _cosine_scores(vectors[0], vectors[1:])
    structural, edge_count = structural_scores(units, trace.get("examined", {}))
    words = _question_words(trace["question"])

    results: list[dict[str, Any]] = []
    numerator = 0.0
    denominator = 0.0
    for unit, sem in zip(units, semantic, strict=True):
        struct = structural[unit["path"]]
        lex = lexical_score(words, unit)
        relevance = (
            SEMANTIC_WEIGHT * sem
            + STRUCTURAL_WEIGHT * struct
            + LEXICAL_WEIGHT * lex
        )
        depth = float(trace.get("examined", {}).get(unit["path"], 0.0))
        blind_risk = relevance * (1.0 - depth)
        numerator += relevance * depth
        denominator += relevance
        results.append(
            {
                "path": unit["path"],
                "sem": round(sem, 6),
                "struct": round(struct, 6),
                "lex": round(lex, 6),
                "relevance": round(relevance, 6),
                "depth": depth,
                "blind_risk": round(blind_risk, 6),
            }
        )
    rwc = numerator / denominator if denominator else 0.0
    results.sort(key=lambda unit: (-unit["blind_risk"], unit["path"]))
    examined_count = sum(path in trace.get("examined", {}) for path in (unit["path"] for unit in units))
    return {
        "rwc": round(rwc, 8),
        "rwc_percent": round(rwc * 100, 2),
        "naive_file_coverage": round(examined_count / len(units), 8) if units else 0.0,
        "naive_file_coverage_percent": round(examined_count / len(units) * 100, 2) if units else 0.0,
        "examined_unit_count": examined_count,
        "unit_count": len(units),
        "embedding_model": EMBEDDING_MODEL,
        "weights": {
            "semantic": SEMANTIC_WEIGHT,
            "structural": STRUCTURAL_WEIGHT,
            "lexical": LEXICAL_WEIGHT,
        },
        "embedding_api_calls": api_calls,
        "dependency_edges": edge_count,
        "structural_nonzero_units": sum(score > 0 for score in structural.values()),
        "units": results,
    }
