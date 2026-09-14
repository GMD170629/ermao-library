import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import { sha256Hex } from './sha256';

test('HTTP-compatible WASM hashing matches SHA-256 vectors and binary artifact bytes', () => {
  for (const bytes of [new Uint8Array(), new TextEncoder().encode('abc'), new Uint8Array(1024 * 1024).fill(173)]) {
    assert.equal(sha256Hex(bytes.buffer), createHash('sha256').update(bytes).digest('hex'));
  }
});
