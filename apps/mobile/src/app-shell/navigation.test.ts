import assert from 'node:assert/strict';
import test from 'node:test';

import {
  shellRouteDefinitions,
  shellRouteForPath,
  shouldUseExpandedNavigation,
} from './navigation';

test('shell routes keep stable destinations and semantic icons', () => {
  assert.deepEqual(shellRouteDefinitions.home, {
    hintKey: 'route.home.hint',
    iconName: 'home',
    labelKey: 'route.home.label',
    path: '/home',
  });
  assert.deepEqual(shellRouteDefinitions.library, {
    hintKey: 'route.library.hint',
    iconName: 'library',
    labelKey: 'route.library.label',
    path: '/library',
  });
  assert.deepEqual(shellRouteDefinitions.me, {
    hintKey: 'route.me.hint',
    iconName: 'person',
    labelKey: 'route.me.label',
    path: '/me',
  });
});

test('descendants keep their top-level destination and unknown paths fall back home', () => {
  assert.equal(shellRouteForPath('/home'), 'home');
  assert.equal(shellRouteForPath('/library'), 'library');
  assert.equal(shellRouteForPath('/library/books'), 'library');
  assert.equal(shellRouteForPath('/me'), 'me');
  assert.equal(shellRouteForPath('/reader'), 'library');
  assert.equal(shellRouteForPath('/unknown'), 'home');
});

test('expanded navigation responds to both available width and text scale', () => {
  assert.equal(
    shouldUseExpandedNavigation({
      availableWidth: 768,
      expandedMinimumWidth: 768,
      fontScale: 1,
    }),
    true,
  );
  assert.equal(
    shouldUseExpandedNavigation({
      availableWidth: 767,
      expandedMinimumWidth: 768,
      fontScale: 1,
    }),
    false,
  );
  assert.equal(
    shouldUseExpandedNavigation({
      availableWidth: 1_000,
      expandedMinimumWidth: 768,
      fontScale: 1.4,
    }),
    false,
  );
});
