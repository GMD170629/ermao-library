from __future__ import annotations

import pytest

from app.modules.imports.domain.directory_probe import (
    ProbeInterpretationResult,
    ProbeTerminationReason,
    decide_directory_probe,
)
from app.modules.imports.domain.resource_adapters import ResourceAdapterId


@pytest.mark.parametrize("sample_count", (0, 1, 99, 100))
def test_sample_count_is_recorded_in_evidence(sample_count: int) -> None:
    samples = tuple(f"book/track{i:03d}.mp3" for i in range(sample_count))
    decision = decide_directory_probe(
        directory_relative_path="book",
        sample_relative_paths=samples,
        entries_visited=sample_count,
        max_depth_reached=1,
        termination_reason=(
            ProbeTerminationReason.SAMPLE_LIMIT
            if sample_count == 100
            else ProbeTerminationReason.COMPLETE_SUBTREE
        ),
    )
    assert decision.evidence.sample_count == sample_count
    assert decision.evidence.sample_relative_paths == samples
    if sample_count == 0:
        assert decision.result is ProbeInterpretationResult.NODE_ONLY
        assert decision.adapter is None
        assert decision.reason_code == "NO_SAMPLES"
    else:
        assert decision.result is ProbeInterpretationResult.RESOURCE
        assert decision.adapter is not None
        assert decision.adapter.adapter_id is ResourceAdapterId.AUDIOBOOK_DIRECTORY
        assert decision.reason_code == "UNIQUE_ADAPTER"


def test_unique_directory_adapter_yields_resource() -> None:
    decision = decide_directory_probe(
        directory_relative_path="a",
        sample_relative_paths=("a/01.mp3", "a/02.flac"),
        entries_visited=2,
        max_depth_reached=0,
        termination_reason=ProbeTerminationReason.COMPLETE_SUBTREE,
    )
    assert decision.result is ProbeInterpretationResult.RESOURCE
    assert decision.adapter is not None
    assert decision.adapter.adapter_id is ResourceAdapterId.AUDIOBOOK_DIRECTORY
    assert decision.reason_code == "UNIQUE_ADAPTER"


def test_image_directory_unique_match() -> None:
    decision = decide_directory_probe(
        directory_relative_path="comic",
        sample_relative_paths=("comic/001.png", "comic/002.jpg"),
        entries_visited=2,
        max_depth_reached=0,
        termination_reason=ProbeTerminationReason.COMPLETE_SUBTREE,
    )
    assert decision.result is ProbeInterpretationResult.RESOURCE
    assert decision.adapter is not None
    assert decision.adapter.adapter_id is ResourceAdapterId.IMAGE_DIRECTORY


def test_conflict_or_unmatched_samples_are_node_only() -> None:
    mixed = decide_directory_probe(
        directory_relative_path="a",
        sample_relative_paths=("a/01.mp3", "a/cover.png"),
        entries_visited=2,
        max_depth_reached=0,
        termination_reason=ProbeTerminationReason.COMPLETE_SUBTREE,
    )
    assert mixed.result is ProbeInterpretationResult.NODE_ONLY
    assert mixed.adapter is None
    assert mixed.reason_code == "ADAPTER_CONFLICT_OR_UNMATCHED"

    unknown = decide_directory_probe(
        directory_relative_path="docs",
        sample_relative_paths=("docs/readme.md",),
        entries_visited=1,
        max_depth_reached=0,
        termination_reason=ProbeTerminationReason.COMPLETE_SUBTREE,
    )
    assert unknown.result is ProbeInterpretationResult.NODE_ONLY
    assert unknown.reason_code == "ADAPTER_CONFLICT_OR_UNMATCHED"


def test_no_samples_is_node_only() -> None:
    decision = decide_directory_probe(
        directory_relative_path="empty",
        sample_relative_paths=(),
        entries_visited=0,
        max_depth_reached=0,
        termination_reason=ProbeTerminationReason.COMPLETE_SUBTREE,
    )
    assert decision.result is ProbeInterpretationResult.NODE_ONLY
    assert decision.reason_code == "NO_SAMPLES"
    assert decision.adapter is None


@pytest.mark.parametrize(
    "termination",
    (
        ProbeTerminationReason.COMPLETE_SUBTREE,
        ProbeTerminationReason.SAMPLE_LIMIT,
        ProbeTerminationReason.ENTRY_BUDGET,
        ProbeTerminationReason.DEPTH_BUDGET,
        ProbeTerminationReason.TIME_BUDGET,
        ProbeTerminationReason.LOCAL_IO_ERROR,
    ),
)
def test_termination_reasons_are_preserved_in_evidence(
    termination: ProbeTerminationReason,
) -> None:
    decision = decide_directory_probe(
        directory_relative_path="dir",
        sample_relative_paths=("dir/a.mp3",),
        entries_visited=10,
        max_depth_reached=3,
        termination_reason=termination,
    )
    assert decision.evidence.termination_reason is termination
    assert decision.evidence.entries_visited == 10
    assert decision.evidence.max_depth_reached == 3


def test_audiobook_parent_with_only_volume_children_is_node_only() -> None:
    decision = decide_directory_probe(
        directory_relative_path="鬼吹灯",
        sample_relative_paths=(
            "鬼吹灯/鬼吹灯I-1-精绝古城/01.mp3",
            "鬼吹灯/鬼吹灯I-2-龙岭迷窟/01.mp3",
        ),
        entries_visited=4,
        max_depth_reached=1,
        termination_reason=ProbeTerminationReason.COMPLETE_SUBTREE,
    )

    assert decision.result is ProbeInterpretationResult.NODE_ONLY
    assert decision.reason_code == "AUDIOBOOK_CHILD_RESOURCE_BOUNDARY"


def test_audiobook_resource_keeps_only_direct_and_transparent_samples() -> None:
    decision = decide_directory_probe(
        directory_relative_path="鬼吹灯",
        sample_relative_paths=(
            "鬼吹灯/00.mp3",
            "鬼吹灯/CD1/01.mp3",
            "鬼吹灯/第一卷/01.mp3",
        ),
        entries_visited=6,
        max_depth_reached=1,
        termination_reason=ProbeTerminationReason.COMPLETE_SUBTREE,
    )

    assert decision.result is ProbeInterpretationResult.RESOURCE
    assert decision.evidence.sample_relative_paths == (
        "鬼吹灯/00.mp3",
        "鬼吹灯/CD1/01.mp3",
    )
