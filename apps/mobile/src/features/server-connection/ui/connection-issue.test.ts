import assert from 'node:assert/strict';
import test from 'node:test';

import {
  connectionIssueMessageKey,
  serverProfilesWarningMessageKey,
} from './connection-issue';

test('maps boundary and infrastructure failures to stable message keys', () => {
  assert.equal(
    connectionIssueMessageKey('INSECURE_REMOTE_NOT_ALLOWED'),
    'connection.issue.INSECURE_REMOTE_NOT_ALLOWED',
  );
  assert.equal(
    connectionIssueMessageKey('storage-unavailable'),
    'connection.issue.storageUnavailable',
  );
  assert.equal(
    connectionIssueMessageKey('conflict'),
    'connection.issue.conflict',
  );
});

test('maps profile recovery warnings to stable message keys', () => {
  assert.equal(
    serverProfilesWarningMessageKey('recovered-older-snapshot'),
    'connection.profiles.warningRecoveredOlderSnapshot',
  );
  assert.equal(
    serverProfilesWarningMessageKey('maintenance-cleanup-failed'),
    'connection.profiles.warningMaintenanceCleanupFailed',
  );
});
