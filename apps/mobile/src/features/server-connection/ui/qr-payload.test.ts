import assert from 'node:assert/strict';
import test from 'node:test';

import {
  MAXIMUM_QR_TEXT_LENGTH,
  QrPayloadGate,
  validateQrText,
} from './qr-payload';

test('accepts bounded plain text and trims surrounding whitespace', () => {
  assert.deepEqual(validateQrText('  https://books.example.com/shuku  '), {
    ok: true,
    value: 'https://books.example.com/shuku',
  });
});

test('rejects empty, oversized, and control-character payloads', () => {
  assert.deepEqual(validateQrText('   '), {
    ok: false,
    reason: 'empty',
  });
  assert.deepEqual(
    validateQrText('a'.repeat(MAXIMUM_QR_TEXT_LENGTH + 1)),
    { ok: false, reason: 'too-long' },
  );
  assert.deepEqual(validateQrText('https://books.example.com\nother'), {
    ok: false,
    reason: 'control-characters',
  });
});

test('locks before returning either an accepted or rejected result', () => {
  const acceptedGate = new QrPayloadGate();
  assert.equal(acceptedGate.consume('https://books.example.com').status, 'accepted');
  assert.deepEqual(acceptedGate.consume('https://other.example.com'), {
    status: 'locked',
  });

  const rejectedGate = new QrPayloadGate();
  assert.equal(rejectedGate.consume('').status, 'rejected');
  assert.deepEqual(rejectedGate.consume('https://books.example.com'), {
    status: 'locked',
  });
  rejectedGate.reset();
  assert.equal(rejectedGate.consume('https://books.example.com').status, 'accepted');
});
