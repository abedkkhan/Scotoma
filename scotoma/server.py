"""Hosted API for running Scotoma audits from the static frontend."""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .adjudicate import adjudicate, run_flip
from .agent import run_agent
from .index import build_index
from .rank import calculate_coverage

MAX_FILES = int(os.environ.get("SCOTOMA_MAX_FILES", "1500"))
MAX_UPLOAD_BYTES = int(os.environ.get("SCOTOMA_MAX_UPLOAD_BYTES", str(30 * 1024 * 1024)))
MAX_FILE_BYTES = int(os.environ.get("SCOTOMA_MAX_FILE_BYTES", str(400 * 1024)))
MAX_CONCURRENT_JOBS = int(os.environ.get("SCOTOMA_MAX_CONCURRENT_JOBS", "2"))
CACHE_ROOT = Path(os.environ.get("SCOTOMA_CACHE_DIR", "/tmp/scotoma-cache"))
WORK_ROOT = Path(os.environ.get("SCOTOMA_WORK_DIR", "/tmp/scotoma-jobs"))

DEFAULT_ORIGINS = [
    "https://abedkkhan.github.io",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]
ALLOWED_ORIGINS = [
    value.strip()
    for value in os.environ.get("SCOTOMA_ALLOWED_ORIGINS", ",".join(DEFAULT_ORIGINS)).split(",")
    if value.strip()
]

app = FastAPI(
    title="Scotoma API",
    description="Measure what an AI agent did not investigate before answering.",
    version="0.2.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Scotoma-Token"],
)

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_JOBS, thread_name_prefix="scotoma-audit")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _authorize(x_scotoma_token: Annotated[str | None, Header()] = None) -> None:
    expected = os.environ.get("SCOTOMA_ACCESS_TOKEN")
    if expected and x_scotoma_token != expected:
        raise HTTPException(status_code=401, detail="A valid Scotoma access token is required")


def _safe_relative(raw_path: str) -> PurePosixPath:
    normalized = raw_path.replace("\\", "/").strip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts or "\x00" in normalized:
        raise HTTPException(status_code=400, detail=f"Unsafe repository path: {raw_path!r}")
    if len(normalized) > 500:
        raise HTTPException(status_code=400, detail="Repository path is too long")
    return path


def _strip_common_root(paths: list[PurePosixPath]) -> list[PurePosixPath]:
    if not paths or any(len(path.parts) < 2 for path in paths):
        return paths
    first = paths[0].parts[0]
    if all(path.parts[0] == first for path in paths):
        return [PurePosixPath(*path.parts[1:]) for path in paths]
    return paths


async def _save_uploads(files: list[UploadFile], paths: list[str], destination: Path) -> int:
    if not files or len(files) != len(paths):
        raise HTTPException(status_code=400, detail="Each uploaded file must have one matching path")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=413, detail=f"Repository exceeds {MAX_FILES} uploaded files")
    safe_paths = _strip_common_root([_safe_relative(path) for path in paths])
    total = 0
    for upload, relative in zip(files, safe_paths, strict=True):
        target = destination.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        try:
            with target.open("wb") as output:
                while chunk := await upload.read(64 * 1024):
                    written += len(chunk)
                    total += len(chunk)
                    if written > MAX_FILE_BYTES:
                        raise HTTPException(status_code=413, detail=f"File too large: {relative}")
                    if total > MAX_UPLOAD_BYTES:
                        raise HTTPException(status_code=413, detail="Repository upload is too large")
                    output.write(chunk)
        finally:
            await upload.close()
    return total


def _update_job(job_id: str, **values: Any) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(values, updated_at=_now())


def _run_pipeline(job_id: str, repo_path: Path, question: str) -> None:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        _update_job(job_id, status="running", stage="indexing", progress=10)
        index = build_index(str(repo_path))
        if not index["units"]:
            raise ValueError("No supported source files were found in the uploaded repository")

        _update_job(job_id, stage="agent", progress=25, unit_count=index["unit_count"])
        trace = run_agent(str(repo_path), question)

        _update_job(job_id, stage="coverage", progress=48)
        coverage = calculate_coverage(
            index, trace, cache_path=str(CACHE_ROOT / "embeddings_cache.json")
        )

        _update_job(job_id, stage="adjudication", progress=68)
        adjudication = adjudicate(
            index,
            trace,
            coverage,
            cache_path=str(CACHE_ROOT / "adjudication_cache.json"),
        )

        _update_job(job_id, stage="flip", progress=88)
        flip = run_flip(
            adjudication, cache_path=str(CACHE_ROOT / "adjudication_cache.json")
        )

        _update_job(
            job_id,
            status="complete",
            stage="complete",
            progress=100,
            result={
                "index": index,
                "trace": trace,
                "coverage": coverage,
                "adjudication": adjudication,
                "flip": flip,
            },
        )
    except Exception as error:  # job boundary: surface a stable message to polling clients
        _update_job(
            job_id,
            status="failed",
            stage="failed",
            error=f"{type(error).__name__}: {error}",
        )
    finally:
        shutil.rmtree(repo_path.parent, ignore_errors=True)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "scotoma",
        "openai_configured": bool(os.environ.get("OPENAI_API_KEY")),
        "max_files": MAX_FILES,
        "max_upload_bytes": MAX_UPLOAD_BYTES,
    }


@app.post("/api/audits", status_code=202, dependencies=[Depends(_authorize)])
async def create_audit(
    question: Annotated[str, Form(min_length=5, max_length=1000)],
    files: Annotated[list[UploadFile], File()],
    paths: Annotated[list[str], Form()],
) -> dict[str, Any]:
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="The server has no OpenAI API key configured")
    with _jobs_lock:
        active = sum(job["status"] in {"queued", "running"} for job in _jobs.values())
    if active >= MAX_CONCURRENT_JOBS:
        raise HTTPException(status_code=429, detail="Audit capacity is full; try again shortly")

    job_id = uuid.uuid4().hex
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    job_root = Path(tempfile.mkdtemp(prefix=f"{job_id}-", dir=WORK_ROOT))
    repo_path = job_root / "repo"
    repo_path.mkdir()
    try:
        upload_bytes = await _save_uploads(files, paths, repo_path)
    except Exception:
        shutil.rmtree(job_root, ignore_errors=True)
        raise

    job = {
        "id": job_id,
        "status": "queued",
        "stage": "queued",
        "progress": 0,
        "question": question,
        "file_count": len(files),
        "upload_bytes": upload_bytes,
        "created_at": _now(),
        "updated_at": _now(),
    }
    with _jobs_lock:
        _jobs[job_id] = job
    _executor.submit(_run_pipeline, job_id, repo_path, question)
    return job


@app.get("/api/audits/{job_id}", dependencies=[Depends(_authorize)])
def get_audit(job_id: str) -> dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Audit job not found")
        return dict(job)
