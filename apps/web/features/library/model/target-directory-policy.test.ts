import assert from 'node:assert/strict';
import test from 'node:test';
import {
  enabledLibraryRootPaths,
  isAllowedTargetPath,
  isDirectoryInside
} from '../../../components/directory/target-directory-policy';

test('allows a monitored root and any nested directory', () => {
  assert.equal(isDirectoryInside('/library/inbox', '/library/inbox'), true);
  assert.equal(isDirectoryInside('/library/inbox', '/library/inbox/fiction/fantasy'), true);
});

test('does not confuse a sibling with a monitored descendant', () => {
  assert.equal(isDirectoryInside('/library/inbox', '/library/inbox-other'), false);
  assert.equal(isDirectoryInside('/library/inbox', '/library'), false);
});

test('only enabled libraries become upload roots', () => {
  const roots = enabledLibraryRootPaths([
    { rootPath: '/library/enabled/', enabled: true },
    { rootPath: '/library/disabled', enabled: false }
  ]);

  assert.deepEqual(roots, ['/library/enabled']);
  assert.equal(isAllowedTargetPath('/library/enabled/nested', roots), true);
  assert.equal(isAllowedTargetPath('/library/disabled', roots), false);
});
