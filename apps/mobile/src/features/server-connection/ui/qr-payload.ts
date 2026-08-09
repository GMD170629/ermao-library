export const MAXIMUM_QR_TEXT_LENGTH = 2_048;

const CONTROL_CHARACTER_PATTERN = /[\u0000-\u001F\u007F-\u009F]/u;

export type QrPayloadRejectionReason =
  | 'control-characters'
  | 'empty'
  | 'too-long';

export type QrPayloadValidation =
  | Readonly<{ ok: true; value: string }>
  | Readonly<{ ok: false; reason: QrPayloadRejectionReason }>;

export function validateQrText(value: string): QrPayloadValidation {
  const trimmed = value.trim();
  if (trimmed.length === 0) {
    return { ok: false, reason: 'empty' };
  }
  if (trimmed.length > MAXIMUM_QR_TEXT_LENGTH) {
    return { ok: false, reason: 'too-long' };
  }
  if (CONTROL_CHARACTER_PATTERN.test(trimmed)) {
    return { ok: false, reason: 'control-characters' };
  }
  return { ok: true, value: trimmed };
}

export type QrPayloadGateResult =
  | Readonly<{ status: 'accepted'; value: string }>
  | Readonly<{
      reason: QrPayloadRejectionReason;
      status: 'rejected';
    }>
  | Readonly<{ status: 'locked' }>;

export class QrPayloadGate {
  private locked = false;

  consume(value: string): QrPayloadGateResult {
    if (this.locked) {
      return { status: 'locked' };
    }
    this.locked = true;
    const validation = validateQrText(value);
    return validation.ok
      ? { status: 'accepted', value: validation.value }
      : { status: 'rejected', reason: validation.reason };
  }

  lock(): void {
    this.locked = true;
  }

  reset(): void {
    this.locked = false;
  }
}
