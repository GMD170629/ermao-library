import assert from 'node:assert/strict';
import test from 'node:test';
import { fetchManagementOverview, parseManagementOverview } from './overview';

test('parses a typed management overview', () => {
  const result = parseManagementOverview({
    cards: { failedImports: 1 },
    checks: { database: { status: 'ok', message: 'ready' } },
    recentEvents: [{
      id: 'event-1',
      level: 'info',
      source: 'system',
      action: 'checked',
      message: 'ok',
      createdAt: '2026-08-22T00:00:00Z'
    }]
  });
  assert.equal(result.cards.failedImports, 1);
  assert.equal(result.checks.database?.status, 'ok');
});

test('loads management overview from its feature client endpoint', async () => {
  const requested: string[] = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    requested.push(String(input));
    return new Response(JSON.stringify({
      ok: true,
      data: { cards: {}, checks: {}, recentEvents: [] }
    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
  try {
    await fetchManagementOverview();
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.deepEqual(requested, ['/api/management/overview']);
});
