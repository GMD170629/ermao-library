import assert from 'node:assert/strict';
import test from 'node:test';
import { mediaKindsLabel } from './media-kind-label';

test('formats every media version in stable Chinese and English order', () => {
  const mixed = ['AUDIOBOOK', 'COMIC', 'EBOOK', 'COMIC'] as const;

  assert.equal(mediaKindsLabel([...mixed], 'zh-CN'), '电子书，漫画，有声书');
  assert.equal(mediaKindsLabel([...mixed], 'en-US'), 'E-book, Comic, Audiobook');
});

test('returns an empty label when a work has no media version', () => {
  assert.equal(mediaKindsLabel([], 'zh-CN'), '');
  assert.equal(mediaKindsLabel([], 'en-US'), '');
});
