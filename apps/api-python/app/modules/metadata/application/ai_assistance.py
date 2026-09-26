"""Strict, evidence-bound AI advice. Advice never grants metadata fields."""

import json
import re
from collections.abc import Mapping
from typing import Any

from app.modules.metadata.application.recognition import candidate_evidence

PROMPT_VERSION = "recognition-assistance-1"


def assistance_input(context: Mapping[str, Any]) -> dict[str, Any]:
    evidence: list[dict[str, str]] = []
    book = context.get("book") or {}
    identity = context.get("identity") or {}
    for key, value in (("title", book.get("title")), ("author", book.get("author")), ("isbn", identity.get("isbn")), ("parent", identity.get("workTitle"))):
        if isinstance(value, str) and value.strip():
            evidence.append({"id": "target:" + key, "value": value[:700]})
    for index, item in enumerate((context.get("files") or [])[:4]):
        if isinstance(item, dict):
            name = re.split(r"[/\\\\]", str(item.get("relativePath") or ""))[-1]
            if name:
                evidence.append({"id": f"file:{index}", "value": name[:150]})
    candidates = []
    for item in (context.get("aiCandidates") or [])[:5]:
        if not isinstance(item, dict) or not item.get("source") or not item.get("id"):
            continue
        candidate = candidate_evidence(str(item["source"]), item)
        refs = []
        for field in ("title", "author", "isbn", "volume", "publisher", "language"):
            value = item.get(field)
            if isinstance(value, str) and value.strip():
                ref = candidate.key + ":" + field
                refs.append(ref)
                evidence.append({"id": ref, "value": value[:500]})
        candidates.append({"candidateKey": candidate.key, "evidenceIds": refs})
    result = {"promptVersion": PROMPT_VERSION, "purpose": "disambiguate" if candidates else "query", "evidence": evidence, "candidates": candidates}
    if len(json.dumps(result, ensure_ascii=False)) > 12000:
        raise ValueError("AI_INPUT_TOO_LARGE")
    return result


def assistance_schema(inputs: Mapping[str, Any]) -> dict[str, Any]:
    refs = [item["id"] for item in inputs["evidence"]]
    references = {"type": "array", "items": {"type": "string", "enum": refs or ["none"]}, "maxItems": 16}
    if inputs["purpose"] == "disambiguate":
        properties = {"selectedCandidateKey": {"type": ["string", "null"], "enum": [None, *[item["candidateKey"] for item in inputs["candidates"]]]},
            "supportingEvidenceIds": references, "conflictingEvidenceIds": references,
            "reason": {"type": "string", "maxLength": 400}}
    else:
        properties = {name: {"type": ["string", "null"], "maxLength": 200} for name in ("title", "author", "volume")}
        properties.update(evidenceIds=references, reason={"type": "string", "maxLength": 400},
            queryHints={"type": "array", "maxItems": 2, "items": {"type": "object", "additionalProperties": False,
                "properties": {"query": {"type": "string", "maxLength": 300}, "evidenceIds": references, "hypothesis": {"type": "boolean"}},
                "required": ["query", "evidenceIds", "hypothesis"]}})
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def parse_assistance(content: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    if len(content) > 8000:
        raise ValueError("AI_OUTPUT_TOO_LARGE")
    result = json.loads(content)
    if not isinstance(result, dict) or set(result) != set(assistance_schema(inputs)["required"]):
        raise ValueError("AI_OUTPUT_FIELDS_INVALID")
    evidence = {item["id"] for item in inputs["evidence"]}
    def refs(value: object, *, required: bool = False) -> None:
        if not isinstance(value, list) or len(value) > 16 or any(not isinstance(item, str) or item not in evidence for item in value) or (required and not value):
            raise ValueError("AI_EVIDENCE_INVALID")
    if not isinstance(result["reason"], str) or len(result["reason"]) > 400:
        raise ValueError("AI_REASON_INVALID")
    if inputs["purpose"] == "disambiguate":
        selected = result["selectedCandidateKey"]
        if selected is not None and (not isinstance(selected, str) or selected not in {item["candidateKey"] for item in inputs["candidates"]}):
            raise ValueError("AI_CANDIDATE_INVALID")
        refs(result["supportingEvidenceIds"], required=selected is not None)
        refs(result["conflictingEvidenceIds"])
    else:
        for name in ("title", "author", "volume"):
            if result[name] is not None and (not isinstance(result[name], str) or len(result[name]) > 200):
                raise ValueError("AI_HINT_INVALID")
        refs(result["evidenceIds"], required=any(result[name] for name in ("title", "author", "volume")))
        if not isinstance(result["queryHints"], list) or len(result["queryHints"]) > 2:
            raise ValueError("AI_HINT_INVALID")
        for hint in result["queryHints"]:
            if not isinstance(hint, dict) or set(hint) != {"query", "evidenceIds", "hypothesis"} or not isinstance(hint["query"], str) or not 1 <= len(hint["query"]) <= 300 or type(hint["hypothesis"]) is not bool:
                raise ValueError("AI_HINT_INVALID")
            refs(hint["evidenceIds"], required=True)
            # Novel words are hypotheses regardless of the model's assertion.
            if any(part not in " ".join(item["value"] for item in inputs["evidence"]) for part in hint["query"].split()):
                hint["hypothesis"] = True
    return {"purpose": inputs["purpose"], **result}
