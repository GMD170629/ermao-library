import argparse
import json
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import python_release_live_fixture as fixture_module
from python_release_live_fixture import (
    FixtureLifecycle,
    FixtureStoppedError,
    NextConfigurationConflict,
    NextConfigurationFile,
    _build_production_web,
    _configuration_file,
    _fixture_lifecycle,
    _next_command,
    _prepare_next_configuration,
    _wait_for_stop,
    _wait_for_web,
)
from python_smoke_process import LoggedProcess


@pytest.fixture
def lifecycle(tmp_path: Path) -> FixtureLifecycle:
    return FixtureLifecycle(
        tmp_path,
        tmp_path / "stop",
        tmp_path / "shutdown-complete",
        time.monotonic() + 1_200,
    )


def shutdown_result(lifecycle: FixtureLifecycle) -> dict[str, object]:
    return json.loads(
        (lifecycle.artifact_dir / "shutdown-result.json").read_text(encoding="utf-8")
    )


def test_runtime_commands_keep_production_opt_in_and_loopback_bound() -> None:
    with patch("python_release_live_fixture._pnpm_command", return_value=["pnpm"]):
        assert _next_command(3101) == [
            "pnpm",
            "exec",
            "next",
            "dev",
            "--webpack",
            "-H",
            "127.0.0.1",
            "-p",
            "3101",
        ]
        assert _next_command(3101, "production") == [
            "pnpm",
            "exec",
            "next",
            "start",
            "-H",
            "127.0.0.1",
            "-p",
            "3101",
        ]
        with pytest.raises(KeyError):
            _next_command(3101, "publish")


@pytest.mark.parametrize("outcome", [0, 1, "timeout"])
def test_build_uses_existing_script_and_always_reaps_its_process(
    outcome: int | str,
    lifecycle: FixtureLifecycle,
) -> None:
    clock = [0.0]
    with (
        patch("python_release_live_fixture._pnpm_command", return_value=["pnpm"]),
        patch("python_release_live_fixture.start_logged_process") as start,
        patch(
            "python_release_live_fixture.time.monotonic", side_effect=lambda: clock[0]
        ),
    ):
        build = start.return_value
        if outcome == "timeout":

            def wait_until_deadline(*, timeout: float) -> int:
                clock[0] = 601.0
                raise subprocess.TimeoutExpired("build", timeout)

            build.wait.side_effect = wait_until_deadline
        else:
            build.wait.return_value = outcome
        env = {"NEXT_DIST_DIR": ".next-release-live-test"}
        if outcome == 0:
            with _fixture_lifecycle(lifecycle):
                _build_production_web(env, Path("next-build.log"), lifecycle)
        else:
            with (
                pytest.raises((RuntimeError, TimeoutError)),
                _fixture_lifecycle(lifecycle),
            ):
                _build_production_web(env, Path("next-build.log"), lifecycle)
        assert start.call_args.args[0] == ["pnpm", "run", "build"]
        assert start.call_args.kwargs["env"] == env
        build.wait.assert_called_once_with(timeout=0.25)
        build.stop.assert_called_once_with(timeout=12)
        assert lifecycle.shutdown_file.is_file()
        assert shutdown_result(lifecycle)["status"] == "stopped"


@pytest.mark.parametrize("lifetime", [599, 7801])
def test_fixture_rejects_unbounded_lifetime(tmp_path: Path, lifetime: int) -> None:
    with pytest.raises(ValueError, match="lifetime"):
        _wait_for_stop(tmp_path / "stop", {}, tmp_path / "events.log", lifetime)


def test_long_fixture_still_enforces_deadline_and_detects_early_exit(
    tmp_path: Path,
) -> None:
    with (
        patch("python_release_live_fixture.time.monotonic", side_effect=[0, 2401]),
        pytest.raises(TimeoutError, match="2400"),
    ):
        _wait_for_stop(tmp_path / "stop", {}, tmp_path / "events.log", 2400)
    with patch("python_release_live_fixture.start_logged_process") as start:
        process = start.return_value
        process.poll.return_value = 2
        process.returncode = 2
        with pytest.raises(RuntimeError, match="exited before"):
            _wait_for_stop(
                tmp_path / "stop", {"api": process}, tmp_path / "events.log", 2400
            )


@pytest.mark.parametrize("lifetime", [600, 7800])
def test_fixture_preserves_short_and_long_lifetime_boundaries(
    lifecycle: FixtureLifecycle,
    lifetime: int,
) -> None:
    lifecycle.stop_file.write_text("stop\n")
    _wait_for_stop(lifecycle.stop_file, {}, lifecycle.event_log, lifetime)


