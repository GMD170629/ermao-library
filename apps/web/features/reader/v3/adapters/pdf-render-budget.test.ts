import assert from 'node:assert/strict';
import test from 'node:test';
import { PDF_MAX_CANVAS_DIMENSION, PDF_MAX_CANVAS_PIXELS, computePdfRenderBudget, pdfPageScale } from './pdf-render-budget';

test('PDF render budget preserves device scale when safely below the cap', () => {
  const budget = computePdfRenderBudget({ cssWidth: 1000, cssHeight: 1400, devicePixelRatio: 2 });
  assert.equal(budget.outputScale, 2);
  assert.equal(budget.pixelWidth, 2000);
  assert.equal(budget.pixelHeight, 2800);
  assert.equal(budget.constrained, false);
});

test('PDF render budget never exceeds pixel or dimension limits', () => {
  const budget = computePdfRenderBudget({ cssWidth: 5000, cssHeight: 7000, devicePixelRatio: 3 });
  assert.ok(budget.pixelWidth <= PDF_MAX_CANVAS_DIMENSION);
  assert.ok(budget.pixelHeight <= PDF_MAX_CANVAS_DIMENSION);
  assert.ok(budget.pixelWidth * budget.pixelHeight <= PDF_MAX_CANVAS_PIXELS);
  assert.equal(budget.constrained, true);
});

test('PDF render budget remains bounded for extreme aspect ratios', () => {
  for (const [cssWidth, cssHeight] of [[100_000, 20], [20, 100_000], [1_000_000, 1_000_000]]) {
    const budget = computePdfRenderBudget({ cssWidth, cssHeight, devicePixelRatio: 3 });
    assert.ok(budget.pixelWidth <= PDF_MAX_CANVAS_DIMENSION);
    assert.ok(budget.pixelHeight <= PDF_MAX_CANVAS_DIMENSION);
    assert.ok(budget.pixelWidth * budget.pixelHeight <= PDF_MAX_CANVAS_PIXELS);
  }
});

test('PDF fit modes derive scale from the requested viewport edge', () => {
  assert.equal(pdfPageScale({ pageWidth: 600, pageHeight: 800, containerWidth: 1200, containerHeight: 900, fit: 'width', zoom: 1 }), 2);
  assert.equal(pdfPageScale({ pageWidth: 600, pageHeight: 800, containerWidth: 1200, containerHeight: 900, fit: 'page', zoom: 1 }), 1.125);
});
