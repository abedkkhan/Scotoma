import json

from scotoma.transcript import parse_transcript


def _jsonl(*events: dict) -> bytes:
    return "\n".join(json.dumps(event) for event in events).encode()


def test_parses_claude_code_reads_and_answer() -> None:
    raw = _jsonl(
        {"type": "user", "message": {"content": "Is authentication safe?"}},
        {
            "type": "assistant",
            "message": {
                "model": "claude-sonnet-4",
                "content": [
                    {"type": "tool_use", "name": "Read", "input": {"file_path": "/work/repo/src/auth.py"}}
                ],
            },
        },
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Authentication is safe."}]}},
    )
    trace = parse_transcript(raw, "/server/repo", ["src/auth.py"], vendor="claude-code")
    assert trace["question"] == "Is authentication safe?"
    assert trace["answer"] == "Authentication is safe."
    assert trace["model"] == "claude-sonnet-4"
    assert trace["examined"] == {"src/auth.py": 1.0}
    assert trace["source"]["imported"] is True


def test_partial_read_keeps_truncated_depth() -> None:
    raw = _jsonl(
        {"type": "user", "message": {"content": "Explain sessions"}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "src/sessions.py", "limit": 200}}
        ]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Sessions are signed."}]}},
    )
    trace = parse_transcript(raw, "/repo", ["src/sessions.py"], vendor="claude-code")
    assert trace["examined"] == {"src/sessions.py": 0.6}


def test_reports_claude_login_failure() -> None:
    raw = _jsonl({"type": "result", "is_error": True, "result": "Not logged in · Please run /login"})
    try:
        parse_transcript(raw, "/repo", ["app.py"], vendor="claude-code")
    except ValueError as error:
        assert "not logged in" in str(error).lower()
    else:
        raise AssertionError("Expected login failure")


def test_parses_codex_response_items_and_exec_calls() -> None:
    raw = _jsonl(
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Can coverage be gamed?"}]}},
        {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "input": "{\"cmd\":\"sed -n '1,200p' scotoma/rank.py\"}"}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Grepping alone receives partial depth."}]}},
    )
    trace = parse_transcript(raw, "/repo", ["scotoma/rank.py"], vendor="codex")
    assert trace["question"] == "Can coverage be gamed?"
    assert trace["answer"] == "Grepping alone receives partial depth."
    assert trace["examined"] == {"scotoma/rank.py": 0.6}
