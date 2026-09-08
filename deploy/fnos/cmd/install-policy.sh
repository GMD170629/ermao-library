#!/bin/bash
set -eu

installation_error() {
  case "${TRIM_SYS_LANGUAGE:-zh-CN}" in
    en*) printf '%s\n' "$2" > "${TRIM_TEMP_LOGFILE:-/dev/stderr}" ;;
    *) printf '%s\n' "$1" > "${TRIM_TEMP_LOGFILE:-/dev/stderr}" ;;
  esac
  exit 1
}

validate_installation() {
  case "${wizard_install_mode:-}" in
    fresh|update) ;;
    *)
      installation_error \
        '请选择“全新安装”或“更新”。' \
        'Select Fresh install or Update.'
      ;;
  esac

  case "${TRIM_OLD_APPVER:-}:${TRIM_APPVER:-}:$wizard_install_mode" in
    0.*:1.*:update)
      installation_error \
        '当前版本无法自动升级到 v1，请重新执行安装并选择“全新安装”。应用配置和数据将被清空，原始书库保留。' \
        'This version cannot be upgraded automatically to v1. Run installation again and select Fresh install. Application settings and data will be erased; original library files will be retained.'
      ;;
  esac
}

require_stopped_containers() {
  . "$(dirname "${BASH_SOURCE[0]}")/docker-runtime.sh"
  local states state
  if ! states="$(web_container_states)"; then
    installation_error \
      '无法确认应用容器已停止，全新安装已终止，未清空配置。请检查 Docker 后重试。' \
      'Cannot verify that the application containers are stopped. Fresh installation was stopped without erasing settings. Check Docker and try again.'
  fi
  while IFS= read -r state; do
    case "$state" in
      ''|created|exited|dead) ;;
      *)
        installation_error \
          '应用容器尚未停止，全新安装已终止，未清空配置。请在 fnOS 中停止应用后重试。' \
          'An application container is still active. Fresh installation was stopped without erasing settings. Stop the application in fnOS and try again.'
        ;;
    esac
  done <<< "$states"
}

reset_application_storage() {
  local package_var storage
  case "${TRIM_PKGVAR:-}" in
    /*) ;;
    *)
      installation_error '应用数据目录无效，无法执行全新安装。' \
        'The application data directory is invalid. Cannot perform a fresh installation.'
      ;;
  esac
  if ! package_var="$(realpath -e -- "$TRIM_PKGVAR" 2>/dev/null)" || [ "$package_var" = / ] || [ ! -d "$package_var" ]; then
    installation_error '应用数据目录无效，无法执行全新安装。' \
      'The application data directory is invalid. Cannot perform a fresh installation.'
  fi
  storage="$package_var/storage"
  if [ -L "$storage" ] || { [ -e "$storage" ] && [ ! -d "$storage" ]; }; then
    installation_error '应用配置目录必须是数据目录内的实际目录，无法执行全新安装。' \
      'Application storage must be a real directory inside the application data directory. Cannot perform a fresh installation.'
  fi
  if [ -d "$storage" ]; then
    # Preserve the storage directory; unlink nested symlinks without following them.
    # Do not cross nested filesystem mounts. A failed removal stops installation.
    if ! find -P "$storage" -xdev -mindepth 1 -delete 2>/dev/null; then
      installation_error '应用配置清空失败，安装已终止。请检查目录权限后重试。' \
        'Could not erase application settings. Installation was stopped. Check directory permissions and try again.'
    fi
  fi
  printf '%s\n' 'event=fnos.install mode=fresh stage=reset outcome=completed'
}

validate_installation
case "${1:-}" in
  validate) ;;
  apply)
    if [ "$wizard_install_mode" = fresh ]; then
      require_stopped_containers
      reset_application_storage
    fi
    ;;
  *)
    installation_error '安装策略操作无效。' 'Invalid installation policy operation.'
    ;;
esac
