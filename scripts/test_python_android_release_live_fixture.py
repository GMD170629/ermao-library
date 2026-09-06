import subprocess
from unittest.mock import patch

import pytest
from python_android_release_live_fixture import adb_call, require_loopback_origin


@pytest.mark.parametrize(
    "origin",
    [
        "http://production.example:18080",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3100",
        "http://admin:password@127.0.0.1:18080",
        "http://127.0.0.1:18080/api",
        "http://127.0.0.1:18080?target=production",
        "http://127.0.0.1:18080#fragment",
        "http://127.0.0.1",
        "https://127.0.0.1:18080",
    ],
)
def test_fixture_refuses_production_or_nonisolated_origin(origin: str) -> None:
    with pytest.raises(ValueError):
        require_loopback_origin(origin)


def test_dedicated_loopback_origin_is_preserved() -> None:
    assert require_loopback_origin("http://127.0.0.1:18080") == (
        "http://127.0.0.1:18080",
        18080,
    )


def test_adb_credential_transport_uses_stdin_and_exact_device() -> None:
    private = b'{"password":"test-only-not-a-secret"}'
    with patch("python_android_release_live_fixture.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, stdout=b"", stderr=b"")
        adb_call(
            "adb.exe",
            "authorized-device",
            "exec-in",
            "run-as",
            "com.ermao.library",
            stdin=private,
        )
    args, kwargs = run.call_args
    assert args[0][:3] == ["adb.exe", "-s", "authorized-device"]
    assert all("test-only-not-a-secret" not in argument for argument in args[0])
    assert kwargs["input"] == private
    assert kwargs["timeout"] == 30
    assert kwargs["capture_output"] is True


def test_adb_failure_does_not_echo_credentials_or_remote_output() -> None:
    with patch("python_android_release_live_fixture.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            [], 1, stdout=b"private", stderr=b"private"
        )
        with pytest.raises(RuntimeError) as failure:
            adb_call("adb.exe", "authorized-device", "exec-in", stdin=b"private")
    assert str(failure.value) == "adb exec-in failed with exit 1"