def test_engine_preflight_failure_has_terminal_cleanup_without_starting_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "run"
    args = argparse.Namespace(
        artifact_dir=root,
        manifest=root / "manifest.json",
        stop_file=root / "stop",
        shutdown_file=root / "shutdown-complete",
        run_id="unit-preflight",
        api_port=18081,
        web_port=3102,
        lifetime_seconds=600,
        startup_timeout_seconds=1200,
        web_runtime="production",
        web_hostname="release-live.localhost",
    )
    primary = RuntimeError("Chapter engine is unavailable")
    monkeypatch.setenv("RELEASE_LIVE_E2E", "1")
    with (
        patch.object(fixture_module, "_parse_args", return_value=args),
        patch.object(fixture_module, "_git_head", return_value="unit-head"),
        patch.object(fixture_module, "_resolve_ffprobe", return_value=None),
        patch.object(
            fixture_module, "_resolve_port", side_effect=lambda value, name: value
        ),
        patch.object(fixture_module, "_build_samples", return_value=[]),
        patch.object(fixture_module.ChapterCore, "load", side_effect=primary),
        patch.object(fixture_module, "start_logged_process") as start,
        pytest.raises(RuntimeError) as failure,
    ):
        fixture_module.main()
    assert failure.value is primary
    start.assert_not_called()
    assert (root / "shutdown-complete").is_file()
    result = json.loads((root / "shutdown-result.json").read_text(encoding="utf-8"))
    assert result == {
        "status": "stopped",
        "stage": "chapter-engine",
        "primaryError": "Chapter engine is unavailable",
        "cleanupErrors": [],
        "processesStopped": True,
    }
    assert "Chapter engine is unavailable" in (root / "fixture.log").read_text(
        encoding="utf-8"
    )


def test_cleanup_preserves_both_errors_and_attempts_every_child(
    lifecycle: FixtureLifecycle,
) -> None:
    primary = RuntimeError("original startup failure")
    cleanup = TimeoutError("owned child did not exit")
    good = MagicMock(spec=LoggedProcess)
    bad = MagicMock(spec=LoggedProcess)
    bad.stop.side_effect = cleanup
    lifecycle.processes.update({"good": good, "bad": bad})
    with pytest.raises(ExceptionGroup) as failure, _fixture_lifecycle(lifecycle):
        raise primary
    assert failure.value.exceptions == (primary, cleanup)
    good.stop.assert_called_once_with(timeout=12)
    bad.stop.assert_called_once_with(timeout=12)
    result = shutdown_result(lifecycle)
    assert result["primaryError"] == str(primary)
    assert result["cleanupErrors"] == ["TimeoutError: owned child did not exit"]
    assert result["processesStopped"] is False
    assert not lifecycle.shutdown_file.exists()


def test_main_preserves_cancellation_that_arrives_before_preflight(
    lifecycle: FixtureLifecycle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = argparse.Namespace(
        artifact_dir=lifecycle.artifact_dir,
        manifest=lifecycle.artifact_dir / "manifest.json",
        stop_file=lifecycle.stop_file,
        shutdown_file=lifecycle.shutdown_file,
        run_id="early-cancel",
        lifetime_seconds=600,
        startup_timeout_seconds=1200,
    )
    lifecycle.stop_file.write_text("stop\n")
    monkeypatch.setenv("RELEASE_LIVE_E2E", "1")
    with (
        patch.object(fixture_module, "_parse_args", return_value=args),
        patch.object(fixture_module, "_git_head") as git,
        patch.object(fixture_module.ChapterCore, "load") as engine,
        patch.object(fixture_module, "start_logged_process") as start,
        pytest.raises(FixtureStoppedError, match="preflight"),
    ):
        fixture_module.main()
    git.assert_not_called()
    engine.assert_not_called()
    start.assert_not_called()
    assert lifecycle.stop_file.read_text() == "stop\n"
    assert lifecycle.shutdown_file.is_file()
    assert shutdown_result(lifecycle)["stage"] == "preflight"
    assert shutdown_result(lifecycle)["status"] == "stopped"


def test_source_hashes_include_untracked_code_without_reading_samples_or_secrets(
    lifecycle: FixtureLifecycle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fixture_module, "REPO_ROOT", lifecycle.artifact_dir)
    source_paths = [
        "apps/api-python/app/modules/publications/infrastructure/html_syntax.py",
        "apps/api-python/app/modules/publications/infrastructure/html_serialization.py",
        "apps/web/features/audio/audio-playback-provider.tsx",
    ]
    excluded = [
        "apps/api-python/app/.env",
        "apps/api-python/app/credentials.json",
        "apps/api-python/app/samples/private.py",
        "artifacts/samples/book.json",
    ]
    for relative in source_paths + excluded:
        path = lifecycle.artifact_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode())
    with (
        patch.object(fixture_module.subprocess, "run") as git,
        patch.object(
            fixture_module, "sha256_file", wraps=fixture_module.sha256_file
        ) as hash_file,
    ):
        git.return_value.stdout = "\0".join(source_paths + excluded).encode()
        entries = fixture_module._application_source_hashes(lifecycle)
    assert [entry["path"] for entry in entries] == sorted(source_paths)
    assert all(len(entry["sha256"]) == 64 for entry in entries)
    assert {
        call.args[0].relative_to(lifecycle.artifact_dir).as_posix()
        for call in hash_file.call_args_list
    } == set(source_paths)
    command = git.call_args.args[0]
    assert command[:7] == [
        "git",
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
    ]
    assert command[7:] == [
        *fixture_module.APPLICATION_SOURCE_ROOTS,
        *fixture_module.APPLICATION_SOURCE_FILES,
    ]


