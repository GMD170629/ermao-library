#!/usr/bin/env bash

set -euo pipefail

./gradlew :androidApp:assembleDebug :androidApp:assembleDebugAndroidTest
adb install -r -t androidApp/build/outputs/apk/debug/androidApp-debug.apk
adb install -r -t androidApp/build/outputs/apk/androidTest/debug/androidApp-debug-androidTest.apk

instrumentation_args=()
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
adb exec-out run-as com.ermao.library \
  cat files/reader-safety-conformance/android.json \
  > androidApp/build/reports/reader-safety-conformance/android.json
test -s androidApp/build/reports/reader-safety-conformance/android.json
python3 ../../packages/reader-contracts/verify-reader-safety-conformance.py \
  --require-consumer ANDROID \
  androidApp/build/reports/reader-safety-conformance/android.json

adb logcat -c
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
grep 'versionCode=1' <<<"$package_dump" >/dev/null
grep 'versionName=1.0.0' <<<"$package_dump" >/dev/null

app_ready=false
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
if grep 'FATAL EXCEPTION' <<<"$crash_log" >/dev/null; then
  printf '%s\n' "$crash_log"
  exit 1
fi
