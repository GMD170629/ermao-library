#!/usr/bin/env bash

set -euo pipefail

startup_stage=build
capture_failure() {
  status=$?
  trap - EXIT
  if [[ "$status" != 0 ]]; then
    echo "Android validation failed during $startup_stage (exit $status)." >&2
    report_dir=androidApp/build/reports/androidTests/manual
    mkdir -p "$report_dir"
    adb shell dumpsys activity activities > "$report_dir/startup-activity.txt" 2>&1 || echo 'Could not capture activities.' >&2
    adb logcat -d -b crash > "$report_dir/startup-crash.txt" 2>&1 || echo 'Could not capture crash log.' >&2
    adb shell uiautomator dump /sdcard/mobile-stage-1.xml || echo 'Could not dump startup UI.' >&2
    adb shell cat /sdcard/mobile-stage-1.xml > "$report_dir/startup-ui.xml" 2>&1 || echo 'Could not capture startup UI.' >&2
  fi
  exit "$status"
}
trap capture_failure EXIT

./gradlew :androidApp:assembleDebug :androidApp:assembleDebugAndroidTest
adb install -r -t androidApp/build/outputs/apk/debug/androidApp-debug.apk
adb install -r -t androidApp/build/outputs/apk/androidTest/debug/androidApp-debug-androidTest.apk

instrumentation_args=()
startup_stage=instrumentation
if [[ "${RUN_FULL_ANDROID_REGRESSION:-false}" == "true" ]]; then
  echo 'Running complete Android instrumented regression.'
else
  instrumentation_args=(
    -e class
    'com.ermao.library.AndroidShellSmokeTest,com.ermao.library.features.reader.infrastructure.ReaderSafetyConformanceInstrumentedTest'
  )
fi

mkdir -p androidApp/build/reports/androidTests/manual
adb shell am instrument -w -r \
  "${instrumentation_args[@]}" \
  com.ermao.library.test/androidx.test.runner.AndroidJUnitRunner \
  | tee androidApp/build/reports/androidTests/manual/instrumentation.txt
grep -q 'OK (' androidApp/build/reports/androidTests/manual/instrumentation.txt
if grep -q 'FAILURES!!!' androidApp/build/reports/androidTests/manual/instrumentation.txt; then
  exit 1
fi

mkdir -p androidApp/build/reports/reader-safety-conformance
startup_stage=safety-conformance
adb exec-out run-as com.ermao.library \
  cat files/reader-safety-conformance/android.json \
  > androidApp/build/reports/reader-safety-conformance/android.json
test -s androidApp/build/reports/reader-safety-conformance/android.json
python3 ../../packages/reader-contracts/verify-reader-safety-conformance.py \
  --require-consumer ANDROID \
  androidApp/build/reports/reader-safety-conformance/android.json

adb logcat -c
startup_stage=cold-start-process
adb shell am force-stop com.ermao.library
adb shell monkey -p com.ermao.library -c android.intent.category.LAUNCHER 1
app_started=false
for attempt in $(seq 1 20); do
  if app_pid="$(adb shell pidof com.ermao.library 2>/dev/null)" \
    && grep -E '[0-9]+' <<<"$app_pid" >/dev/null; then
    app_started=true
    break
  fi
  sleep 1
done
test "$app_started" = true

package_dump="$(adb shell dumpsys package com.ermao.library)"
startup_stage=package-version
grep 'versionCode=1' <<<"$package_dump" >/dev/null
grep 'versionName=1.0.0' <<<"$package_dump" >/dev/null

app_ready=false
startup_stage=login-screen
for attempt in $(seq 1 20); do
  if adb shell uiautomator dump /sdcard/mobile-stage-1.xml >/dev/null \
    && ui_dump="$(adb shell cat /sdcard/mobile-stage-1.xml)" \
    && grep 'Log in to your library' <<<"$ui_dump" >/dev/null; then
    app_ready=true
    break
  fi
  sleep 1
done
test "$app_ready" = true

crash_log="$(adb logcat -d -b crash)"
startup_stage=crash-check
if grep 'FATAL EXCEPTION' <<<"$crash_log" >/dev/null; then
  printf '%s\n' "$crash_log"
  exit 1
fi
