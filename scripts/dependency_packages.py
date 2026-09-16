"""Compatibility CLI for the single portable dependency implementation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api-python"))
from shuku_dependencies import (
    Artifact,
    Package,
    canonical_digest,
    digest,
    generate,
    node_packages,
    normalized,
    python_packages,
)
from shuku_dependencies.packages import main

__all__ = [
    "Artifact",
    "Package",
    "canonical_digest",
    "digest",
    "generate",
    "node_packages",
    "normalized",
    "python_packages",
]

if __name__ == "__main__":
    main()
