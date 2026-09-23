import assert from 'node:assert/strict';
import test from 'node:test';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { requestDigest, selectTasks, validateRequest, validateSource, validateMode, selectAndroidBuild, workflowAndroidSelection, validateRequestVersions } from './release-request.mjs';

const image = `gamersgu/shuku-starship-web@sha256:${'a'.repeat(64)}`;
export function sample(target = 'server-update') {
  return {
    schemaVersion: 1, id: 'local-test-only', sourceCommit: 'a'.repeat(40), channel: 'stable',
    targets: [target], versions: { [target === 'server-update' ? 'server' : target]: '1.2.3' }, promoteLatest: false,
    notes: { 'zh-CN': '修复更新准备完成后提示状态不准确的问题，下载准备完成后会明确显示尚未安装，管理员仍可以检查内容并决定何时执行更新。', 'en-US': 'Fix the update preparation status so administrators can distinguish a downloaded package from an installed update before continuing.' },
    ...(target === 'server-update' ? { server: { mode: 'code-only', baseVersion: '1.2.2', runtimeImage: image } } : {}),
    ...(['android', 'ios'].includes(target) ? { [target]: { destination: target === 'android' ? 'github-apk' : 'testflight', buildNumber: 7 } } : {}),
    ...(target === 'fnos' ? { fnos: { image } } : {}),
    ...(target === 'docker' ? { docker: { runtimeImage: image, application: { version: '1.2.3', sourceCommit: 'a'.repeat(40), ociDigests: [`sha256:${'b'.repeat(64)}`, `sha256:${'c'.repeat(64)}`] } } } : {}),
  };
}

test('every single target selects exactly one task without implicit publications', () => {
  for (const target of ['server-update', 'android', 'ios', 'docker', 'fnos']) {
    const request = sample(target);
    assert.equal(validateRequest(request), request);
    assert.deepEqual(selectTasks(request).map(item => item.target), [target]);
    assert.deepEqual(selectTasks(request)[0].needs, []);
    assert.deepEqual(selectTasks(request, { [target]: true }), []);
  }
});

test('independent versions and explicit artifact dependencies', () => {
  const request = sample();
  request.targets.push('android', 'docker', 'fnos');
  Object.assign(request.versions, { android: '2.1.0', docker: '1.2.3', fnos: '3.0.0' });
  request.android = sample('android').android;
  request.docker = { fromServerUpdate: true, runtimeImage: image };
  request.fnos = { fromDocker: true };
  const tasks = selectTasks(request);
  assert.deepEqual(tasks.map(task => task.needs), [[], [], ['server-update'], ['docker']]);
  assert.equal(tasks[1].tag, 'android-v2.1.0');
  assert.deepEqual(selectTasks(request, { 'server-update': true, android: true }).map(task => task.target), ['docker', 'fnos']);
});

test('reject unknown fields, credentials, targets, placeholders and invalid references', () => {
  const mutations = [
    r => r.targets.push('all'), r => r.targets.push('server-update'), r => r.targets = [],
    r => r.command = 'echo bad', r => r.server.token = 'secret', r => r.server.runtimeImage = 'gamersgu/shuku-starship-web:latest',
    r => r.server.runtimeImage = `evil.example/image@sha256:${'a'.repeat(64)}`,
    r => r.sourceCommit = 'main', r => r.versions.android = '2.0.0', r => r.server.mode = 'anything',
    r => r.notes['en-US'] = 'TODO '.repeat(20), r => r.android = sample('android').android,
    r => r.server.mode = 'runtime', r => r.promoteLatest = 'true', r => r.channel = 'beta',
  ];
  for (const mutate of mutations) { const request = sample(); mutate(request); assert.throws(() => validateRequest(request)); }
  assert.throws(() => validateRequest(sample(), 'different.json'), /filename/);
  const f = sample('fnos'); f.fnos = { fromDocker: true }; assert.throws(() => validateRequest(f), /explicit docker/);
  const d = sample('docker'); d.docker.application.sourceCommit = 'b'.repeat(40); assert.throws(() => validateRequest(d), /original application/);
});

