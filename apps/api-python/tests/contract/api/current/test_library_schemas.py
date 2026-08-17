from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.modules.catalog.presentation.schemas import (
    CreateLibraryRequest,
    LibraryAdminView,
    LibrarySummary,
    UpdateLibraryConfigRequest,
)


def _summary_payload() -> dict[str, object]:
    return {
        "id": "library-1",
        "name": "Books",
        "organizationMode": "VOLUMES",
        "topologyVersion": 1,
        "pathComparison": "SENSITIVE",
        "writePolicy": "READ_ONLY",
        "controlState": "ACTIVE",
        "observedHealth": "HEALTHY",
        "configRevision": 1,
        "grantLevel": "READ",
        "createdAt": datetime.now(UTC),
        "updatedAt": datetime.now(UTC),
    }


def test_ordinary_library_projection_never_accepts_root_path() -> None:
    payload = _summary_payload()
    payload["rootPath"] = "/srv/books"

    with pytest.raises(ValidationError):
        LibrarySummary.model_validate(payload)


def test_actor_scoped_library_projection_requires_grant_level() -> None:
    payload = _summary_payload()
    payload.pop("grantLevel")

    with pytest.raises(ValidationError):
        LibrarySummary.model_validate(payload)


def test_admin_library_projection_contains_canonical_root() -> None:
    payload = _summary_payload()
    payload["rootPath"] = "/srv/books"

    library = LibraryAdminView.model_validate(payload)

    assert library.root_path == "/srv/books"
    assert library.model_dump(by_alias=True)["rootPath"] == "/srv/books"


def test_create_library_contract_uses_current_fields_only() -> None:
    request = CreateLibraryRequest.model_validate(
        {
            "name": "Books",
            "rootPath": "/srv/books",
            "organizationMode": "AUDIOBOOK",
            "pathComparison": "INSENSITIVE",
        }
    )

    assert request.organization_mode == "AUDIOBOOK"
    assert request.write_policy == "READ_ONLY"
    assert "mediaKind" not in request.model_dump(by_alias=True)
    assert "monitorFolderId" not in request.model_dump(by_alias=True)


def test_config_patch_cannot_change_root_but_accepts_current_config_fields() -> None:
    with pytest.raises(ValidationError):
        UpdateLibraryConfigRequest.model_validate(
            {
                "expectedConfigRevision": 1,
                "rootPath": "/other",
            }
        )

    request = UpdateLibraryConfigRequest.model_validate(
        {
            "expectedConfigRevision": 1,
            "organizationMode": "FLAT",
            "pathComparison": "INSENSITIVE",
        }
    )
    assert request.organization_mode == "FLAT"
    assert request.path_comparison == "INSENSITIVE"
