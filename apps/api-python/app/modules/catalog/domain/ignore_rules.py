"""Exact, root-relative ignore rules."""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from app.modules.catalog.domain.errors import DuplicateIgnoreRule, InvalidIgnoreRule


class IgnoreRuleKind(StrEnum):
    NAME = "NAME"
    PATH = "PATH"


def _normalize_pattern(kind: IgnoreRuleKind, pattern: str) -> str:
    if not isinstance(kind, IgnoreRuleKind) or not isinstance(pattern, str):
        raise InvalidIgnoreRule("pattern")
    value = unicodedata.normalize("NFC", pattern)
    maximum_length = 255 if kind is IgnoreRuleKind.NAME else 4096
    if (
        not value
        or len(value) > maximum_length
        or any(unicodedata.category(character) == "Cc" for character in value)
    ):
        raise InvalidIgnoreRule("pattern")
    if kind is IgnoreRuleKind.NAME:
        if "/" in value or "\\" in value or value in {".", ".."}:
            raise InvalidIgnoreRule("name")
        return value
    if (
        value.startswith(("/", "\\"))
        or "\\" in value
        or (len(value) >= 2 and value[1] == ":" and value[0].isalpha())
    ):
        raise InvalidIgnoreRule("path")
    segments = value.split("/")
    if any(not segment or segment in {".", ".."} for segment in segments):
        raise InvalidIgnoreRule("path")
    return "/".join(segments)


@dataclass(frozen=True, slots=True)
class IgnoreRule:
    kind: IgnoreRuleKind
    pattern: str
    rule_key: str = ""
    enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise InvalidIgnoreRule("enabled")
        normalized = _normalize_pattern(self.kind, self.pattern)
        derived_key = hashlib.sha256(
            f"{self.kind.value}\x00{normalized}".encode()
        ).hexdigest()
        if self.rule_key and self.rule_key != derived_key:
            raise InvalidIgnoreRule("rule_key")
        object.__setattr__(self, "pattern", normalized)
        object.__setattr__(self, "rule_key", derived_key)

    @classmethod
    def create(cls, *, kind: IgnoreRuleKind, pattern: str) -> IgnoreRule:
        return cls(kind=kind, pattern=pattern)


def replace_rules(rules: tuple[IgnoreRule, ...]) -> tuple[IgnoreRule, ...]:
    if not isinstance(rules, tuple) or len(rules) > 200:
        raise InvalidIgnoreRule("rule_count")
    if any(not isinstance(rule, IgnoreRule) for rule in rules):
        raise InvalidIgnoreRule("rule")
    keys = [rule.rule_key for rule in rules]
    if len(set(keys)) != len(keys):
        raise DuplicateIgnoreRule()
    return tuple(rules)