test('beta identity is fixed by request, never by workflow run number', () => {
  const r = sample('android'); r.channel = 'beta';
  assert.equal(selectTasks(r)[0].tag, 'android-v1.2.3-beta.7');
  r.android.destination = 'arbitrary-upload-url'; assert.throws(() => validateRequest(r), /destination/);
});

test('canonical request digest ignores key ordering but detects content changes', () => {
  const r = sample(); const reversed = Object.fromEntries(Object.entries(r).reverse());
  assert.equal(requestDigest(r), requestDigest(reversed));
  reversed.promoteLatest = true; assert.notEqual(requestDigest(r), requestDigest(reversed));
});

function repository(t) {
  const root = mkdtempSync(join(tmpdir(), 'release-request-test-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const git = (...args) => execFileSync('git', args, { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
  git('init', '-b', 'main'); git('config', 'user.name', 'Test'); git('config', 'user.email', 'test@example.invalid');
  const put = (path, text) => { mkdirSync(join(root, path, '..'), { recursive: true }); writeFileSync(join(root, path), text); };
  const commit = () => { git('add', '.'); git('commit', '-m', 'fixture'); return git('rev-parse', 'HEAD'); };
  put('README.md', 'test\n'); commit();
  return { root, git, put, commit };
}

test('accepted source is an ancestor, request is admitted separately and immutable across history', t => {
  const { root, put, commit, git } = repository(t);
  const r = sample('android'); r.sourceCommit = git('rev-parse', 'HEAD');
  const requestPath = `release/requests/${r.id}.json`;
  put(requestPath, JSON.stringify(r)); commit();
  const options = { root, authorizedRef: 'main', accepted: true, requestPath };
  assert.doesNotThrow(() => validateSource(r, options));
  const changed = structuredClone(r); changed.promoteLatest = true;
  assert.throws(() => validateSource(changed, options), /differs/);
  put(requestPath, JSON.stringify(changed)); commit();
  assert.throws(() => validateSource(changed, options), /immutable/);
  git('checkout', '-b', 'unaccepted'); put('other', 'new'); const other = commit();
  assert.throws(() => validateSource({ ...r, sourceCommit: other }, { root, authorizedRef: 'main' }));
});

test('mode validates real Git inputs and ignores only application version in dependency identity', t => {
  const { root, put, commit, git } = repository(t);
  put('package.json', JSON.stringify({ version: '1.2.2', dependencies: { x: '1.0' } }));
  put('apps/web/package.json', JSON.stringify({ version: '1.2.2' }));
  put('apps/api-python/pyproject.toml', '[project]\nversion = "1.2.2"\ndependencies = []\n');
  put('apps/api-python/uv.lock', '[[package]]\nname = "ermao-books-api-python"\nversion = "1.2.2"\n');
  put('pnpm-lock.yaml', 'lockfileVersion: 9\n');
  commit(); git('tag', 'v1.2.2');
  put('package.json', JSON.stringify({ version: '1.2.3', dependencies: { x: '1.0' } }));
  put('apps/api-python/uv.lock', '[[package]]\nname = "ermao-books-api-python"\nversion = "1.2.3"\n');
  const r = sample(); r.sourceCommit = commit();
  assert.doesNotThrow(() => validateMode(r, { root }));
  put('package.json', JSON.stringify({ version: '1.2.3', dependencies: { x: '2.0' } })); r.sourceCommit = commit();
  assert.throws(() => validateMode(r, { root }), /dependency/);
  r.server.mode = 'application'; assert.doesNotThrow(() => validateMode(r, { root }));
  put('scripts/container-entry.py', 'changed runtime'); r.sourceCommit = commit();
  assert.throws(() => validateMode(r, { root }), /Fixed runtime/);
});


test('Android defaults off; only strict explicit inputs or request targets select it', () => {
  for (const eventName of ['push', 'pull_request', 'workflow_dispatch', 'workflow_call']) {
    for (const input of [undefined, '', false, 'false']) assert.equal(selectAndroidBuild({ eventName, input }), false);
  }
  for (const input of [true, 'true']) {
    for (const eventName of ['workflow_dispatch', 'workflow_call']) assert.equal(selectAndroidBuild({ eventName, input }), true);
    for (const eventName of ['push', 'pull_request', 'pull_request_target']) assert.throws(() => selectAndroidBuild({ eventName, input }));
  }
  for (const input of ['TRUE', '1', 1, null, [], {}]) assert.throws(() => selectAndroidBuild({ input }), /boolean/);
  assert.equal(selectAndroidBuild({ request: sample('android'), eventName: 'push' }), true);
  assert.equal(selectAndroidBuild({ request: sample(), eventName: 'push' }), false);
  for (const input of [true, false, 'false']) assert.throws(() => selectAndroidBuild({ request: sample('android'), input }), /conflict/);
  assert.throws(() => selectAndroidBuild({ request: sample('android'), mode: 'code-only' }), /code-only/);
  assert.throws(() => selectAndroidBuild({ request: sample('android'), eventName: 'pull_request' }), /PRs/);
});

test('legacy tag and branch entries do not inherit an Android selection', async t => {
  const { root, put, commit } = repository(t);
  put('package.json', JSON.stringify({ version: '1.3.1' })); commit();
  for (const GITHUB_EVENT_NAME of ['push', 'pull_request', 'workflow_dispatch']) {
    const result = await workflowAndroidSelection({ root, env: { GITHUB_EVENT_NAME, GITHUB_REF_TYPE: 'tag', RELEASE_MODE: 'full' } });
    assert.equal(result.buildAndroid, false);
  }
  await assert.rejects(workflowAndroidSelection({ root, env: { GITHUB_EVENT_NAME: 'workflow_dispatch', GITHUB_REF_TYPE: 'branch', BUILD_ANDROID_INPUT: 'true' } }), /version tag/);
});


test('tag selection validates admitted request identity, source contents, version and native build number', async t => {
  const { root, put, commit, git } = repository(t);
  const files = ['package.json', 'apps/web/package.json', 'packages/reader-core/package.json',
    'packages/reader-contracts/package.json', 'apps/readium-web-poc/package.json',
    'apps/api-python/pyproject.toml', 'apps/api-python/uv.lock', 'apps/api-python/app/core/config.py',
    'apps/web/public/sw.js', 'apps/mobile/androidApp/build.gradle.kts',
    'apps/mobile/iosApp/ErmaoLibrary.xcodeproj/project.pbxproj'];
  for (const file of files) put(file, readFileSync(file));
  const request = sample('android');
  const version = JSON.parse(readFileSync('package.json')).version;
  const androidBuild = readFileSync('apps/mobile/androidApp/build.gradle.kts', 'utf8');
  put(
    'apps/mobile/androidApp/build.gradle.kts',
    androidBuild.replace(/versionName = "[^"]+"/, `versionName = "${version}"`)
  );
  request.versions.android = version;
  request.android.buildNumber = Number(androidBuild.match(/versionCode = (\d+)/)[1]);
  request.id = `stable-${version.replaceAll('.', '-')}`;
  request.sourceCommit = commit();
  await assert.rejects(validateRequestVersions({ ...request, android: { ...request.android, buildNumber: request.android.buildNumber + 1 } }, { root }), /buildNumber differs/);
  await assert.rejects(validateRequestVersions({ ...request, versions: { android: '9.9.9' } }, { root }), /version differs/);
  const path = `release/requests/${request.id}.json`;
  put(path, JSON.stringify(request)); commit();
  git('update-ref', 'refs/remotes/origin/main', 'HEAD');
  const env = { GITHUB_EVENT_NAME: 'push', GITHUB_REF_TYPE: 'tag', RELEASE_MODE: 'full' };
  assert.equal((await workflowAndroidSelection({ root, env })).buildAndroid, true);
  await assert.rejects(workflowAndroidSelection({ root, env: { ...env, GITHUB_EVENT_NAME: 'workflow_dispatch', BUILD_ANDROID_INPUT: 'false' } }), /conflict/);
  put('apps/api-python/app/core/config.py', 'changed after frozen source'); commit();
  await assert.rejects(workflowAndroidSelection({ root, env }), /source differs/);
  git('reset', '--hard', 'HEAD^');
  request.android.buildNumber += 1;
  put(path, JSON.stringify(request)); commit(); git('update-ref', 'refs/remotes/origin/main', 'HEAD');
  await assert.rejects(workflowAndroidSelection({ root, env }), /immutable/);
});
