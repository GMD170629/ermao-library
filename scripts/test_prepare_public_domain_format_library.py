from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "prepare_public_domain_format_library",
    Path(__file__).with_name("prepare-public-domain-format-library.py"),
)
assert spec is not None and spec.loader is not None
corpus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(corpus)


def test_aiff_alias_is_rejected_before_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "alias.aifc"
    sample.write_bytes(b"FORM\x00\x00\x00\x04AIFF")

    def forbidden_probe(*args, **kwargs):
        pytest.fail("An AIFF alias must not be counted as an AIFC fixture")

    monkeypatch.setattr(corpus.subprocess, "run", forbidden_probe)
    with pytest.raises(RuntimeError, match="AIFC FORM"):
        corpus.probe_audio(Path("ffprobe"), sample)


def test_aifc_header_preserves_audio_stream_and_duration_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "valid.aifc"
    sample.write_bytes(b"FORM\x00\x00\x00\x04AIFC")
    payload = {
        "streams": [{"codec_type": "audio", "codec_name": "pcm_s16le"}],
        "format": {"duration": "30"},
    }

    def probe(*args, **kwargs):
        return subprocess.CompletedProcess([], 0, json.dumps(payload), "")

    monkeypatch.setattr(corpus.subprocess, "run", probe)
    assert corpus.probe_audio(Path("ffprobe"), sample) == payload
    payload["format"]["duration"] = "0"
    with pytest.raises(RuntimeError, match="No valid audio stream and duration"):
        corpus.probe_audio(Path("ffprobe"), sample)
