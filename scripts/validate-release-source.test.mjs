import assert from 'node:assert/strict';
import test from 'node:test';
import { isFormalRelease, validateReleaseSource } from './validate-release-source.mjs';

const sha = 'a'.repeat(40);
const source = {
  sha, mainSha: sha, developSha: sha, tag: 'v1.0.5', version: '1.0.5', release: null,
  environment: { protection_rules: [{ type: 'required_reviewers', reviewers: [{ type: 'User', reviewer: { id: 1 } }] }] },
};

test('main dispatch cannot start a duplicate candidate build', () => {
  assert.throws(() => isFormalRelease({ eventName: 'workflow_dispatch', refType: 'branch', refName: 'main' }), /build once/);
  assert.throws(() => isFormalRelease({ eventName: 'workflow_dispatch', refType: 'branch', refName: 'feature' }), /build once/);
  for (const eventName of ['push', 'workflow_dispatch']) {
    assert.equal(isFormalRelease({ eventName, refType: 'tag', refName: 'v1.0.4' }), true);
    for (const refName of ['develop', 'prod']) assert.equal(isFormalRelease({ eventName, refType: 'branch', refName }), false);
  }
  assert.equal(isFormalRelease({ eventName: 'pull_request', refType: 'branch', refName: '1/merge' }), false);
  assert.throws(() => isFormalRelease({ eventName: 'push', refType: 'tag', refName: 'android-beta' }), /build once/);
});

test('a release must start from the same commit on both branches and match the version', () => {
  validateReleaseSource(source);
  for (const field of ['mainSha', 'developSha', 'sha']) {
    assert.throws(() => validateReleaseSource({ ...source, [field]: 'b'.repeat(40) }), /same release commit/);
  }
  assert.throws(() => validateReleaseSource({ ...source, tag: 'v1.0.6' }), /version/);
});

test('an already published version cannot rebuild, while a draft can recover', () => {
  validateReleaseSource({ ...source, release: { draft: true } });
  assert.throws(() => validateReleaseSource({ ...source, release: { draft: false } }), /already published/);
});

test('explicitly authorized releases do not require a GitHub reviewer environment', () => {
  for (const mode of ['full', 'code-only']) {
    for (const environment of [null, {}, { protection_rules: [] }]) {
      assert.doesNotThrow(() => validateReleaseSource({ ...source, mode, environment }));
    }
  }
});
