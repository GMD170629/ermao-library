import {
  type ValidationResult,
  hasOnlyKeys,
  isRecord,
} from '../../../shared/validation/unknown';

const ENVELOPE_KEYS = new Set(['ok', 'data']);
const DATA_KEYS = new Set(['service', 'status']);
const SETUP_DATA_KEYS = new Set(['initialized']);

export type ServiceHealth = Readonly<{
  service: 'ermao-books';
  status: 'error' | 'ok';
}>;

export function decodeServiceHealth(
  value: unknown,
): ValidationResult<ServiceHealth> {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, ENVELOPE_KEYS) ||
    value.ok !== true ||
    !isRecord(value.data) ||
    !hasOnlyKeys(value.data, DATA_KEYS) ||
    value.data.service !== 'ermao-books' ||
    (value.data.status !== 'ok' && value.data.status !== 'error')
  ) {
    return { ok: false, reason: 'INVALID_HEALTH_ENVELOPE' };
  }

  return {
    ok: true,
    value: {
      service: value.data.service,
      status: value.data.status,
    },
  };
}

export type SetupStatus = Readonly<{ initialized: boolean }>;

export function decodeSetupStatus(
  value: unknown,
): ValidationResult<SetupStatus> {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, ENVELOPE_KEYS) ||
    value.ok !== true ||
    !isRecord(value.data) ||
    !hasOnlyKeys(value.data, SETUP_DATA_KEYS) ||
    typeof value.data.initialized !== 'boolean'
  ) {
    return { ok: false, reason: 'INVALID_SETUP_STATUS_ENVELOPE' };
  }
  return { ok: true, value: { initialized: value.data.initialized } };
}
