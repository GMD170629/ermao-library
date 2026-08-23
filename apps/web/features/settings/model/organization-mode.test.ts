import assert from 'node:assert/strict';
import test from 'node:test';
import { ORGANIZATION_MODES } from './organization-mode';

test('only the two ADR 0018 organization modes are public', () => {
  assert.deepEqual(ORGANIZATION_MODES.map((mode) => mode.value), ['FLAT', 'VOLUMES']);
});
