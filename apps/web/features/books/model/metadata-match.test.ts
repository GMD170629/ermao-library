import assert from 'node:assert/strict';
import test from 'node:test';
import { metadataMatchLabels } from './metadata-match';

test('summarizes match outcome, scope, and known or unknown reason codes for the candidate view', () => {
  assert.deepEqual(metadataMatchLabels({
    outcome: 'REJECTED', level: 'VOLUME', candidateKey: 'provider:item',
    evidenceIds: ['title'], reasons: ['AUTHOR_CONFLICT', 'NEW_REASON'], allowedFields: []
  }), {
    outcome: '已排除', level: '卷册', reasons: ['作者不一致', '其他匹配原因']
  });
});
