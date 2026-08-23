import assert from 'node:assert/strict';
import test from 'node:test';
import { COLLAPSED_STRUCTURE_RESOURCE_LIMIT, structureResourceList, structureResourceShowsAssetDetails } from './structure-resource-list';

const resources = Array.from({ length: 12 }, (_, index) => `resource-${index + 1}`);

test('content structure shows at most ten resources by default', () => {
  const result = structureResourceList(resources.slice(0, 10), false, 12);

  assert.equal(COLLAPSED_STRUCTURE_RESOURCE_LIMIT, 10);
  assert.deepEqual(result.visibleResources, resources.slice(0, 10));
  assert.equal(result.canToggle, true);
});

test('content structure shows every resource after expansion', () => {
  const result = structureResourceList(resources, true);

  assert.deepEqual(result.visibleResources, resources);
  assert.equal(result.canToggle, true);
});

test('content structure does not offer a toggle for ten or fewer resources', () => {
  const result = structureResourceList(resources.slice(0, 10), false);

  assert.deepEqual(result.visibleResources, resources.slice(0, 10));
  assert.equal(result.canToggle, false);
});

test('content structure hides source file details for audiobook resources', () => {
  assert.equal(structureResourceShowsAssetDetails('AUDIOBOOK'), false);
  assert.equal(structureResourceShowsAssetDetails('EBOOK'), true);
  assert.equal(structureResourceShowsAssetDetails('COMIC'), true);
});
