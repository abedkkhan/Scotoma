from __future__ import annotations

from scotoma.rank import build_dependency_graph, lexical_score, structural_scores


def _unit(path: str, imports: list[str], signature: str = "") -> dict:
    return {"path": path, "imports": imports, "symbols": [], "signature": signature}


def test_python_relative_imports_create_undirected_edges() -> None:
    units = [
        _unit("src/pkg/app.py", [".sessions", ".missing"]),
        _unit("src/pkg/sessions.py", [".security"]),
        _unit("src/pkg/security.py", []),
    ]

    graph = build_dependency_graph(units)

    assert graph["src/pkg/app.py"] == {"src/pkg/sessions.py"}
    assert graph["src/pkg/sessions.py"] == {"src/pkg/app.py", "src/pkg/security.py"}


def test_structural_scores_stop_after_three_hops() -> None:
    units = [
        _unit("src/pkg/a.py", [".b"]),
        _unit("src/pkg/b.py", [".c"]),
        _unit("src/pkg/c.py", [".d"]),
        _unit("src/pkg/d.py", [".e"]),
        _unit("src/pkg/e.py", []),
    ]

    scores, edge_count = structural_scores(units, {"src/pkg/a.py": 0.6})

    assert edge_count == 4
    assert scores["src/pkg/a.py"] == 1.0
    assert scores["src/pkg/b.py"] == 0.5
    assert scores["src/pkg/d.py"] == 0.125
    assert scores["src/pkg/e.py"] == 0.0


def test_lexical_overlap_uses_question_word_fraction() -> None:
    unit = _unit("src/session/security.py", [], "validate signed session cookie")

    assert lexical_score({"session", "cookie", "bypass", "flask"}, unit) == 0.5


def test_lexical_overlap_does_not_confuse_sign_with_signals() -> None:
    unit = _unit("src/flask/signals.py", [], "application signals and hooks")

    assert lexical_score({"sign", "session"}, unit) == 0.0
