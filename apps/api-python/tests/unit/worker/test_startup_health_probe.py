"""Exercise the launcher's actual Python probe against the diagnostic API."""

import io
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from app.modules.system.infrastructure.log_files import read_log_events


@pytest.mark.parametrize("fails", [False, True])
def test_startup_health_probe_preserves_retry_and_records_failure(db_session, monkeypatch, fails):
    root = Path(__file__).resolve().parents[5]
    script = (root / "scripts/start-unified-app.sh").read_text(encoding="utf-8")
    probe = script.split('"$BUSINESS_PYTHON" -c "\n', 1)[1].split('\n") >/dev/null', 1)[0]

    def request(*_args, **_kwargs):
        if fails:
            raise urllib.error.URLError("startup-test-connection-refused")
        return io.BytesIO(b'{}')

    monkeypatch.setattr(urllib.request, "urlopen", request)
    if fails:
        with pytest.raises(SystemExit) as result:
            exec(compile(probe, "startup-health-probe", "exec"), {})  # noqa: S102 - fixed repository script under test
        assert result.value.code == 1
        events = list(read_log_events())
        assert len(events) == 1
        assert "startup-test-connection-refused" in events[0]["metadata"]["diagnostics"]["traceback"]
    else:
        exec(compile(probe, "startup-health-probe", "exec"), {})  # noqa: S102 - fixed repository script under test
        assert list(read_log_events()) == []
