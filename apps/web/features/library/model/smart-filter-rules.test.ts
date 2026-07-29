import assert from 'node:assert/strict';
import test from 'node:test';
import {
  applicableSmartFilterRules,
  parseSmartFilterRules,
  serializableSmartFilterRules,
  smartFilterConditionComplete
} from './smart-filter-rules';

test('parses supported route rules and rejects malformed input', () => {
  assert.deepEqual(parseSmartFilterRules(JSON.stringify({
    combinator: 'ANY',
    conditions: [
      { field: 'readingStatus', operator: 'equals', value: 'READING' },
      { field: 'tag', operator: 'contains', value: '科幻' }
    ]
  })), {
    combinator: 'ANY',
    conditions: [
      { id: 'route-filter-0', field: 'readingStatus', operator: 'equals', value: 'READING' },
      { id: 'route-filter-1', field: 'tag', operator: 'contains', value: '科幻' }
    ]
  });
  assert.deepEqual(parseSmartFilterRules('{invalid'), { combinator: 'ALL', conditions: [] });
});

test('keeps only complete conditions for previews and persistence', () => {
  const rules = {
    combinator: 'ALL' as const,
    conditions: [
      { id: 'complete', field: 'readingStatus', operator: 'equals', value: 'READING' },
      { id: 'missing', field: 'tag', operator: 'contains', value: '' },
      { id: 'boolean', field: 'hasCover', operator: 'is_true' }
    ]
  };

  assert.equal(smartFilterConditionComplete(rules.conditions[0]), true);
  assert.equal(smartFilterConditionComplete(rules.conditions[1]), false);
  assert.equal(smartFilterConditionComplete(rules.conditions[2]), true);
  assert.deepEqual(applicableSmartFilterRules(rules).conditions.map((condition) => condition.id), [
    'complete',
    'boolean'
  ]);
  assert.deepEqual(serializableSmartFilterRules(applicableSmartFilterRules(rules)), {
    combinator: 'ALL',
    conditions: [
      { field: 'readingStatus', operator: 'equals', value: 'READING' },
      { field: 'hasCover', operator: 'is_true' }
    ]
  });
});
