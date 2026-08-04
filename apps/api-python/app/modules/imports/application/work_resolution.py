"""Pure title-based work identity after local metadata has been finalized."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.modules.imports.application.identity_policy import normalize_identity_part

WorkIdentityKind = Literal["TITLE"]


@dataclass(frozen=True, slots=True)
class WorkIdentityDecision:
    """The deterministic database identity derived from final publication metadata."""

    merge_key: str
    kind: WorkIdentityKind


def resolve_work_identity(
    *,
    title: str,
) -> WorkIdentityDecision:
    """Resolve a work key solely from the final recognized work title."""

    return WorkIdentityDecision(normalize_identity_part(title), "TITLE")
