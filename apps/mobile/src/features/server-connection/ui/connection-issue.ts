import type { MessageKey } from '../../../shared/i18n/public';
import type {
  ConnectionIssue,
  ServerProfilesWarning,
} from './contracts';

const messageKeys: Readonly<Record<ConnectionIssue, MessageKey>> = {
  CREDENTIALS_NOT_ALLOWED: 'connection.issue.CREDENTIALS_NOT_ALLOWED',
  DEVICE_LOOPBACK_NOT_ALLOWED:
    'connection.issue.DEVICE_LOOPBACK_NOT_ALLOWED',
  EMPTY: 'connection.issue.EMPTY',
  INSECURE_REMOTE_NOT_ALLOWED:
    'connection.issue.INSECURE_REMOTE_NOT_ALLOWED',
  INVALID: 'connection.issue.INVALID',
  QUERY_OR_FRAGMENT_NOT_ALLOWED:
    'connection.issue.QUERY_OR_FRAGMENT_NOT_ALLOWED',
  UNSUPPORTED_SCHEME: 'connection.issue.UNSUPPORTED_SCHEME',
  cancelled: 'connection.issue.cancelled',
  capacity: 'connection.issue.capacity',
  conflict: 'connection.issue.conflict',
  'corrupt-storage': 'connection.issue.corruptStorage',
  incompatible: 'connection.issue.incompatible',
  network: 'connection.issue.network',
  'storage-unavailable': 'connection.issue.storageUnavailable',
  timeout: 'connection.issue.timeout',
  unhealthy: 'connection.issue.unhealthy',
  unknown: 'connection.issue.unknown',
};

export function connectionIssueMessageKey(
  issue: ConnectionIssue,
): MessageKey {
  return messageKeys[issue];
}

export function serverProfilesWarningMessageKey(
  warning: ServerProfilesWarning,
): MessageKey {
  switch (warning) {
    case 'maintenance-cleanup-failed':
      return 'connection.profiles.warningMaintenanceCleanupFailed';
    case 'recovered-older-snapshot':
      return 'connection.profiles.warningRecoveredOlderSnapshot';
  }
}
