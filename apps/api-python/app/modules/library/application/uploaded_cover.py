"""Authority and revision rules for an explicitly uploaded Book cover."""

from app.contracts.automation_upload import UploadActor, UploadError, UploadSpec
from app.modules.library.application.metadata_patches import MetadataSnapshot


def require_uploaded_cover(
    actor: UploadActor, spec: UploadSpec, snapshot: MetadataSnapshot | None
) -> MetadataSnapshot:
    if snapshot is None or snapshot.library_id not in actor.library_ids:
        raise UploadError("RESOURCE_NOT_FOUND")
    if snapshot.revision != spec.expected_revision:
        raise UploadError("METADATA_CONFLICT")
    if "cover_ref" in snapshot.protected and not (spec.override and actor.can_override):
        raise UploadError("METADATA_PROTECTED")
    return snapshot
