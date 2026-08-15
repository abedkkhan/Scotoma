from __future__ import annotations

from pathlib import Path

from scotoma.index import MAX_SIGNATURE_LENGTH, build_index


def test_build_index_extracts_python_and_typescript_metadata(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        '"""A small application module."""\n'
        "import os\n"
        "from .db import query\n\n"
        "class App:\n    pass\n\n"
        "async def run():\n    return os.getcwd()\n",
        encoding="utf-8",
    )
    (tmp_path / "route.ts").write_text(
        "import { db } from './db';\n"
        "const util = require('./util');\n"
        "export async function search() { return db.query('x'); }\n",
        encoding="utf-8",
    )

    result = build_index(str(tmp_path))
    units = {unit["path"]: unit for unit in result["units"]}

    assert result["unit_count"] == 2
    assert units["app.py"]["symbols"] == ["App", "run"]
    assert units["app.py"]["imports"] == ["os", ".db"]
    assert "App" in units["app.py"]["signature"]
    assert units["route.ts"]["imports"] == ["./db", "./util"]
    assert "search" in units["route.ts"]["symbols"]
    assert all(len(unit["signature"]) <= MAX_SIGNATURE_LENGTH for unit in units.values())


def test_build_index_skips_excluded_binary_and_oversized_files(tmp_path: Path) -> None:
    (tmp_path / "good.py").write_text("def good():\n    return True\n", encoding="utf-8")
    skipped = tmp_path / "node_modules"
    skipped.mkdir()
    (skipped / "ignored.js").write_text("function ignored() {}\n", encoding="utf-8")
    (tmp_path / "binary.py").write_bytes(b"def fake():\x00nope")
    (tmp_path / "huge.py").write_text("x" * (401 * 1024), encoding="utf-8")
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")

    result = build_index(str(tmp_path))

    assert [unit["path"] for unit in result["units"]] == ["good.py"]


def test_parse_errors_do_not_crash(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    result = build_index(str(tmp_path))

    assert result["units"][0]["symbols"] == []
    assert result["units"][0]["imports"] == []


def test_python_class_methods_enrich_signature_but_not_top_level_symbols(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text(
        "class Service:\n"
        "    def __init__(self):\n        pass\n\n"
        "    def search_users(self):\n        pass\n\n"
        "    async def execute_query(self):\n        pass\n\n"
        "    def _internal(self):\n        pass\n",
        encoding="utf-8",
    )

    unit = build_index(str(tmp_path))["units"][0]

    assert unit["symbols"] == ["Service"]
    assert "Service(search_users, execute_query" in unit["signature"]
    assert unit["signature"].index("search_users") < unit["signature"].index("__init__")
