# Test-only append to metadata_file_writeback in the isolated acceptance volume.
import os as _crash_os
import signal as _crash_signal
from pathlib import Path as _CrashPath

_crash_original_publish = globals()["file_writeback"].publish_prepared


def _crash_before_publish(source, prepared):
    root = _CrashPath("/app/storage/update-tmp")
    marker = root / "writeback-crashed"
    if not marker.exists():
        assert _CrashPath(prepared).is_file()
        marker.touch()
        _crash_os.kill(_crash_os.getpid(), _crash_signal.SIGKILL)
    output = _crash_original_publish(source, prepared)
    published = root / "writeback-published"
    assert not published.exists(), "duplicate publication"
    published.write_text("once")
    return output


globals()["file_writeback"].publish_prepared = _crash_before_publish