def test_build_cancellation_is_observed_between_bounded_waits(
    lifecycle: FixtureLifecycle,
) -> None:
    def cancelled_wait(*, timeout: float) -> int:
        lifecycle.stop_file.write_text("stop\n")
        raise subprocess.TimeoutExpired("build", timeout)

    with (
        patch.object(fixture_module, "_pnpm_command", return_value=["pnpm"]),
        patch.object(fixture_module, "start_logged_process") as start,
    ):
        start.return_value.wait.side_effect = cancelled_wait
        with pytest.raises(FixtureStoppedError), _fixture_lifecycle(lifecycle):
            _build_production_web({}, lifecycle.artifact_dir / "build.log", lifecycle)
        start.return_value.wait.assert_called_once_with(timeout=0.25)
        start.return_value.stop.assert_called_once_with(timeout=12)
    assert shutdown_result(lifecycle)["status"] == "stopped"


@pytest.mark.parametrize("reason", ["stop-file", "startup-deadline"])
def test_cancelled_startup_does_not_launch_another_process(
    lifecycle: FixtureLifecycle,
    reason: str,
) -> None:
    if reason == "stop-file":
        lifecycle.stop_file.write_text("stop\n")
    else:
        lifecycle.startup_deadline = 0
    with (
        patch.object(fixture_module, "_pnpm_command", return_value=["pnpm"]),
        patch.object(fixture_module, "start_logged_process") as start,
        pytest.raises((FixtureStoppedError, TimeoutError)),
        _fixture_lifecycle(lifecycle),
    ):
        _build_production_web({}, lifecycle.artifact_dir / "build.log", lifecycle)
    start.assert_not_called()


def test_web_readiness_cancellation_does_not_make_a_network_request(
    lifecycle: FixtureLifecycle,
) -> None:
    lifecycle.stop_file.write_text("stop\n")
    with (
        patch.object(fixture_module.httpx, "get") as get,
        pytest.raises(FixtureStoppedError),
    ):
        _wait_for_web("http://127.0.0.1:3102", MagicMock(spec=LoggedProcess), lifecycle)
    get.assert_not_called()


@pytest.fixture
def next_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    originals = {
        # Deliberately nonstandard whitespace/EOL: restoration is byte-exact.
        "tsconfig.json": b'{\r\n "compilerOptions": {"strict": true, "tsBuildInfoFile": ".next/cache/user.tsbuildinfo"},\r\n "include": ["**/*.ts"], "exclude": ["node_modules"]\r\n}\r\n',
        "next-env.d.ts": b'/// <reference types="next" />\r\nimport "./.next/dev/types/routes.d.ts";\r\n// original user comment\r\n',
    }
    web_root = tmp_path / "web"
    web_root.mkdir()
    for name, content in originals.items():
        (web_root / name).write_bytes(content)
    monkeypatch.setattr(fixture_module, "WEB_ROOT", web_root)
    return originals


