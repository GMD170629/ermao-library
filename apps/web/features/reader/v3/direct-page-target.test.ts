import assert from 'node:assert/strict';
import test from 'node:test';
import { requestedPdfPage } from './direct-page-target';

test('PDF direct page targets accept only bounded positive integers', () => {
  assert.equal(requestedPdfPage('7', 20), 7);
  assert.equal(requestedPdfPage('0', 20), null);
  assert.equal(requestedPdfPage('7.5', 20), null);
  assert.equal(requestedPdfPage('21', 20), null);
  assert.equal(requestedPdfPage('7', null), 7);
});

