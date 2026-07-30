export type UnknownRecord = Readonly<Record<string, unknown>>;

export type ValidationResult<Value> =
  | Readonly<{ ok: true; value: Value }>
  | Readonly<{ ok: false; reason: string }>;

export function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function hasOnlyKeys(
  value: UnknownRecord,
  allowedKeys: ReadonlySet<string>,
): boolean {
  return Object.keys(value).every((key) => allowedKeys.has(key));
}

export function nonEmptyString(
  value: unknown,
  maximumLength: number,
): string | null {
  if (typeof value !== 'string') {
    return null;
  }

  const normalized = value.trim();
  if (normalized.length === 0 || normalized.length > maximumLength) {
    return null;
  }

  return normalized;
}

export function finiteNumberInRange(
  value: unknown,
  minimum: number,
  maximum: number,
): number | null {
  if (
    typeof value !== 'number' ||
    !Number.isFinite(value) ||
    value < minimum ||
    value > maximum
  ) {
    return null;
  }

  return value;
}

export function nonNegativeSafeInteger(value: unknown): number | null {
  if (
    typeof value !== 'number' ||
    !Number.isSafeInteger(value) ||
    value < 0
  ) {
    return null;
  }

  return value;
}
