#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE_DIR="$ROOT_DIR/deploy/fnos"
APP_VERSION="${APP_VERSION:-$(node -p "require('$ROOT_DIR/package.json').version")}"
IMAGE_REFERENCE="gamersgu/shuku-starship-web:${APP_VERSION}"
FNPACK_BIN="${FNPACK_BIN:-fnpack}"
VALIDATE_ONLY="${FNOS_VALIDATE_ONLY:-false}"
OUTPUT_DIR="${OUTPUT_DIR:-$ROOT_DIR/dist/fnos}"
BUILD_ROOT="${BUILD_ROOT:-$ROOT_DIR/.fnos-build}"
PACKAGE_DIR="$BUILD_ROOT/ermao-books"

if [[ ! "$APP_VERSION" =~ ^[0-9]+([.][0-9]+){0,2}(-[A-Za-z0-9._-]+)?$ ]]; then
  echo "Invalid APP_VERSION: $APP_VERSION" >&2
  exit 2
fi

if [ "$VALIDATE_ONLY" != "true" ] && [ "$VALIDATE_ONLY" != "false" ]; then
  echo "FNOS_VALIDATE_ONLY must be true or false" >&2
  exit 2
fi

if [ "$VALIDATE_ONLY" = "false" ] && ! command -v "$FNPACK_BIN" >/dev/null 2>&1; then
  echo "fnpack was not found. Set FNPACK_BIN or install it from https://developer.fnnas.com/docs/cli/fnpack/" >&2
  exit 1
fi

rm -rf "$BUILD_ROOT"
mkdir -p "$PACKAGE_DIR" "$OUTPUT_DIR"
cp -R "$TEMPLATE_DIR"/. "$PACKAGE_DIR"/

sed -i.bak "s|__APP_VERSION__|$APP_VERSION|g" "$PACKAGE_DIR/manifest"
sed -i.bak "s|__IMAGE_REFERENCE__|$IMAGE_REFERENCE|g" \
  "$PACKAGE_DIR/app/docker/docker-compose.yaml"
rm -f "$PACKAGE_DIR/manifest.bak" "$PACKAGE_DIR/app/docker/docker-compose.yaml.bak"

find "$PACKAGE_DIR/cmd" -type f -exec chmod 755 {} +
chmod 755 \
  "$PACKAGE_DIR/app/docker/prepare-storage.sh" \
  "$PACKAGE_DIR/app/docker/validate-port.sh"
