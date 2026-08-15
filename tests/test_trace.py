from __future__ import annotations

from pathlib import Path

import pytest

from scotoma.agent import RepositoryTools
from scotoma.trace import TraceRecorder


def test_trace_keeps_highest_examination_depth() -> None:
    recorder = TraceRecorder(question="q", repo_path="/repo", model="model")
    recorder.examine("app.py", 0.25)
    recorder.examine("app.py", 0.05)
    recorder.examine("app.py", 1.0)

    assert recorder.finish("answer")["examined"] == {"app.py": 1.0}


def test_repository_tools_record_depths_and_block_escape(tmp_path: Path) -> None:
    (tmp_path / "small.py").write_text("def target():\n    return 'needle'\n", encoding="utf-8")
    (tmp_path / "large.py").write_text("# needle\n" + "x = 1\n" * 2_000, encoding="utf-8")
    recorder = TraceRecorder(question="q", repo_path=str(tmp_path), model="model")
    tools = RepositoryTools(str(tmp_path), recorder)

    tools.list_files(".")
    assert recorder.examined["small.py"] == 0.05
    tools.search("needle")
    assert recorder.examined["small.py"] == 0.25
    tools.read_file("small.py")
    tools.read_file("large.py")

    assert recorder.examined["small.py"] == 1.0
    assert recorder.examined["large.py"] == 0.60
    with pytest.raises(ValueError, match="escapes"):
        tools.read_file("../outside.py")