@pytest.mark.parametrize("runtime", ["development", "production"])
def test_next_configuration_changes_only_run_paths_and_restores_original_bytes(
    lifecycle: FixtureLifecycle,
    next_files: dict[str, bytes],
    runtime: str,
) -> None:
    with _fixture_lifecycle(lifecycle):
        _prepare_next_configuration(lifecycle, ".next-release-live-unit", runtime)
        config = json.loads((fixture_module.WEB_ROOT / "tsconfig.json").read_bytes())
        assert config["compilerOptions"] == {
            "strict": True,
            "tsBuildInfoFile": ".next-release-live-unit/cache/tsconfig.tsbuildinfo",
        }
        assert config["include"] == [
            "**/*.ts",
            ".next-release-live-unit/types/**/*.ts",
            ".next-release-live-unit/dev/types/**/*.ts",
        ]
        assert config["exclude"] == ["node_modules"]
        suffix = "/dev" if runtime == "development" else ""
        assert (
            f".next-release-live-unit{suffix}/types/routes.d.ts".encode()
            in (fixture_module.WEB_ROOT / "next-env.d.ts").read_bytes()
        )
    for name, original in next_files.items():
        assert (fixture_module.WEB_ROOT / name).read_bytes() == original
        assert (
            lifecycle.artifact_dir / "next-config-before" / name
        ).read_bytes() == original
    assert sorted(
        path.name for path in (lifecycle.artifact_dir / "next-config-before").iterdir()
    ) == sorted(next_files)


@pytest.mark.parametrize("name", ["tsconfig.json", "next-env.d.ts"])
def test_configuration_concurrent_edit_is_preserved_and_cleanup_fails_explicitly(
    lifecycle: FixtureLifecycle,
    next_files: dict[str, bytes],
    name: str,
) -> None:
    edited = next_files[name] + b"\n "
    with pytest.raises(ExceptionGroup) as failure, _fixture_lifecycle(lifecycle):
        _prepare_next_configuration(lifecycle, ".next-release-live-unit", "production")
        (fixture_module.WEB_ROOT / name).write_bytes(edited)
    assert any(
        isinstance(error, NextConfigurationConflict)
        for error in failure.value.exceptions
    )
    assert (fixture_module.WEB_ROOT / name).read_bytes() == edited
    assert not lifecycle.shutdown_file.exists()
    result = shutdown_result(lifecycle)
    assert result["status"] == "cleanup_failed"
    assert result["processesStopped"] is True
    assert name in str(result["cleanupErrors"])
    for other, original in next_files.items():
        if other != name:
            assert (fixture_module.WEB_ROOT / other).read_bytes() == original


