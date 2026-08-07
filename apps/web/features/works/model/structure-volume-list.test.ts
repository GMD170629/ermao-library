import assert from 'node:assert/strict';
import test from 'node:test';
import { COLLAPSED_STRUCTURE_VOLUME_LIMIT, structureVolumeList, structureVolumeShowsFileDetails } from './structure-volume-list';

const volumes = Array.from({ length: 12 }, (_, index) => `volume-${index + 1}`);

test('content structure shows at most ten volumes by default', () => {
  const result = structureVolumeList(volumes.slice(0, 10), false, 12);

  assert.equal(COLLAPSED_STRUCTURE_VOLUME_LIMIT, 10);
  assert.deepEqual(result.visibleVolumes, volumes.slice(0, 10));
  assert.equal(result.canToggle, true);
});

test('content structure shows every volume after expansion', () => {
  const result = structureVolumeList(volumes, true);

  assert.deepEqual(result.visibleVolumes, volumes);
  assert.equal(result.canToggle, true);
});

test('content structure does not offer a toggle for ten or fewer volumes', () => {
  const result = structureVolumeList(volumes.slice(0, 10), false);

  assert.deepEqual(result.visibleVolumes, volumes.slice(0, 10));
  assert.equal(result.canToggle, false);
});

test('content structure hides source file details for audiobook volumes', () => {
  assert.equal(structureVolumeShowsFileDetails('AUDIOBOOK'), false);
  assert.equal(structureVolumeShowsFileDetails('EBOOK'), true);
  assert.equal(structureVolumeShowsFileDetails('COMIC'), true);
});
