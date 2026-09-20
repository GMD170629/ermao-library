import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { serverUpdate, releaseMode, validateQuickSource, validatePublishedBase } from './release-mode.mjs';
import { validateMode } from './release-request.mjs';

const runtimeImage = `gamersgu/shuku-starship-web@sha256:${'a'.repeat(64)}`;
const update = { mode: 'code-only', baseVersion: '1.2.0', runtimeImage };
function repository(t) {
  const root = mkdtempSync(join(tmpdir(), 'quick-release-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const git = (...args) => execFileSync('git', args, { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
  const put = (name, content) => { mkdirSync(join(root, name, '..'), { recursive: true }); writeFileSync(join(root, name), typeof content === 'string' ? content : JSON.stringify(content)); };
  const commit = () => { git('add', '.'); git('commit', '-m', 'fixture'); return git('rev-parse', 'HEAD'); };
  git('init', '-b', 'main'); git('config', 'user.email', 'fixture@example.invalid'); git('config', 'user.name', 'Fixture');
  put('package.json', { version: '1.2.0' });
  put('release-notes/index.json', { releases: [{ version: '1.2.0' }] });
  put('apps/mobile/androidApp/build.gradle.kts', 'versionCode = 10\nversionName = "1.2.0"\n');
  commit(); git('tag', 'v1.2.0');
  return { root, git, put, commit };
}

test('mode defaults to full; invalid or implicit quick metadata cannot select a branch', t => {
  const { root, put } = repository(t);
  assert.equal(releaseMode({ root }).mode, 'full');
  assert.equal(serverUpdate({ version: '1.2.1' }), null);
  for (const invalid of [null, {}, { ...update, mode: 'application' }, { ...update, runtimeImage: 'latest' }, { ...update, baseVersion: '1.2.1' }, { ...update, extra: true }]) {
    assert.throws(() => serverUpdate({ version: '1.2.1', serverUpdate: invalid }));
  }
  put('package.json', { version: '1.2.1' });
  put('release-notes/index.json', { releases: [{ version: '1.2.1', serverUpdate: update }] });
  assert.deepEqual(releaseMode({ root }), { version: '1.2.1', ...update });
});

test('published baseline and immutable ancestry are mandatory; continuous quick releases inherit runtime', t => {
  const { root, put, commit, git } = repository(t);
  put('package.json', { version: '1.2.1' });
  put('release-notes/index.json', { releases: [{ version: '1.2.1', serverUpdate: update }] });
  commit();
  assert.equal(validateQuickSource(update, { root }), '1.2.0');
  git('tag', 'v1.2.1');
  const next = { ...update, baseVersion: '1.2.1' };
  put('package.json', { version: '1.2.2' });
  put('release-notes/index.json', { releases: [{ version: '1.2.2', serverUpdate: next }] });
  commit();
  assert.equal(validateQuickSource(next, { root }), '1.2.0');
  assert.throws(() => validateQuickSource({ ...next, runtimeImage: runtimeImage.replaceAll('a', 'b') }, { root }), /inherit/);
  for (const release of [{}, { tagName: 'v1.2.0', isDraft: true, isPrerelease: false }, { tagName: 'v1.2.0', isDraft: false, isPrerelease: true }]) assert.throws(() => validatePublishedBase(update, release));
  validatePublishedBase(update, { tagName: 'v1.2.0', isDraft: false, isPrerelease: false });
});

test('eligibility rejects unshipped inputs, patches, native clients and migration changes', t => {
  const { root, put, commit, git } = repository(t);
  put('apps/web/features/example.ts', 'export const fixed = true;');
  put('apps/mobile/androidApp/build.gradle.kts', 'versionCode = 11\nversionName = "1.2.1"\n');
  let sourceCommit = commit();
  assert.doesNotThrow(() => validateMode({ server: update, sourceCommit }, { root }));
  for (const file of ['patches/x.patch', 'pnpm-workspace.yaml', '.npmrc', 'apps/web/next.config.js', 'packages/reader-core/package.json', 'apps/mobile/shared/src/Main.kt', 'apps/api-python/app/db/migrations/versions/new.py', 'apps/api-python/app/contracts/http.py', 'scripts/container_image.py']) {
    put(file, file.endsWith('.json') ? '{}' : 'changed'); sourceCommit = commit();
    assert.throws(() => validateMode({ server: update, sourceCommit }, { root }), undefined, file);
    git('reset', '--hard', 'HEAD^');
  }
});

test('a quick release commit suppresses builds, but subsequent ordinary development does not', t => {
  const { root, put, commit, git } = repository(t);
  put('package.json', { version: '1.2.1' });
  put('release-notes/index.json', { releases: [{ version: '1.2.1', serverUpdate: update }] });
  commit(); git('tag', 'v1.2.1');
  const run = () => JSON.parse(execFileSync(process.execPath, [new URL('./release-mode.mjs', import.meta.url).pathname], {
    cwd: root, encoding: 'utf8', env: { ...process.env, GITHUB_REF_TYPE: 'branch', GITHUB_EVENT_NAME: 'push', GITHUB_OUTPUT: '' }
  }));
  assert.equal(run().mode, 'code-only');
  put('apps/web/features/fix.ts', 'export const fixed = true;'); commit();
  assert.equal(run().mode, 'full');
});

test('Wiki gitlink changes are unrelated to application eligibility', t => {
  const { root, git, commit } = repository(t);
  git('update-index', '--add', '--cacheinfo', `160000,${git('rev-parse', 'HEAD')},ermao-library.wiki`);
  git('commit', '-m', 'unrelated wiki pointer');
  assert.doesNotThrow(() => validateMode({ server: update, sourceCommit: 'HEAD' }, { root }));
});
