from pathlib import Path

from app.worker import main


def test_worker_ready_file_uses_platform_temporary_directory(
    monkeypatch,
) -> None:
    monkeypatch.delenv("IMPORT_WORKER_READY_FILE", raising=False)
    monkeypatch.setattr(main, "gettempdir", lambda: "platform-temp")

    assert main.worker_ready_file() == Path("platform-temp") / "import-worker-ready"


def test_worker_ready_file_preserves_explicit_override(monkeypatch) -> None:
    configured = Path("configured") / "worker.ready"
    monkeypatch.setenv("IMPORT_WORKER_READY_FILE", str(configured))

    assert main.worker_ready_file() == configured
