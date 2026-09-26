"""One provider-to-field proposal mapping for both recognition callers."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from app.contracts.recognized_metadata_fields import PROVIDER_METADATA_FIELDS
from app.modules.metadata.application.recognition import (
    assess_candidates,
    candidate_evidence,
)
from app.modules.metadata.domain.recognition import MatchDecision, RecognitionContext

ProposalValue = str | float | bool | tuple[str, ...]


@dataclass(frozen=True)
class FieldProposal:
    field: str
    value: ProposalValue
    current: object
    provider_id: str
    candidate_key: str
    level: str
    evidence_ids: tuple[str, ...]
    protected: bool


def propose_fields(context: RecognitionContext, provider: str,
                   candidate: Mapping[str, object], decision: MatchDecision) -> tuple[FieldProposal, ...]:
    if decision.outcome != "MATCHED":
        return ()
    current = dict(context.values)
    result = []
    for source, name in PROVIDER_METADATA_FIELDS.items():
        field = context.target_type + "." + name
        value = candidate.get(source)
        if field not in decision.allowed_fields or value is None or value == "":
            continue
        if name == "published_at":
            # A year or month is not a day. Preserve it in candidate evidence,
            # but do not invent a full timestamp for the database date field.
            if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}(?:$|T)", value):
                continue
            parsed = datetime.fromisoformat(value)
            value = (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).isoformat()
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            value = tuple(value)
        if not isinstance(value, (str, int, float, bool, tuple)):
            continue
        result.append(FieldProposal(field, value, current.get(name), provider,
                                   decision.candidate_key, decision.level,
                                   decision.evidence_ids, name in context.protected))
    return tuple(result)


def supplement_fields(context: RecognitionContext, provider: str, candidate: Mapping[str, object],
                      additional_provider: str, additional: dict[str, object]) -> tuple[FieldProposal, ...]:
    """Require both target identity and agreement with the primary source."""
    local = assess_candidates(context, additional_provider, [additional])[0][1]
    primary = candidate_evidence(provider, candidate)
    cross = assess_candidates(replace(context, identity=primary.identity), additional_provider, [additional])[0][1]
    if cross.outcome != "MATCHED":
        return ()
    return tuple(proposal for proposal in propose_fields(context, additional_provider, additional, local)
                 if proposal.field in cross.allowed_fields)
