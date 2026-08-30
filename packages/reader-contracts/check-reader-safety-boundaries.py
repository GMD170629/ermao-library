#!/usr/bin/env python3
"""Enforce generated Reader safety policy ownership at source boundaries."""

from __future__ import annotations

import importlib.util
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ROOT = ROOT / "packages/reader-contracts"
GENERATOR = CONTRACT_ROOT / "generate-reader-safety-policy.py"
POLICY = CONTRACT_ROOT / "reader-safety-policy.json"
FIXTURES = CONTRACT_ROOT / "fixtures/reader-safety-v1/manifest.json"

SCAN_ROOTS = (
    ROOT / "packages/reader-core/src",
    ROOT / "apps/web/features/reader",
    ROOT / "apps/web/features/audio",
    ROOT
    / "apps/mobile/shared/src/commonMain/kotlin/com/ermao/library/shared/modules/reader",
    ROOT
    / "apps/mobile/shared/src/commonMain/kotlin/com/ermao/library/shared/modules/downloads",
    ROOT / "apps/mobile/androidApp/src/main/kotlin/com/ermao/library/features/reader",
    ROOT / "apps/mobile/androidApp/src/main/kotlin/com/ermao/library/features/downloads",
    ROOT / "apps/mobile/iosApp/ErmaoLibrary/Features/Reader",
    ROOT / "apps/mobile/iosApp/ErmaoLibrary/Features/Downloads",
    ROOT / "apps/mobile/iosApp/ErmaoLibrary/Persistence/ManagedDownloadStore.swift",
    ROOT / "apps/mobile/mobiCore/src/main",
    ROOT / "apps/mobile/archiveCore/src/main",
    ROOT / "apps/mobile/native/archive-core/include/archive_core.h",
    ROOT / "apps/mobile/native/archive-core/src/archive_core.c",
    ROOT / "apps/mobile/native/mobi-core/Sources/CLibMobi/public/ermao_mobi.h",
    ROOT / "apps/mobile/native/mobi-core/Sources/CLibMobi/src/ermao_mobi.c",
    ROOT / "apps/api-python/app/modules/publications",
    ROOT / "apps/api-python/app/modules/media",
    ROOT / "apps/api-python/app/modules/reader",
    ROOT / "apps/api-python/app/contracts/media_capabilities.py",
    ROOT / "apps/api-python/app/infrastructure/comic_archives.py",
    ROOT / "apps/api-python/app/modules/imports/application/audio_types.py",
    ROOT / "apps/api-python/app/modules/imports/domain/resource_adapters.py",
    ROOT / "apps/api-python/app/services/audio_metadata.py",
)
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".kt", ".swift", ".c", ".cc", ".cpp", ".h", ".hpp"}
GENERATED_FILENAMES = {
    "reader-safety-policy.generated.ts",
    "ReaderSafetyPolicy.generated.kt",
    "reader_safety_policy_generated.py",
    "reader_safety_policy.generated.h",
    "ReaderHttpErrorStatuses.kt",
}

# These patterns identify a second policy catalog, not detector mechanics. A
# platform may compile generated values into sets/regexes; it may not author the
# values inside a literal list or recreate policy outcomes with raw strings.
PRIVATE_CATALOG_PATTERNS = (
    re.compile(r"(?is)allowedFontAlgorithms\s*=\s*(?:new\s+Set\s*\()?\s*\["),
    re.compile(
        r"(?is)(?:MIME_BY_FORMAT|MIME_TYPES_BY_FORMAT|CANONICAL_MIME_TYPES)\s*=\s*[\[{]"
    ),
    re.compile(
        r"(?is)(?:SAFE_DOCTYPES|SANITIZED_ELEMENTS|BLOCKED_SCHEMES)\s*=\s*(?:setOf|listOf)?\s*[\[{]\s*[\"']"
    ),
    re.compile(
        r"(?is)(?:BLOCKED_ELEMENT|BLOCKED_SVG_ELEMENT|DANGEROUS_META)\s*=\s*Regex\s*\(\s*[\"']"
    ),
    re.compile(r"(?is)URI_ATTRIBUTES\s*=\s*(?:setOf|listOf|new\s+Set)\s*\(\s*[\"']"),
    re.compile(
        r"(?is)querySelectorAll\s*\(\s*[\"'][^\"']*\["
        r"(?:href|src|srcset|poster|style|action|formaction|data)\]"
        r"[^\"']*,[^\"']*[\"']"
    ),
    re.compile(
        r"(?is)selector\s*:\s*[\"'][^\"']*\["
        r"(?:href|src|srcset|poster|style|action|formaction|data)\]"
    ),
    re.compile(
        r"(?im)^\s*(?:private\s+)?(?:const\s+val|const|let|val|static\s+final)\s+"
        r"[A-Z][A-Z0-9_]*(?:MAX_BYTES|MAX_COUNT|MAX_DEPTH|MAX_NODES|COMPRESSION_RATIO)\s*"
        r"[:=][^\n]*(?:\d|\*|shl)"
    ),
    re.compile(
        r"(?s)(?<!class )(?<![A-Za-z0-9_])(?:rejected|rejectReaderSafety|PublicationSecurityError)\s*\(.*?"
        r"[\"']PUBLICATION_SECURITY_REJECTED[\"']"
    ),
)