bash -n "$PACKAGE_DIR"/cmd/*
bash -n "$PACKAGE_DIR/app/docker/prepare-storage.sh"
bash -n "$PACKAGE_DIR/app/docker/validate-port.sh"

if grep -R -n -E '__APP_VERSION__|__IMAGE_REFERENCE__' "$PACKAGE_DIR"; then
  echo "fnOS package still contains unresolved template placeholders" >&2
  exit 1
fi

python3 - \
  "$PACKAGE_DIR/config/privilege" \
  "$PACKAGE_DIR/config/resource" \
  "$PACKAGE_DIR/app/ui/config" \
  "$PACKAGE_DIR/manifest" \
  "$PACKAGE_DIR/wizard/install" \
  "$PACKAGE_DIR/wizard/upgrade" \
  "$PACKAGE_DIR/wizard/config" <<'PY'
import json
import sys

(
    privilege_path,
    resource_path,
    ui_config_path,
    manifest_path,
    install_wizard_path,
    upgrade_wizard_path,
    config_wizard_path,
) = sys.argv[1:]

with open(privilege_path, encoding="utf-8") as file:
    privilege = json.load(file)
if privilege.get("defaults", {}).get("run-as") != "package":
    raise SystemExit("fnOS lifecycle scripts must run as the dedicated package user")
if privilege.get("join-groups"):
    raise SystemExit("fnOS package user must not retain unnecessary supplementary groups")

with open(resource_path, encoding="utf-8") as file:
    resource = json.load(file)
shares = resource.get("data-share", {}).get("shares", [])
if shares != [{"name": "shuku.monitor"}]:
    raise SystemExit("fnOS must declare the shuku.monitor shared data directory")
projects = resource.get("docker-project", {}).get("projects", [])
if projects != [{"name": "ermao-books", "path": "docker"}]:
    raise SystemExit("fnOS Docker project resource declaration is invalid")

with open(manifest_path, encoding="utf-8") as file:
    manifest = dict(
        line.rstrip("\n").split("=", 1)
        for line in file
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    )
if manifest.get("disable_authorization_path") != "true":
    raise SystemExit("fnOS arbitrary directory authorization must remain disabled")
if manifest.get("platform") != "all":
    raise SystemExit("fnOS package must support all published image architectures")
expected_metadata = {
    "maintainer": "六面体",
    "maintainer_url": "https://github.com/GMD170629/ermao-library",
    "distributor": "六面体",
    "distributor_url": "https://github.com/GMD170629/ermao-library",
}
metadata_errors = [
    f"{key}: expected {value!r}, got {manifest.get(key)!r}"
    for key, value in expected_metadata.items()
    if manifest.get(key) != value
]
if metadata_errors:
    raise SystemExit("Invalid fnOS publisher metadata:\n- " + "\n- ".join(metadata_errors))
for required_description_text in (
    "自托管",
    "书库管理",
    "EPUB",
    "漫画",
    "PDF",
    "家庭 NAS",
    "有声书",
    "M4B",
    "M4A",
    "MP3",
    "多分轨",
    "倍速",
    "睡眠定时",
    "进度同步",
    "https://www.bilibili.com/video/BV1r2KA6FEfL/",
    "154560969",
):
    if required_description_text not in manifest.get("desc", ""):
        raise SystemExit(f"fnOS description must explain {required_description_text!r}")

with open(ui_config_path, encoding="utf-8") as file:
    ui_config = json.load(file)
entry_id = manifest.get("desktop_applaunchname")
entry = ui_config.get(".url", {}).get(entry_id)
expected_entry = {
    "title": manifest.get("display_name"),
    "icon": "images/icon_v2_{0}.png",
    "type": "url",
    "protocol": "http",
    "port": "${wizard_port}",
    "url": "/",
    "allUsers": True,
}
if entry is None:
    raise SystemExit(f"fnOS desktop entry {entry_id!r} is missing")
entry_errors = [
    f"{key}: expected {value!r}, got {entry.get(key)!r}"
    for key, value in expected_entry.items()
    if entry.get(key) != value
]
if entry_errors:
    raise SystemExit("Invalid fnOS desktop entry:\n- " + "\n- ".join(entry_errors))

expected_pattern = (
    r"^(102[4-9]|10[3-9][0-9]|1[1-9][0-9]{2}|[2-9][0-9]{3}|"
    r"[1-5][0-9]{4}|6[0-4][0-9]{3}|65[0-4][0-9]{2}|655[0-2][0-9]|6553[0-5])$"
)
for wizard_path in (install_wizard_path, upgrade_wizard_path, config_wizard_path):
    with open(wizard_path, encoding="utf-8") as file:
        steps = json.load(file)
    items = [item for step in steps for item in step.get("items", [])]
    port_item = next((item for item in items if item.get("field") == "wizard_port"), None)
    if port_item is None or port_item.get("initValue") != "3000":
        raise SystemExit(f"{wizard_path} must collect wizard_port with a 3000 default")
    patterns = [rule.get("pattern") for rule in port_item.get("rules", []) if "pattern" in rule]
    if expected_pattern not in patterns:
        raise SystemExit(f"{wizard_path} does not constrain wizard_port to 1024-65535")

with open(install_wizard_path, encoding="utf-8") as file:
    install_steps = json.load(file)
install_help = " ".join(
    item.get("helpText", "")
    for step in install_steps
    for item in step.get("items", [])
)
for required_text in ("/shuku.monitor", "/monitor", "共享数据目录"):
    if required_text not in install_help:
        raise SystemExit(f"fnOS install guide must explain {required_text!r}")
PY

compose="$PACKAGE_DIR/app/docker/docker-compose.yaml"
if ! grep -Fq "image: $IMAGE_REFERENCE" "$compose" || \
   ! grep -Fq 'user: "${TRIM_UID}:${TRIM_GID}"' "$compose" || \
   ! grep -Fq '${TRIM_PKGVAR}/storage:/app/storage' "$compose" || \
   ! grep -Fq '${TRIM_DATA_SHARE_PATHS}:/monitor' "$compose" || \
   grep -Fq 'MONITOR_ROOT' "$compose"; then
  echo "fnOS Compose is missing the versioned image, package user, or required data mounts" >&2
  exit 1
fi

if grep -Eq '^[[:space:]]*platform:[[:space:]]*(linux/)?(amd64|arm64)' "$compose"; then
  echo "fnOS Compose must select the image architecture automatically" >&2
  exit 1
fi

if grep -R -n -E 'TRIM_DATA_ACCESSIBLE_PATHS|sync-accessible-mounts|run-as["'"'"':[:space:]]+root' \
  "$PACKAGE_DIR/cmd" "$PACKAGE_DIR/app" "$PACKAGE_DIR/config"; then
  echo "fnOS package still contains root or dynamic authorized-path handling" >&2
  exit 1
fi

for callback in install_callback config_callback upgrade_callback; do
  if grep -Eq 'sudo|docker[[:space:]]+(info|compose|ps|inspect)|force-recreate' \
    "$PACKAGE_DIR/cmd/$callback"; then
    echo "fnOS $callback must not manage Docker directly" >&2
    exit 1
  fi
  if ! grep -Fq 'validate-port.sh' "$PACKAGE_DIR/cmd/$callback"; then
    echo "fnOS $callback does not validate the configured host port" >&2
    exit 1
  fi
  if ! grep -Fq 'prepare-storage.sh' "$PACKAGE_DIR/cmd/$callback"; then
    echo "fnOS $callback does not prepare persistent storage" >&2
    exit 1
  fi
done

if ! grep -Fq 'label=com.docker.compose.project=ermao-books' "$PACKAGE_DIR/cmd/main" || \
   ! grep -Fq 'label=com.docker.compose.service=web' "$PACKAGE_DIR/cmd/main" || \
   ! grep -Fq 'exit 3' "$PACKAGE_DIR/cmd/main"; then
  echo "fnOS cmd/main does not accurately report the Docker service status" >&2
  exit 1
fi

if ! cmp -s "$PACKAGE_DIR/ICON.PNG" "$PACKAGE_DIR/app/ui/images/icon_64.png" || \
   ! cmp -s "$PACKAGE_DIR/ICON_256.PNG" "$PACKAGE_DIR/app/ui/images/icon_256.png" || \
   ! cmp -s "$PACKAGE_DIR/ICON.PNG" "$PACKAGE_DIR/app/ui/images/icon_v2_64.png" || \
   ! cmp -s "$PACKAGE_DIR/ICON_256.PNG" "$PACKAGE_DIR/app/ui/images/icon_v2_256.png"; then
  echo "fnOS package icons are not synchronized" >&2
  exit 1
fi

port_validation_log="$BUILD_ROOT/port-validation.log"
for valid_port in 1024 3000 65535; do
  wizard_port="$valid_port" TRIM_TEMP_LOGFILE="$port_validation_log" \
    bash "$PACKAGE_DIR/app/docker/validate-port.sh"
done

storage_validation_root="$BUILD_ROOT/storage-validation"
TRIM_PKGVAR="$storage_validation_root" \
  bash "$PACKAGE_DIR/app/docker/prepare-storage.sh"
for storage_subdirectory in \
  database covers indexes conversions temp/conversions logs secrets; do
  if [ ! -d "$storage_validation_root/storage/$storage_subdirectory" ]; then
    echo "fnOS storage preparation did not create $storage_subdirectory" >&2
    exit 1
  fi
done
for invalid_port in 0 80 1023 65536 not-a-port; do
  if wizard_port="$invalid_port" TRIM_TEMP_LOGFILE="$port_validation_log" \
    bash "$PACKAGE_DIR/app/docker/validate-port.sh"; then
    echo "fnOS port validation accepted invalid port: $invalid_port" >&2
    exit 1
  fi
done

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  validation_dir="$BUILD_ROOT/validation"
  mkdir -p "$validation_dir/var" "$validation_dir/library"
  services="$(
    TRIM_PKGVAR="$validation_dir/var" \
    TRIM_DATA_SHARE_PATHS="$validation_dir/library" \
    TRIM_UID=1000 \
    TRIM_GID=1000 \
    wizard_port=3000 \
      docker compose -f "$compose" config --services
  )"
  if [ "$services" != "web" ]; then
    echo "fnOS Compose services do not match the expected topology" >&2
    exit 1
  fi
fi

if [ "$VALIDATE_ONLY" = "true" ]; then
  echo "Validated fnOS package template: $PACKAGE_DIR"
  exit 0
fi

(
  cd "$PACKAGE_DIR"
  "$FNPACK_BIN" build
)

artifact="$(find "$BUILD_ROOT" -maxdepth 3 -type f -name '*.fpk' -print -quit)"
if [ -z "$artifact" ]; then
  echo "fnpack completed without producing an .fpk artifact" >&2
  exit 1
fi

if ! cmp -s "$PACKAGE_DIR/ICON.PNG" <(tar -xOzf "$artifact" ICON.PNG) || \
   ! cmp -s "$PACKAGE_DIR/ICON_256.PNG" <(tar -xOzf "$artifact" ICON_256.PNG); then
  echo "Built fnOS artifact does not contain the current package icons" >&2
  exit 1
fi

destination="$OUTPUT_DIR/ermao-books-${APP_VERSION}-all.fpk"
cp "$artifact" "$destination"

echo "Built fnOS package: $destination"
