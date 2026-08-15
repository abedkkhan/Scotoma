from __future__ import annotations

from fastapi.testclient import TestClient

from scotoma.server import _safe_relative, _strip_common_root, app


def test_health_endpoint() -> None:
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json()["service"] == "scotoma"


def test_safe_relative_rejects_traversal() -> None:
    from fastapi import HTTPException
    import pytest

    with pytest.raises(HTTPException):
        _safe_relative("../../secret.txt")


def test_common_uploaded_root_is_removed() -> None:
    paths = [_safe_relative("repo/src/app.py"), _safe_relative("repo/tests/test_app.py")]

    assert [str(path) for path in _strip_common_root(paths)] == [
        "src/app.py",
        "tests/test_app.py",
    ]


def test_create_audit_accepts_repository_files_without_blocking(
    tmp_path, monkeypatch
) -> None:
    import scotoma.server as server

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(server, "WORK_ROOT", tmp_path)
    monkeypatch.setattr(server._executor, "submit", lambda *args, **kwargs: None)
    server._jobs.clear()

    response = TestClient(app).post(
        "/api/audits",
        files=[
            ("question", (None, "Could authentication be bypassed?")),
            ("paths", (None, "sample/src/app.py")),
            ("files", ("app.py", b"def login():\n    return True\n", "text/x-python")),
        ],
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["file_count"] == 1