SOURCE_STRING_LITERAL = re.compile(
    r'""".*?"""|\'\'\'.*?\'\'\'|'
    r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`',
    re.DOTALL,
)


def find_source_literal_containing(
    source: str, values: Iterable[str]
) -> re.Match[str] | None:
    candidates = tuple(values)
    for literal in SOURCE_STRING_LITERAL.finditer(source):
        if any(value in literal.group(0) for value in candidates):
            return literal
    return None


def load_generator() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "reader_safety_policy_generator", GENERATOR
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("cannot load Reader safety policy generator")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def source_files() -> Iterable[Path]:
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        candidates = (root,) if root.is_file() else root.rglob("*")
        for path in candidates:
            lowered_parts = {part.lower() for part in path.parts}
            if (
                not path.is_file()
                or path.suffix not in SOURCE_SUFFIXES
                or path.name in GENERATED_FILENAMES
                or "test" in lowered_parts
                or "tests" in lowered_parts
                or "build" in lowered_parts
                or "node_modules" in lowered_parts
                or ".gradle" in lowered_parts
                or ".next" in lowered_parts
                or "vendor" in lowered_parts
                or path.name.endswith((".test.ts", ".test.tsx", "Test.kt"))
            ):
                continue
            yield path


def check_generated(
    module: ModuleType, policy: Mapping[str, object], digest: str
) -> list[str]:
    targets = (
        (module.TS_TARGET, module.render_typescript(policy, digest)),
        (module.KT_TARGET, module.render_kotlin(policy, digest)),
        (module.PY_TARGET, module.render_python(policy, digest)),
        (module.C_TARGET, module.render_c(policy, digest)),
    )
    return [
        f"stale generated policy: {path.relative_to(ROOT)}"
        for path, expected in targets
        if not path.exists() or path.read_text(encoding="utf-8") != expected
    ]


def check_source_ownership(policy: Mapping[str, object]) -> list[str]:
    rule_ids = [entry["id"] for entry in policy["rules"]]  # type: ignore[index]
    error_codes = {
        entry["errorCode"]
        for entry in policy["rules"]  # type: ignore[index]
        if entry["errorCode"] is not None
    }
    error_codes.update(policy["implementationFailureCodes"])  # type: ignore[arg-type,index]
    issues: list[str] = []
    for path in source_files():
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT)
        # Match policy values anywhere inside a source string, not only when
        # the whole literal equals the value. This catches interpolated error
        # messages such as `<generated-code>:${detail}` as well as literals.
        if match := find_source_literal_containing(source, rule_ids):
            line = source.count("\n", 0, match.start()) + 1
            issues.append(
                f"{relative}:{line}: raw ruleId; use the generated enum/object"
            )
        if match := find_source_literal_containing(source, error_codes):
            line = source.count("\n", 0, match.start()) + 1
            issues.append(
                f"{relative}:{line}: raw Reader safety errorCode; derive it from the generated rule/code"
            )
        for pattern in PRIVATE_CATALOG_PATTERNS:
            if match := pattern.search(source):
                line = source.count("\n", 0, match.start()) + 1
                issues.append(
                    f"{relative}:{line}: platform-owned Reader safety catalog/outcome"
                )
    return issues


def main() -> None:
    module = load_generator()
    policy = module.validate_policy(json.loads(POLICY.read_text(encoding="utf-8")))
    digest = module.policy_digest(policy)
    module.validate_fixture_manifest(
        json.loads(FIXTURES.read_text(encoding="utf-8")), policy=policy, digest=digest
    )
    issues = check_generated(module, policy, digest)
    issues.extend(check_source_ownership(policy))
    if issues:
        raise SystemExit(
            "Reader safety boundary check failed:\n- " + "\n- ".join(issues)
        )


if __name__ == "__main__":
    main()
