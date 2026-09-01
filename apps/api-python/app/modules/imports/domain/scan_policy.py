"""Policies that control reconciliation after source-tree discovery."""

from __future__ import annotations

from enum import Enum


class MissingEntryPolicy(str, Enum):
    """Choose whether unseen stored children survive a successful directory scan."""

    PRESERVE = "PRESERVE"
    PRUNE_MISSING = "PRUNE_MISSING"


__all__ = ["MissingEntryPolicy"]
