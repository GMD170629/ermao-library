"""Pure mapping from fenced source observations to PR6A content facts."""

from __future__ import annotations

from app.modules.catalog.application.content_dto import (
    ContentObservationOrigin,
    ObservedContentSource,
)
from app.modules.catalog.application.scan_dto import (
    DiscoveryEntryType,
    SourceObservation,
    SourceObservationOutcome,
)
from app.modules.catalog.domain.admission import (
    SourceAdmissionEvidence,
    SourceAdmissionRejection,
)
from app.modules.catalog.domain.content import SOURCE_CONTENT_POLICY_VERSION
from app.modules.catalog.domain.model import AdmissionKind


def observed_content_sources(
    observations: tuple[SourceObservation, ...],
    outcome: SourceObservationOutcome,
    *,
    origin: ContentObservationOrigin,
) -> tuple[ObservedContentSource, ...]:
    """Map only complete regular-file admissions through exact opaque bindings."""

    if not isinstance(observations, tuple):
        raise TypeError("observations must be a tuple")
    if not isinstance(outcome, SourceObservationOutcome):
        raise TypeError("outcome must be a SourceObservationOutcome")
    binding_by_path = {binding.relative_path: binding for binding in outcome.bindings}
    collision_paths = {
        path for collision in outcome.collisions for path in collision.related_paths
    }
    mapped: list[ObservedContentSource] = []
    for observation in observations:
        if not isinstance(observation, SourceObservation):
            raise TypeError("observations must contain SourceObservation values")
        source = observation.source
        admission = observation.admission
        if source.entry_type is not DiscoveryEntryType.FILE or admission is None:
            continue
        if source.relative_path in collision_paths:
            # Collision rows are deliberately invalid and have no usable opaque
            # binding.  Their diagnostics/topology blocking remain owned by the
            # scan or reconcile transaction.
            continue
        binding = binding_by_path.get(source.relative_path)
        if binding is None:
            raise ValueError("a content observation requires its exact source binding")
        identity = binding.filesystem_identity
        if identity is None or source.filesystem_identity != identity:
            raise ValueError(
                "content observation identity must match its source binding"
            )
        if source.expected_stat is None:
            raise ValueError("a content observation requires expected stat facts")
        if isinstance(admission, SourceAdmissionEvidence):
            admission_kind = admission.admission
            source_format = admission.source_format
            sidecar_role = admission.sidecar_role
        elif isinstance(admission, SourceAdmissionRejection):
            admission_kind = AdmissionKind.UNSUPPORTED
            source_format = None
            sidecar_role = None
        else:
            raise TypeError("admission must be a typed source admission result")
        mapped.append(
            ObservedContentSource(
                source_entry_id=binding.source_entry_id,
                relative_path=source.relative_path,
                filesystem_identity=identity,
                expected_stat=source.expected_stat,
                admission=admission_kind,
                source_format=source_format,
                sidecar_role=sidecar_role,
                policy_version=SOURCE_CONTENT_POLICY_VERSION,
                origin=origin,
            )
        )
    return tuple(mapped)


__all__ = ["observed_content_sources"]
