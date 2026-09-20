import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('../apps/mobile/scripts/run-android-emulator-tests.sh', import.meta.url), 'utf8');
const startup = source.slice(source.indexOf('\napp_ready=false'));
assert.ok(startup.includes('startup_stage=login-screen'));

function run(scenario) {
  return spawnSync(process.env.BASH ?? 'bash', ['-s'], {
    encoding: 'utf8',
    env: { ...process.env, STARTUP_SCENARIO: scenario },
    input: `set -euo pipefail
recovered=false
sleep() { :; }
adb() {
  case "$*" in
    'shell dumpsys activity activities')
      case "$STARTUP_SCENARIO" in
        launcher|persistent) echo 'mCurrentFocus=Window{123 u0 Application Not Responding: com.android.launcher3}';;
        app) echo 'mCurrentFocus=Window{123 u0 Application Not Responding: com.ermao.library}';;
        other) echo 'mCurrentFocus=Window{123 u0 Application Not Responding: com.android.launcher3.other}';;
      esac;;
    'shell am force-stop com.android.launcher3')
      echo 'stopped-launcher'
      recovered=true;;
    'shell uiautomator dump /sdcard/mobile-stage-1.xml') :;;
    'shell cat /sdcard/mobile-stage-1.xml')
      if [[ "$STARTUP_SCENARIO" == healthy || "$STARTUP_SCENARIO" == crash ]] \\
        || { [[ "$STARTUP_SCENARIO" == launcher && "$recovered" == true ]]; }; then
        echo 'Log in to your library'
      else
        echo 'ANR dialog'
      fi;;
    'logcat -d -b crash')
      if [[ "$STARTUP_SCENARIO" == crash ]]; then echo 'FATAL EXCEPTION'; fi;;
    *) echo "Unexpected adb call: $*" >&2; return 99;;
  esac
}
${startup}`
  });
}

test('login succeeds normally and after a single Quickstep recovery', () => {
  for (const scenario of ['healthy', 'launcher']) {
    const result = run(scenario);
    assert.equal(result.status, 0, result.stderr);
    assert.equal((result.stdout.match(/stopped-launcher/g) ?? []).length, scenario === 'launcher' ? 1 : 0);
  }
});

test('persistent launcher ANR fails after one recovery; other ANRs and crashes remain failures', () => {
  for (const scenario of ['persistent', 'app', 'other', 'crash']) {
    const result = run(scenario);
    assert.equal(result.status, 1, result.stderr);
    assert.equal((result.stdout.match(/stopped-launcher/g) ?? []).length, scenario === 'persistent' ? 1 : 0);
  }
});
