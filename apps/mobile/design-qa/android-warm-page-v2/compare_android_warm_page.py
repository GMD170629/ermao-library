#!/usr/bin/env python3
"""Read-only Android Warm Page design-reference comparator.

This tool deliberately separates immutable design references from rendered
Android candidates. It never creates or updates an expected/golden baseline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

try:
    from PIL import Image, ImageChops
except ImportError as exc:  # pragma: no cover - exercised by the invoking environment
    raise SystemExit(
        "Pillow is required for Android Warm Page visual comparison. "
        "Install it in the host Python environment; the comparator does not run on-device."
    ) from exc


EXIT_DIFFERENCE = 1
EXIT_CONFIGURATION = 2
OWNERSHIP_CODES = {"A": 1, "B": 2, "C": 3}
OWNERSHIP_NAMES = {
    "A": "System-owned",
    "B": "Native-themed",
    "C": "App-owned",
}


class ConfigurationError(RuntimeError):
    """Raised when references, inputs, or the manifest are not trustworthy."""


@dataclass(frozen=True)
class Viewport:
    width: int
    height: int


@dataclass(frozen=True)
class OwnershipRegion:
    ownership: str
    name: str
    bounds: tuple[int, int, int, int]


@dataclass(frozen=True)
class OwnershipProfile:
    name: str
    default_ownership: str
    regions: tuple[OwnershipRegion, ...]


@dataclass(frozen=True)
class Scene:
    scene_id: str
    actual_file: str
    reference_path: Path
    reference_sha256: str
    ownership_profile: OwnershipProfile
    anchors: tuple[Mapping[str, object], ...]


@dataclass(frozen=True)
class Manifest:
    path: Path
    repository_root: Path
    viewport: Viewport
    maximum_channel_difference: int
    maximum_app_owned_difference_ratio: float
    scenes: tuple[Scene, ...]


@dataclass(frozen=True)
class PreparedScene:
    scene: Scene
    actual_path: Path
    reference_image: Image.Image
    actual_image: Image.Image


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ConfigurationError(f"{context} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ConfigurationError(f"{context} keys must be strings")
    return value


def _sequence(value: object, context: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ConfigurationError(f"{context} must be an array")
    return value


def _string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigurationError(f"{context} must be a non-empty string")
    return value


def _integer(value: object, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigurationError(f"{context} must be an integer")
    return value


def _number(value: object, context: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigurationError(f"{context} must be a number")
    return float(value)


def _ownership(value: object, context: str) -> str:
    result = _string(value, context)
    if result not in OWNERSHIP_CODES:
        raise ConfigurationError(f"{context} must be A, B, or C")
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_repository_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists() and (candidate / "docs").is_dir():
            return candidate.resolve()
    raise ConfigurationError(
        f"Unable to find repository root above {start}; pass --repo-root explicitly"
    )


def _parse_bounds(value: object, context: str, viewport: Viewport) -> tuple[int, int, int, int]:
    parts = _sequence(value, context)
    if len(parts) != 4:
        raise ConfigurationError(f"{context} must contain [x, y, width, height]")
    x, y, width, height = (
        _integer(parts[0], f"{context}[0]"),
        _integer(parts[1], f"{context}[1]"),
        _integer(parts[2], f"{context}[2]"),
        _integer(parts[3], f"{context}[3]"),
    )
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ConfigurationError(f"{context} must describe a positive in-frame rectangle")
    if x + width > viewport.width or y + height > viewport.height:
        raise ConfigurationError(
            f"{context} {x, y, width, height} exceeds {viewport.width}x{viewport.height}"
        )
    return x, y, width, height


def load_manifest(manifest_path: Path, repository_root: Path | None = None) -> Manifest:
    path = manifest_path.resolve()
    if not path.is_file():
        raise ConfigurationError(f"Manifest does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Unable to read manifest {path}: {exc}") from exc
    root = _mapping(payload, "manifest")
    schema_version = _integer(root.get("schemaVersion"), "schemaVersion")
    if schema_version != 1:
        raise ConfigurationError(f"Unsupported schemaVersion {schema_version}; expected 1")

    viewport_value = _mapping(root.get("canonicalViewport"), "canonicalViewport")
    viewport = Viewport(
        width=_integer(viewport_value.get("width"), "canonicalViewport.width"),
        height=_integer(viewport_value.get("height"), "canonicalViewport.height"),
    )
    if viewport.width <= 0 or viewport.height <= 0:
        raise ConfigurationError("canonicalViewport dimensions must be positive")

    comparison = _mapping(root.get("comparison"), "comparison")
    maximum_channel_difference = _integer(
        comparison.get("maximumChannelDifference"),
        "comparison.maximumChannelDifference",
    )
    maximum_app_owned_difference_ratio = _number(
        comparison.get("maximumAppOwnedDifferenceRatio"),
        "comparison.maximumAppOwnedDifferenceRatio",
    )
    if not 0 <= maximum_channel_difference <= 255:
        raise ConfigurationError("maximumChannelDifference must be between 0 and 255")
    if not 0 <= maximum_app_owned_difference_ratio <= 1:
        raise ConfigurationError("maximumAppOwnedDifferenceRatio must be between 0 and 1")

    profiles_value = _mapping(root.get("ownershipProfiles"), "ownershipProfiles")
    profiles: dict[str, OwnershipProfile] = {}
    for profile_name, raw_profile in profiles_value.items():
        profile_value = _mapping(raw_profile, f"ownershipProfiles.{profile_name}")
        default_ownership = _ownership(
            profile_value.get("defaultOwnership"),
            f"ownershipProfiles.{profile_name}.defaultOwnership",
        )
        raw_regions = _sequence(
            profile_value.get("regions", []),
            f"ownershipProfiles.{profile_name}.regions",
        )
        regions: list[OwnershipRegion] = []
        for index, raw_region in enumerate(raw_regions):
            context = f"ownershipProfiles.{profile_name}.regions[{index}]"
            region_value = _mapping(raw_region, context)
            regions.append(
                OwnershipRegion(
                    ownership=_ownership(region_value.get("ownership"), f"{context}.ownership"),
                    name=_string(region_value.get("name"), f"{context}.name"),
                    bounds=_parse_bounds(region_value.get("bounds"), f"{context}.bounds", viewport),
                )
            )
        profiles[profile_name] = OwnershipProfile(
            name=profile_name,
            default_ownership=default_ownership,
            regions=tuple(regions),
        )
    if not profiles:
        raise ConfigurationError("ownershipProfiles must not be empty")

    resolved_repository_root = (
        repository_root.resolve()
        if repository_root is not None
        else discover_repository_root(path.parent)
    )
    raw_scenes = _sequence(root.get("scenes"), "scenes")
    scenes: list[Scene] = []
    seen_scene_ids: set[str] = set()
    seen_actual_files: set[str] = set()
    for index, raw_scene in enumerate(raw_scenes):
        context = f"scenes[{index}]"
        scene_value = _mapping(raw_scene, context)
        scene_id = _string(scene_value.get("id"), f"{context}.id")
        actual_file = _string(scene_value.get("actualFile"), f"{context}.actualFile")
        reference = _string(scene_value.get("reference"), f"{context}.reference")
        reference_sha256 = _string(
            scene_value.get("referenceSha256"),
            f"{context}.referenceSha256",
        ).lower()
        profile_name = _string(
            scene_value.get("ownershipProfile"),
            f"{context}.ownershipProfile",
        )
        if scene_id in seen_scene_ids:
            raise ConfigurationError(f"Duplicate scene id: {scene_id}")
        if actual_file in seen_actual_files:
            raise ConfigurationError(f"Duplicate actualFile: {actual_file}")
        if profile_name not in profiles:
            raise ConfigurationError(f"{context} references unknown ownership profile {profile_name}")
        if Path(reference).is_absolute() or ".." in Path(reference).parts:
            raise ConfigurationError(f"{context}.reference must be repository-relative")
        if Path(actual_file).name != actual_file:
            raise ConfigurationError(f"{context}.actualFile must be a plain file name")
        if len(reference_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in reference_sha256
        ):
            raise ConfigurationError(f"{context}.referenceSha256 must be a lowercase SHA-256")
        raw_anchors = _sequence(scene_value.get("anchors"), f"{context}.anchors")
        anchors = tuple(
            _mapping(anchor, f"{context}.anchors[{anchor_index}]")
            for anchor_index, anchor in enumerate(raw_anchors)
        )
        if not anchors:
            raise ConfigurationError(f"{context}.anchors must not be empty")
        scenes.append(
            Scene(
                scene_id=scene_id,
                actual_file=actual_file,
                reference_path=(resolved_repository_root / reference).resolve(),
                reference_sha256=reference_sha256,
                ownership_profile=profiles[profile_name],
                anchors=anchors,
            )
        )
        seen_scene_ids.add(scene_id)
        seen_actual_files.add(actual_file)
    if not scenes:
        raise ConfigurationError("scenes must not be empty")

    return Manifest(
        path=path,
        repository_root=resolved_repository_root,
        viewport=viewport,
        maximum_channel_difference=maximum_channel_difference,
        maximum_app_owned_difference_ratio=maximum_app_owned_difference_ratio,
        scenes=tuple(scenes),
    )


def selected_scenes(manifest: Manifest, requested: Sequence[str]) -> tuple[Scene, ...]:
    if not requested:
        return manifest.scenes
    scene_by_id = {scene.scene_id: scene for scene in manifest.scenes}
    unknown = sorted(set(requested) - scene_by_id.keys())
    if unknown:
        raise ConfigurationError(f"Unknown scenario(s): {', '.join(unknown)}")
    return tuple(scene_by_id[scene_id] for scene_id in requested)


def validate_reference(scene: Scene, viewport: Viewport) -> Image.Image:
    path = scene.reference_path
    if not path.is_file():
        raise ConfigurationError(
            f"Missing authoritative reference for '{scene.scene_id}': {path}"
        )
    actual_sha256 = _sha256(path)
    if actual_sha256 != scene.reference_sha256:
        raise ConfigurationError(
            f"Reference checksum mismatch for '{scene.scene_id}': expected "
            f"{scene.reference_sha256}, found {actual_sha256} at {path}"
        )
    try:
        with Image.open(path) as source:
            source.load()
            image = source.convert("RGB")
    except (OSError, ValueError) as exc:
        raise ConfigurationError(
            f"Unable to decode reference for '{scene.scene_id}': {path}: {exc}"
        ) from exc
    if image.size != (viewport.width, viewport.height):
        raise ConfigurationError(
            f"Reference viewport mismatch for '{scene.scene_id}': expected "
            f"{viewport.width}x{viewport.height}, found {image.width}x{image.height} at {path}"
        )
    return image


def validate_manifest_references(manifest: Manifest, scenes: Sequence[Scene]) -> None:
    failures: list[str] = []
    for scene in scenes:
        try:
            validate_reference(scene, manifest.viewport).close()
        except ConfigurationError as exc:
            failures.append(str(exc))
    if failures:
        raise ConfigurationError("Reference validation failed:\n- " + "\n- ".join(failures))


def _load_actual(path: Path, scene: Scene, viewport: Viewport) -> Image.Image:
    if not path.is_file():
        raise ConfigurationError(f"Missing actual capture for '{scene.scene_id}': {path}")
    try:
        with Image.open(path) as source:
            source.load()
            image = source.convert("RGB")
    except (OSError, ValueError) as exc:
        raise ConfigurationError(
            f"Unable to decode actual capture for '{scene.scene_id}': {path}: {exc}"
        ) from exc
    if image.size != (viewport.width, viewport.height):
        raise ConfigurationError(
            f"Actual viewport mismatch for '{scene.scene_id}': expected "
            f"{viewport.width}x{viewport.height}, found {image.width}x{image.height} at {path}"
        )
    return image


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_output_directory(
    output_directory: Path,
    actual_directory: Path,
    repository_root: Path,
) -> Path:
    output = output_directory.resolve()
    actual = actual_directory.resolve()
    protected = (
        (repository_root / "docs" / "assets" / "mobile-app-hifi-v1").resolve(),
        (
            repository_root
            / "apps"
            / "mobile"
            / "androidApp"
            / "src"
            / "androidTest"
            / "assets"
        ).resolve(),
        actual,
    )
    for protected_path in protected:
        if output == protected_path or _is_relative_to(output, protected_path):
            raise ConfigurationError(
                f"Refusing to write evidence under protected input/baseline path: {output}"
            )
    if output.exists() and any(output.iterdir()):
        raise ConfigurationError(
            f"Output directory must be empty or absent to prevent stale evidence: {output}"
        )
    return output


def prepare_scenes(
    manifest: Manifest,
    scenes: Sequence[Scene],
    actual_directory: Path,
) -> tuple[PreparedScene, ...]:
    actual_root = actual_directory.resolve()
    if not actual_root.is_dir():
        raise ConfigurationError(f"Actual directory does not exist: {actual_root}")
    prepared: list[PreparedScene] = []
    failures: list[str] = []
    for scene in scenes:
        reference_image: Image.Image | None = None
        actual_image: Image.Image | None = None
        try:
            reference_image = validate_reference(scene, manifest.viewport)
            actual_path = actual_root / scene.actual_file
            actual_image = _load_actual(actual_path, scene, manifest.viewport)
            prepared.append(
                PreparedScene(
                    scene=scene,
                    actual_path=actual_path,
                    reference_image=reference_image,
                    actual_image=actual_image,
                )
            )
        except ConfigurationError as exc:
            if reference_image is not None:
                reference_image.close()
            if actual_image is not None:
                actual_image.close()
            failures.append(str(exc))
    if failures:
        for item in prepared:
            item.reference_image.close()
            item.actual_image.close()
        raise ConfigurationError("Comparison inputs are invalid:\n- " + "\n- ".join(failures))
    return tuple(prepared)


def build_ownership_map(scene: Scene, viewport: Viewport) -> bytearray:
    default_code = OWNERSHIP_CODES[scene.ownership_profile.default_ownership]
    ownership_map = bytearray([default_code]) * (viewport.width * viewport.height)
    for region in scene.ownership_profile.regions:
        x, y, width, height = region.bounds
        code = OWNERSHIP_CODES[region.ownership]
        for row in range(y, y + height):
            offset = row * viewport.width + x
            ownership_map[offset : offset + width] = bytes([code]) * width
    return ownership_map


def _region_metrics_template() -> dict[str, dict[str, object]]:
    return {
        ownership: {
            "ownership": OWNERSHIP_NAMES[ownership],
            "comparedPixels": 0,
            "differentPixels": 0,
            "differentPixelRatio": 0.0,
            "maximumObservedChannelDifference": 0,
        }
        for ownership in OWNERSHIP_CODES
    }


def compare_scene(
    prepared: PreparedScene,
    manifest: Manifest,
    output_directory: Path,
) -> Mapping[str, object]:
    scene = prepared.scene
    reference = prepared.reference_image
    actual = prepared.actual_image
    ownership_map = build_ownership_map(scene, manifest.viewport)
    difference = ImageChops.difference(reference, actual)
    difference_pixels = list(difference.get_flattened_data())
    region_metrics = _region_metrics_template()
    heatmap_pixels: list[tuple[int, int, int, int]] = []

    code_to_ownership = {code: ownership for ownership, code in OWNERSHIP_CODES.items()}
    threshold = manifest.maximum_channel_difference
    for index, channels in enumerate(difference_pixels):
        maximum_difference = max(channels)
        ownership = code_to_ownership[ownership_map[index]]
        metrics = region_metrics[ownership]
        metrics["comparedPixels"] = int(metrics["comparedPixels"]) + 1
        metrics["maximumObservedChannelDifference"] = max(
            int(metrics["maximumObservedChannelDifference"]),
            maximum_difference,
        )
        is_different = maximum_difference > threshold
        if is_different:
            metrics["differentPixels"] = int(metrics["differentPixels"]) + 1

        if maximum_difference == 0:
            heatmap_pixels.append((0, 0, 0, 0))
        elif ownership == "C":
            heatmap_pixels.append((255, 32, 32, max(64, maximum_difference)))
        elif ownership == "B":
            heatmap_pixels.append((255, 180, 0, max(48, maximum_difference)))
        else:
            heatmap_pixels.append((40, 120, 255, max(48, maximum_difference)))

    for metrics in region_metrics.values():
        compared = int(metrics["comparedPixels"])
        different = int(metrics["differentPixels"])
        metrics["differentPixelRatio"] = different / compared if compared else 0.0

    app_owned_ratio = float(region_metrics["C"]["differentPixelRatio"])
    passes_app_owned_gate = (
        app_owned_ratio <= manifest.maximum_app_owned_difference_ratio
    )
    scene_id = scene.scene_id
    reference_output = output_directory / "reference" / f"{scene_id}.png"
    actual_output = output_directory / "actual" / f"{scene_id}.png"
    overlay_output = output_directory / "overlay" / f"{scene_id}.png"
    heatmap_output = output_directory / "heatmap" / f"{scene_id}.png"
    metrics_output = output_directory / "metrics" / f"{scene_id}.json"
    for directory in (
        reference_output.parent,
        actual_output.parent,
        overlay_output.parent,
        heatmap_output.parent,
        metrics_output.parent,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    reference.save(reference_output, format="PNG")
    actual.save(actual_output, format="PNG")
    Image.blend(reference, actual, 0.5).save(overlay_output, format="PNG")
    heatmap = Image.new("RGBA", reference.size)
    heatmap.putdata(heatmap_pixels)
    heatmap.save(heatmap_output, format="PNG")
    heatmap.close()

    metrics_payload: dict[str, object] = {
        "scene": scene_id,
        "verdict": "pass" if passes_app_owned_gate else "fail",
        "reference": {
            "repositoryRelativePath": str(
                scene.reference_path.relative_to(manifest.repository_root)
            ).replace("\\", "/"),
            "sha256": scene.reference_sha256,
            "viewport": {
                "width": manifest.viewport.width,
                "height": manifest.viewport.height,
            },
        },
        "actual": {
            "inputFile": scene.actual_file,
            "sha256": _sha256(prepared.actual_path),
        },
        "thresholds": {
            "maximumChannelDifference": manifest.maximum_channel_difference,
            "maximumAppOwnedDifferenceRatio": (
                manifest.maximum_app_owned_difference_ratio
            ),
        },
        "ownershipProfile": scene.ownership_profile.name,
        "ownershipMetrics": region_metrics,
        "appOwnedGate": {
            "passes": passes_app_owned_gate,
            "note": "Only C/App-owned pixels are blocking. A/B require Android platform review.",
        },
        "anchors": [dict(anchor) for anchor in scene.anchors],
        "anchorGate": {
            "status": "requires_semantic_or_manual_verification",
            "note": "Raster comparison does not infer semantic node bounds.",
        },
        "artifacts": {
            "reference": f"reference/{scene_id}.png",
            "actual": f"actual/{scene_id}.png",
            "overlay": f"overlay/{scene_id}.png",
            "heatmap": f"heatmap/{scene_id}.png",
        },
    }
    metrics_output.write_text(
        json.dumps(metrics_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return metrics_payload


def run_comparison(
    manifest: Manifest,
    scenes: Sequence[Scene],
    actual_directory: Path,
    output_directory: Path,
) -> tuple[Mapping[str, object], ...]:
    output = validate_output_directory(
        output_directory,
        actual_directory,
        manifest.repository_root,
    )
    prepared = prepare_scenes(manifest, scenes, actual_directory)
    output.mkdir(parents=True, exist_ok=True)
    results: list[Mapping[str, object]] = []
    try:
        for item in prepared:
            results.append(compare_scene(item, manifest, output))
    finally:
        for item in prepared:
            item.reference_image.close()
            item.actual_image.close()

    summary = {
        "manifest": str(manifest.path),
        "verdict": (
            "pass" if all(result["verdict"] == "pass" for result in results) else "fail"
        ),
        "sceneCount": len(results),
        "scenes": [
            {
                "id": result["scene"],
                "verdict": result["verdict"],
                "metrics": f"metrics/{result['scene']}.json",
            }
            for result in results
        ],
        "baselineWritten": False,
    }
    (output / "metrics" / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return tuple(results)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare 390x844 Android captures to immutable Warm Page references. "
            "The tool writes evidence only; it cannot update expected/golden assets."
        )
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("reference-manifest.json"),
        help="Reference manifest (default: script-adjacent reference-manifest.json)",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        help="Repository root override, primarily for isolated self-tests",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="Compare/check one scenario; repeat for multiple scenarios",
    )
    parser.add_argument(
        "--check-manifest",
        action="store_true",
        help="Validate selected authoritative references and exit without writing output",
    )
    parser.add_argument("--actual-dir", type=Path, help="Directory of canonical actual PNGs")
    parser.add_argument("--output-dir", type=Path, help="New/empty evidence directory")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest, args.repo_root)
        scenes = selected_scenes(manifest, args.scenario)
        if args.check_manifest:
            validate_manifest_references(manifest, scenes)
            print(f"Validated {len(scenes)} immutable reference(s) from {manifest.path}")
            return 0
        if args.actual_dir is None or args.output_dir is None:
            raise ConfigurationError(
                "--actual-dir and --output-dir are required unless --check-manifest is used"
            )
        results = run_comparison(manifest, scenes, args.actual_dir, args.output_dir)
        failed = [str(result["scene"]) for result in results if result["verdict"] != "pass"]
        if failed:
            print(
                "C/App-owned fidelity gate failed for: " + ", ".join(failed),
                file=sys.stderr,
            )
            return EXIT_DIFFERENCE
        print(f"Compared {len(results)} scene(s); C/App-owned fidelity gate passed")
        return 0
    except ConfigurationError as exc:
        print(f"Android Warm Page comparison configuration error:\n{exc}", file=sys.stderr)
        return EXIT_CONFIGURATION


if __name__ == "__main__":
    raise SystemExit(main())
