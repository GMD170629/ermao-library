import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { publicationContext, publish, shouldPublish } from './publish-android-beta.mjs';

const env = { GITHUB_REF: 'refs/heads/develop', GITHUB_EVENT_NAME: 'push', GITHUB_RUN_NUMBER: '42',
  GITHUB_RUN_ATTEMPT: '2', GITHUB_SHA: 'a'.repeat(40), GITHUB_REPOSITORY: 'owner/repo', GITHUB_RUN_ID: '123' };
const context = publicationContext(env);
const previous = { id: 1, prerelease: true, body: '<!-- android-beta run=41 attempt=1 -->' };

test('only develop push and manual runs can publish', () => {
  for (const GITHUB_EVENT_NAME of ['pull_request', 'pull_request_target', 'workflow_run']) {
    assert.throws(() => publicationContext({ ...env, GITHUB_EVENT_NAME }));
  }
  assert.throws(() => publicationContext({ ...env, GITHUB_REF: 'refs/heads/prod' }));
  assert.throws(() => publicationContext({ ...env, GITHUB_RUN_NUMBER: '2147483647' }));
  assert.equal(publicationContext({ ...env, GITHUB_EVENT_NAME: 'workflow_dispatch' }).number, 42);
});

test('older runs and attempts cannot replace published builds', () => {
  assert.equal(shouldPublish(previous, context), true);
  assert.equal(shouldPublish({ ...previous, body: '<!-- android-beta run=43 attempt=1 -->' }, context), false);
  assert.equal(shouldPublish({ ...previous, body: '<!-- android-beta run=42 attempt=2 -->' }, context), false);
  assert.equal(shouldPublish({ ...previous, body: '<!-- android-beta run=42 attempt=1 -->' }, context), true);
  assert.throws(() => shouldPublish({ ...previous, prerelease: false }, context));
  assert.throws(() => shouldPublish({ ...previous, immutable: true }, context));
  assert.throws(() => shouldPublish({ ...previous, body: '' }, context));
});

function fixture(t, overrides = {}) {
  const directory = mkdtempSync(join(tmpdir(), 'android-beta-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const name = 'ermao-library-1.0.0-beta.42-aaaaaaaa-r2.apk';
  writeFileSync(join(directory, name), 'apk-fixture');
  const digest = createHash('sha256').update('apk-fixture').digest('hex');
  writeFileSync(join(directory, `${name}.sha256`), `${digest}  ${name}\n`);
  const calls = [];
  const api = {
    release: () => previous, head: () => context.sha,
    createDraft: () => { calls.push('draft'); return { id: 1 }; },
    upload: () => calls.push('upload'), moveTag: () => calls.push('tag'),
    update: () => calls.push('update'),
    assets: () => [{ id: 2, name: 'ermao-library-old.apk' }, { id: 3, name }, { id: 4, name: 'unrelated.txt' }],
    remove: id => calls.push(`remove:${id}`), ...overrides,
  };
  return { directory, name, api, calls };
}

test('upload both verified assets before changing published metadata and cleaning old assets', t => {
  const { directory, api, calls } = fixture(t);
  assert.equal(publish(context, directory, api), 'published');
  assert.deepEqual(calls, ['upload', 'upload', 'tag', 'update', 'remove:2']);
});

test('first publication creates a draft before uploading', t => {
  const { directory, api, calls } = fixture(t, { release: () => null });
  publish(context, directory, api);
  assert.equal(calls[0], 'draft');
  assert.equal(calls.at(-2), 'update');
});

test('failed upload cannot change the published tag/body or delete old assets', t => {
  let uploads = 0;
  const { directory, api, calls } = fixture(t, { upload: () => { if (++uploads === 2) throw Error('upload failed'); } });
  assert.throws(() => publish(context, directory, api), /upload failed/);
  assert.deepEqual(calls, []);
});

test('stale commit and corrupt APK cannot mutate releases', t => {
  const { directory, name, api, calls } = fixture(t, { head: () => 'b'.repeat(40) });
  assert.equal(publish(context, directory, api), 'superseded');
  writeFileSync(join(directory, name), 'corrupt');
  assert.throws(() => publish(context, directory, api), /SHA-256/);
  assert.deepEqual(calls, []);
});

test('CI gates signing/publication behind all existing mobile checks', () => {
  const workflow = readFileSync(new URL('../.github/workflows/mobile.yml', import.meta.url), 'utf8');
  const job = workflow.split('\n  publish-android-beta:')[1].split('\n  android-emulator:')[0];
  assert.match(job, /needs: \[backend-contract, android, android-emulator\]/);
  assert.match(job, /github.ref == 'refs\/heads\/develop'/);
  assert.match(job, /contents: write/);
  assert.match(job, /cancel-in-progress: false/);
  assert.equal((workflow.match(/contents: write/g) ?? []).length, 1);
  assert.match(workflow, /:androidApp:lintBeta/);
  const signer = readFileSync(new URL('./sign-android-beta.sh', import.meta.url), 'utf8');
  assert.match(signer, /Required beta signing input is missing/);
  assert.doesNotMatch(signer, /genkey|debug.keystore|set -x/);
});
