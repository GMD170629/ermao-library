import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from python_release_live_fixture import (
    _build_production_web,
    _next_command,
    _wait_for_stop,
)


def test_runtime_commands_keep_production_opt_in_and_loopback_bound() -> None:
    with patch("python_release_live_fixture._pnpm_command", return_value=["pnpm"]):
        assert _next_command(3101) == [
            "pnpm",
            "exec",
            "next",
            "dev",
            "--webpack",
            "-H",
            "127.0.0.1",
            "-p",
            "3101",
        ]
        assert _next_command(3101, "production") == [
            "pnpm",
            "exec",
            "next",
            "start",
            "-H",
            "127.0.0.1",
            "-p",
            "3101",
        ]
        with pytest.raises(KeyError):
            _next_command(3101, "publish")


@pytest.mark.parametrize("outcome", [0, 1, subprocess.TimeoutExpired("build", 600)])
def test_build_uses_existing_script_and_always_reaps_its_process(
    outcome: object,
) -> None:
    with (
        patch("python_release_live_fixture._pnpm_command", return_value=["pnpm"]),
        patch("python_release_live_fixture.start_logged_process") as start,
    ):
        build = start.return_value
        if isinstance(outcome, subprocess.TimeoutExpired):
            build.wait.side_effect = outcome
        else:
            build.wait.return_value = outcome
        env = {"NEXT_DIST_DIR": ".next-release-live-test"}
        if outcome == 0:
            _build_production_web(env, Path("next-build.log"))
        else:
            with pytest.raises((RuntimeError, subprocess.TimeoutExpired)):
                _build_production_web(env, Path("next-build.log"))
        assert start.call_args.args[0] == ["pnpm", "run", "build"]
        assert start.call_args.kwargs["env"] == env
        build.wait.assert_called_once_with(timeout=600)
        build.stop.assert_called_once_with(timeout=12)


@pytest.mark.parametrize("lifetime", [599, 7801])
def test_fixture_rejects_unbounded_lifetime(tmp_path: Path, lifetime: int) -> None:
    with pytest.raises(ValueError, match="lifetime"):
        _wait_for_stop(tmp_path / "stop", {}, tmp_path / "events.log", lifetime)


def test_long_fixture_still_enforces_deadline_and_detects_early_exit(
    tmp_path: Path,
) -> None:
    with (
        patch("python_release_live_fixture.time.monotonic", side_effect=[0, 2401]),
        pytest.raises(TimeoutError, match="2400"),
    ):
        _wait_for_stop(tmp_path / "stop", {}, tmp_path / "events.log", 2400)
    with patch("python_release_live_fixture.start_logged_process") as start:
        process = start.return_value
        process.poll.return_value = 2
        process.returncode = 2
        with pytest.raises(RuntimeError, match="exited before"):
            _wait_for_stop(
                tmp_path / "stop", {"api": process}, tmp_path / "events.log", 2400
            )
