"""Bounded directory probe decision rules (suffix-only, no file I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.modules.imports.domain.ignore_rules import is_builtin_ignored_file
from app.modules.imports.domain.resource_adapters import (
    ResourceAdapterId,
    ResourceAdapterSpec,
    is_supported_source_tree_filename,
    match_directory_adapters_for_samples,
    unique_adapter_or_none,
)
from app.modules.library.public import (
    SourceNodePhysicalKind,
    SourceNodeRelativePath,
    audiobook_resource_owns_path,
)


class ProbeTerminationReason(str, Enum):
    COMPLETE_SUBTREE = "COMPLETE_SUBTREE"
    SAMPLE_LIMIT = "SAMPLE_LIMIT"
    ENTRY_BUDGET = "ENTRY_BUDGET"
    DEPTH_BUDGET = "DEPTH_BUDGET"
    TIME_BUDGET = "TIME_BUDGET"
    LOCAL_IO_ERROR = "LOCAL_IO_ERROR"


class ProbeInterpretationResult(str, Enum):
    NODE_ONLY = "NODE_ONLY"
    RESOURCE = "RESOURCE"


@dataclass(frozen=True, slots=True)
class DirectoryProbeEvidence:
    sample_relative_paths: tuple[str, ...]
    sample_count: int
    entries_visited: int
    max_depth_reached: int
    termination_reason: ProbeTerminationReason


@dataclass(frozen=True, slots=True)
class DirectoryProbeDecision:
    result: ProbeInterpretationResult
    adapter: ResourceAdapterSpec | None
    reason_code: str
    evidence: DirectoryProbeEvidence


def decide_directory_probe(
    *,
    directory_relative_path: str,
    sample_relative_paths: tuple[str, ...],
    entries_visited: int,
    max_depth_reached: int,
    termination_reason: ProbeTerminationReason,
) -> DirectoryProbeDecision:
    eligible_sample_paths = tuple(
        path
        for path in sample_relative_paths
        if not is_builtin_ignored_file(path.rsplit("/", 1)[-1])
        and is_supported_source_tree_filename(path.rsplit("/", 1)[-1])
    )
    evidence = DirectoryProbeEvidence(
        sample_relative_paths=eligible_sample_paths,
        sample_count=len(eligible_sample_paths),
        entries_visited=entries_visited,
        max_depth_reached=max_depth_reached,
        termination_reason=termination_reason,
    )
    if evidence.sample_count == 0:
        return DirectoryProbeDecision(
            result=ProbeInterpretationResult.NODE_ONLY,
            adapter=None,
            reason_code="NO_SAMPLES",
            evidence=evidence,
        )
    sample_names = tuple(
        path.rsplit("/", 1)[-1] for path in evidence.sample_relative_paths
    )
    matches = match_directory_adapters_for_samples(sample_names)
    adapter = unique_adapter_or_none(matches)
    if (
        adapter is not None
        and adapter.adapter_id is ResourceAdapterId.AUDIOBOOK_DIRECTORY
    ):
        anchor = SourceNodeRelativePath(directory_relative_path)
        owned_samples = tuple(
            sample
            for sample in evidence.sample_relative_paths
            if audiobook_resource_owns_path(
                resource_anchor=anchor,
                candidate_path=SourceNodeRelativePath(sample),
                candidate_kind=SourceNodePhysicalKind.REGULAR_FILE,
            )
        )
        if not owned_samples:
            return DirectoryProbeDecision(
                result=ProbeInterpretationResult.NODE_ONLY,
                adapter=None,
                reason_code="AUDIOBOOK_CHILD_RESOURCE_BOUNDARY",
                evidence=evidence,
            )
        evidence = DirectoryProbeEvidence(
            sample_relative_paths=owned_samples,
            sample_count=len(owned_samples),
            entries_visited=entries_visited,
            max_depth_reached=max_depth_reached,
            termination_reason=termination_reason,
        )
    if adapter is None:
        return DirectoryProbeDecision(
            result=ProbeInterpretationResult.NODE_ONLY,
            adapter=None,
            reason_code="ADAPTER_CONFLICT_OR_UNMATCHED",
            evidence=evidence,
        )
    return DirectoryProbeDecision(
        result=ProbeInterpretationResult.RESOURCE,
        adapter=adapter,
        reason_code="UNIQUE_ADAPTER",
        evidence=evidence,
    )
