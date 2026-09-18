from __future__ import annotations

from app.core.exception_diagnostics import (
    format_exception_diagnostics,
    sanitize_diagnostic_text,
)
from app.modules.system.application.projections import (
    serialize_system_event,
    summarize_diagnostic_metadata,
)
from app.modules.system.domain.events import (
    prepare_event_metadata,
    truncate_event_message,
)


def test_sanitize_redacts_credentials_and_sql_parameters() -> None:
    text = (
        "Authorization: Bearer abc123\n"
        "Cookie: shuku_session=deadbeef\n"
        "password=hunter2 token=xyz api_key=sekret\n"
        "[parameters: ('a@example.com', 'hunter2')]\n"
        "(Background on this error at: https://sqlalche.me/e/20/abc)"
    )

    cleaned = sanitize_diagnostic_text(text)

    assert "abc123" not in cleaned
    assert "deadbeef" not in cleaned
    assert "hunter2" not in cleaned
    assert "xyz" not in cleaned
    assert "sekret" not in cleaned
    assert "[parameters: [redacted]]" in cleaned
    assert "Background on this error" not in cleaned


def _raise_marker() -> None:
    raise ValueError("boom-marker")


def test_format_uses_original_traceback_not_current_stack() -> None:
    try:
        _raise_marker()
    except ValueError as error:
        diagnostics = format_exception_diagnostics(error)

    assert diagnostics["exceptionType"].endswith("ValueError")
    assert diagnostics["message"] == "boom-marker"
    assert "_raise_marker" in diagnostics["traceback"]
    assert "ValueError: boom-marker" in diagnostics["traceback"]
    # The recording frame must not be presented as the original failure.
    assert "format_exception_diagnostics" not in diagnostics["traceback"]
    assert diagnostics["location"]
    assert "test_exception_diagnostics.py" in diagnostics["location"]


def test_format_preserves_exception_chain() -> None:
    def _outer() -> None:
        try:
            raise ValueError("root-cause")
        except ValueError as root:
            raise RuntimeError("outer-error") from root

    try:
        _outer()
    except RuntimeError as error:
        diagnostics = format_exception_diagnostics(error)

    chained = [entry["message"] for entry in diagnostics["chain"]]
    assert chained[0] == "outer-error"
    assert "root-cause" in chained
    assert diagnostics["chain"][0]["type"].endswith("RuntimeError")


def test_long_traceback_is_explicitly_truncated_and_keeps_tail() -> None:
    try:
        raise RuntimeError("HEAD-" + ("z" * 5_000) + "-TAIL")
    except RuntimeError as error:
        diagnostics = format_exception_diagnostics(error, max_traceback_chars=1_500)

    assert diagnostics["truncated"] is True
    assert "[diagnostic truncated]" in diagnostics["traceback"]
    assert diagnostics["traceback"].startswith("Traceback")
    assert diagnostics["traceback"].rstrip().endswith("-TAIL")


def test_prepare_event_metadata_preserves_tail_when_over_limit() -> None:
    metadata = {
        "diagnostics": {
            "id": "diag_1",
            "exceptionType": "builtins.RuntimeError",
            "message": "root cause",
            "location": "app/x.py:10",
            "traceback": "x" * 80_000,
        },
        "context": "y" * 80_000,
    }

    prepared = prepare_event_metadata(metadata)

    assert prepared["truncated"] is True
    assert prepared["originalChars"] > 64 * 1024
    assert prepared["preview"]
    assert prepared["tail"]
    assert prepared["diagnostics"]["exceptionType"] == "builtins.RuntimeError"
    assert prepared["diagnostics"]["location"] == "app/x.py:10"


def test_truncate_event_message_keeps_both_ends() -> None:
    text = "开头" + ("中" * 5_000) + "结尾标记"

    truncated = truncate_event_message(text)

    assert len(truncated) <= 4_000
    assert truncated.startswith("开头")
    assert truncated.endswith("结尾标记")
    assert "[message truncated]" in truncated


def test_serialize_system_event_is_backward_compatible_with_legacy_metadata() -> None:
    serialized = serialize_system_event(
        {
            "id": "old-1",
            "level": "error",
            "source": "import",
            "actorType": "system",
            "action": "scan.failed",
            "message": "旧日志",
            "metadata": None,
            "createdAt": 1_700_000_000_000,
        }
    )

    assert serialized["metadata"] == {}
    assert serialized["message"] == "旧日志"


def test_list_projection_omits_traceback_but_keeps_summary() -> None:
    metadata = {
        "stage": "scan",
        "diagnostics": {
            "exceptionType": "builtins.OSError",
            "traceback": "Traceback ... very long",
            "chain": [{"type": "builtins.OSError", "message": "disk"}],
            "location": "app/x.py:1",
        },
    }

    summary = summarize_diagnostic_metadata(metadata)

    assert summary["stage"] == "scan"
    assert summary["diagnostics"]["exceptionType"] == "builtins.OSError"
    assert summary["diagnostics"]["location"] == "app/x.py:1"
    assert "traceback" not in summary["diagnostics"]
    assert "chain" not in summary["diagnostics"]
