import assert from 'node:assert/strict';
import test from 'node:test';
import { detectPdfCropBox, pdfContinuousWindowPages } from './pdf-layout';

test('PDF continuous mode keeps only the current page and two neighbors on each side', () => {
  assert.deepEqual(pdfContinuousWindowPages(5, 20), [3, 4, 5, 6, 7]);
  assert.deepEqual(pdfContinuousWindowPages(1, 20), [1, 2, 3]);
  assert.deepEqual(pdfContinuousWindowPages(20, 20), [18, 19, 20]);
});

test('PDF crop analysis returns a normalized reliable content box', () => {
  const width = 20;
  const height = 20;
  const pixels = new Uint8ClampedArray(width * height * 4).fill(255);
  for (let y = 5; y < 15; y += 1) {
    for (let x = 4; x < 16; x += 1) {
      const offset = (y * width + x) * 4;
      pixels[offset] = 20;
      pixels[offset + 1] = 20;
      pixels[offset + 2] = 20;
    }
  }
  assert.deepEqual(detectPdfCropBox(pixels, width, height), { left: 0.1, top: 0.15, right: 0.9, bottom: 0.85 });
});

test('PDF crop analysis preserves the original page when detection is unreliable', () => {
  const blank = new Uint8ClampedArray(10 * 10 * 4).fill(255);
  assert.equal(detectPdfCropBox(blank, 10, 10), null);
});
