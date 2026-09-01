import assert from 'node:assert/strict';
import test from 'node:test';
import { comicImageSizing, comicPageSlotSizing } from './comic-model';

test('comic page slots and default width fit stay inside the reading area', () => {
  assert.deepEqual(comicPageSlotSizing('single'), { flex: '0 1 100%', maxWidth: '100%', width: '100%' });
  assert.deepEqual(comicPageSlotSizing('double'), { flex: '1 1 50%', maxWidth: '50%', width: '50%' });
  assert.deepEqual(comicImageSizing('width'), {
    display: 'block',
    height: 'auto',
    maxHeight: '100%',
    maxWidth: '100%',
    objectFit: 'contain',
    width: '100%'
  });
  assert.deepEqual(comicImageSizing('width', 'double'), {
    display: 'block',
    height: '100%',
    maxHeight: '100%',
    maxWidth: '100%',
    objectFit: 'contain',
    width: 'auto'
  });
});