def test_configuration_compare_prevents_overwriting_a_pre_install_edit(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tsconfig.json"
    path.write_bytes(b"concurrent editor")
    change = NextConfigurationFile(path, b"before", b"run")
    with pytest.raises(NextConfigurationConflict):
        change.install()
    assert path.read_bytes() == b"concurrent editor"
    assert change.changed is False


def test_configuration_compare_and_write_hold_an_exclusive_handle(
    tmp_path: Path,
) -> None:
    path = tmp_path / "next-env.d.ts"
    path.write_bytes(b"before")
    change = NextConfigurationFile(path, b"before", b"run")
    with _configuration_file(path), pytest.raises(OSError):
        change.install()
    assert path.read_bytes() == b"before"
    change.install()
    change.restore()
    assert path.read_bytes() == b"before"


def test_partial_configuration_install_restores_the_first_owned_file(
    lifecycle: FixtureLifecycle,
    next_files: dict[str, bytes],
) -> None:
    with (
        _configuration_file(fixture_module.WEB_ROOT / "next-env.d.ts"),
        pytest.raises(OSError),
        _fixture_lifecycle(lifecycle),
    ):
        _prepare_next_configuration(lifecycle, ".next-release-live-unit", "production")
    for name, original in next_files.items():
        assert (fixture_module.WEB_ROOT / name).read_bytes() == original
    assert shutdown_result(lifecycle)["status"] == "stopped"


@pytest.mark.parametrize("runtime", ["development", "production"])
def test_pinned_next_config_writers_leave_the_installed_run_bytes_unchanged(
    lifecycle: FixtureLifecycle,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runtime: str,
) -> None:
    web_root = fixture_module.REPO_ROOT / "apps/web"
    copied_root = tmp_path / "next-config-copy"
    copied_root.mkdir()
    originals = {
        name: (web_root / name).read_bytes()
        for name in ("tsconfig.json", "next-env.d.ts")
    }
    for name, original in originals.items():
        (copied_root / name).write_bytes(original)
    monkeypatch.setattr(fixture_module, "WEB_ROOT", copied_root)
    # Only Next's two small configuration writers run on copies. There is no
    # next CLI, compilation, server, dependency snapshot or browser here.
    script = r"""
const path = require('node:path');
const nextRoot = path.dirname(require.resolve('next/package.json'));
const ts = require('typescript');
const [baseDir, distName, runtime] = process.argv.slice(1);
process.env.NODE_ENV = runtime;
const distDir = runtime === 'development' ? `${distName}/dev` : distName;
const {writeConfigurationDefaults} = require(path.join(nextRoot, 'dist/lib/typescript/writeConfigurationDefaults.js'));
const {writeAppTypeDeclarations} = require(path.join(nextRoot, 'dist/lib/typescript/writeAppTypeDeclarations.js'));
(async () => {
  await writeConfigurationDefaults(ts.version, path.join(baseDir, 'tsconfig.json'), false, true, distDir, false, false);
  await writeAppTypeDeclarations({baseDir, distDir, imageImportsEnabled: true, hasAppDir: true, hasPagesDir: false, strictRouteTypes: false});
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    with _fixture_lifecycle(lifecycle):
        _prepare_next_configuration(lifecycle, ".next-release-live-unit", runtime)
        completed = subprocess.run(
            [
                "node",
                "-e",
                script,
                str(copied_root),
                ".next-release-live-unit",
                runtime,
            ],
            cwd=web_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        for change in lifecycle.configuration:
            assert change.path.read_bytes() == change.installed
    for name, original in originals.items():
        assert (copied_root / name).read_bytes() == original


def test_browser_fixture_lifecycle_with_fake_process_fs_and_clock() -> None:
    # Transpile only the checked-in functions/test callback, never load the
    # Playwright runner. All process, page, filesystem and clock effects below
    # are fakes; assertion failures and cleanup evidence use the real code.
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const source = fs.readFileSync('e2e/release-live.spec.ts', 'utf8');
const ast = ts.createSourceFile('release-live.spec.ts', source, ts.ScriptTarget.Latest, true);
const names = new Set(['record', 'redact', 'readJson', 'safeFixtureError', 'combineFixtureErrors', 'stopFixture', 'startFixture']);
const functionSource = ast.statements.filter(node => ts.isFunctionDeclaration(node) && names.has(node.name?.text)).map(node => node.getText(ast)).join('\n');
const compile = text => ts.transpileModule(text, {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
const files = new Map();
let clock = 0, artifactDir, mode = 'preflight', spawnArguments, observedTimeout;
const password = 'SYNTHETIC_REVIEW_PASSWORD';
const env = {RELEASE_LIVE_PASSWORD:password, RELEASE_LIVE_E2E:'1', RELEASE_LIVE_WEB_RUNTIME:'production', PLAYWRIGHT_BASE_URL:'http://release-live.localhost:3102', RELEASE_LIVE_API_PORT:'18081', RELEASE_LIVE_PYTHON:'synthetic-python'};
const sandbox = vm.createContext({
  Error, AggregateError, URL, process:{env}, Date:{now:()=>clock},
  REPO_ROOT:path.resolve('../..'), DEFAULT_ARTIFACT_ROOT:'synthetic-evidence',
  RESERVED_PORTS:new Set([3000,3100,8000]), productionWeb:true,
  FIXTURE_STARTUP_TIMEOUT_MS:1200000, FIXTURE_STOP_TIMEOUT_MS:120000,
  resolve:path.resolve, audioSoakSeconds:()=>30, parseManifest:value=>value,
  existsSync:file=>file==='synthetic-python'||files.has(file),
  mkdir:async dir=>{artifactDir=dir;},
  readFile:async file=>{if(!files.has(file))throw new Error('missing synthetic file');return files.get(file);},
  writeFile:async(file,text)=>{files.set(file,text);},
  delay:async millis=>{clock+=millis;},
  spawn:(_python,args)=>{
    spawnArguments=args;
    files.set(path.resolve(artifactDir,'fixture.log'),`Chapter engine is unavailable ${password}`);
    if(mode!=='missing-result'&&mode!=='spawn-error') {
      files.set(path.resolve(artifactDir,'shutdown-result.json'),JSON.stringify({status:mode==='cleanup-failure'?'cleanup_failed':'stopped',processesStopped:true,primaryError:'Chapter engine is unavailable',cleanupErrors:mode==='cleanup-failure'?['next-config concurrent edit']:[]}));
      if(mode!=='cleanup-failure')files.set(path.resolve(artifactDir,'shutdown-complete'),'stopped\n');
    }
    return {exitCode:mode==='spawn-error'?null:1,signalCode:null,pid:mode==='spawn-error'?undefined:123,
      once:(event,listener)=>{if(mode==='spawn-error'&&event==='error')listener(new Error('synthetic spawn error'));}};
  },
  test:{setTimeout:timeout=>{observedTimeout=timeout;}}
});
vm.runInContext(compile(functionSource),sandbox);
async function startupFailure(nextMode){
  files.clear();clock=0;mode=nextMode;
  let failure;
  try{await sandbox.startFixture({workerIndex:0});}catch(error){failure=error;}
  assert.ok(failure);
  const evidence=JSON.parse(files.get(path.resolve(artifactDir,'startup-failure.json')));
  assert.ok(!JSON.stringify(evidence).includes(password));
  assert.ok(!failure.stack?.includes(password));
  assert.ok(!failure.message.includes(password));
  assert.equal(clock,0,'already-exited or never-spawned children must not wait out stop timeout');
  return {failure,evidence};
}
(async()=>{
  const first=await startupFailure('preflight');
  assert.match(first.failure.message,/Chapter engine is unavailable/);
  assert.equal(first.evidence.cleanupFailure,null);
  assert.equal(spawnArguments[spawnArguments.indexOf('--lifetime-seconds')+1],'630');
  assert.equal(spawnArguments[spawnArguments.indexOf('--startup-timeout-seconds')+1],'1200');
  const both=await startupFailure('cleanup-failure');
  assert.ok(both.failure instanceof AggregateError);
  assert.equal(both.failure.errors.length,2);
  assert.match(both.failure.message,/Chapter engine is unavailable/);
  assert.match(both.evidence.cleanupFailure,/next-config concurrent edit/);
  const missing=await startupFailure('missing-result');
  assert.match(missing.failure.message,/Chapter engine is unavailable/);
  assert.match(missing.evidence.cleanupFailure,/without a shutdown result/);
  const spawn=await startupFailure('spawn-error');
  assert.match(spawn.failure.message,/synthetic spawn error/);
  const pending={artifactDir:'synthetic-pending',stopFile:'synthetic-stop',shutdownFile:'synthetic-shutdown',spawnError:null,child:{exitCode:null,signalCode:null,pid:123}};
  clock=0;
  await assert.rejects(sandbox.stopFixture(pending),/still running/);
  assert.equal(clock,120000);

  const declaration=ast.statements.find(node=>ts.isExpressionStatement(node)&&ts.isCallExpression(node.expression)&&node.expression.expression.getText(ast)==='test');
  assert.ok(declaration);
  const callback=declaration.expression.arguments[1];
  sandbox.startFixture=async()=>({artifactDir:'synthetic-final',manifest:{ffprobeAvailable:false,webOrigin:env.PLAYWRIGHT_BASE_URL,apiOrigin:'http://127.0.0.1:18081'}});
  sandbox.stopFixture=async()=>{throw new Error('cleanup sentinel');};
  const run=vm.runInContext(compile(`const callback = ${callback.getText(ast)}; callback;`),sandbox);
  await assert.rejects(run({page:{on:()=>{}},context:{}},{project:{name:'chrome'}}),error=>{
    assert.ok(error instanceof AggregateError);
    assert.match(error.message,/configured ffprobe/);
    assert.match(error.message,/cleanup sentinel/);
    return true;
  });
  const final=JSON.parse(files.get(path.resolve('synthetic-final','browser-observations.json')));
  assert.equal(final.result,'FAILED');
  assert.match(final.failure,/configured ffprobe/);
  assert.equal(final.cleanupFailure,'cleanup sentinel');
  assert.equal(observedTimeout,1200000+300000+30000+120000);

  const configSource=fs.readFileSync('playwright.release-live.config.ts','utf8');
  const configAst=ts.createSourceFile('config.ts',configSource,ts.ScriptTarget.Latest,true);
  const body=configAst.statements.filter(node=>!ts.isImportDeclaration(node)).map(node=>node.getText(configAst)).join('\n');
  const exported={};
  vm.runInNewContext(compile(body),{process:{env},exports:exported,defineConfig:value=>value,devices:{'Desktop Chrome':{},'Pixel 7':{}}});
  assert.equal(exported.default.workers,1);
  assert.equal(exported.default.use.trace,'off');
  assert.equal(exported.default.use.serviceWorkers,'allow');
  console.log('PASS: startup original/cleanup errors, early exit/spawn failure, bounded stop, final evidence, soak budget, workers and trace defaults');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=fixture_module.REPO_ROOT / "apps/web",
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
