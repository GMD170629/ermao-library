"""Operation kind probes continue only for a missing resource in that kind."""

from dataclasses import dataclass

import pytest

from app.contracts.automation_upload import UploadError
from app.modules.automation.application.operations import AutomationOperations
from app.modules.automation.domain.access import (
    EffectiveAccess,
    GrantPermissions,
    Scope,
)
from app.modules.library.public import FileMoveError

KINDS = ("deletions", "uploads", "moves", "writebacks")
ACCESS = EffectiveAccess(
    "grant",
    "owner",
    GrantPermissions(frozenset({Scope.FILES_MODIFY}), frozenset({"library"})),
)


@dataclass
class Endpoint:
    kind: str
    calls: list[str]
    found: bool = False
    failure: Exception | None = None

    def progress(self, access, operation_id):
        self.calls.append(self.kind)
        if self.failure is not None:
            raise self.failure
        if self.found:
            return {"operation_id": operation_id, "kind": self.kind}
        error_type = UploadError if self.kind == "uploads" else FileMoveError
        raise error_type("RESOURCE_NOT_FOUND")

    def cancel(self, access, operation_id):
        return self.progress(access, operation_id)


@pytest.mark.parametrize("method", ["progress", "cancel"])
@pytest.mark.parametrize("kind", KINDS)
def test_missing_kind_probes_reach_the_owning_operation(kind, method, caplog):
    calls = []
    endpoints = {name: Endpoint(name, calls, found=name == kind) for name in KINDS}
    operations = AutomationOperations(**endpoints)
    assert getattr(operations, method)(ACCESS, "operation") == {
        "operation_id": "operation",
        "kind": kind,
    }
    assert calls == list(KINDS[: KINDS.index(kind) + 1])
    assert not caplog.records


@pytest.mark.parametrize("method", ["progress", "cancel"])
@pytest.mark.parametrize("kind", KINDS[:-1])
def test_real_operation_error_is_not_hidden_by_kind_probes(kind, method):
    calls = []
    error_type = UploadError if kind == "uploads" else FileMoveError
    failure = error_type("AUTHORIZATION_REVOKED")
    endpoints = {name: Endpoint(name, calls) for name in KINDS}
    endpoints[kind].failure = failure
    operations = AutomationOperations(**endpoints)
    with pytest.raises(error_type) as observed:
        getattr(operations, method)(ACCESS, "operation")
    assert observed.value is failure
    assert calls == list(KINDS[: KINDS.index(kind) + 1])
