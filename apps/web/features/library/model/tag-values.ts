const TAG_SEPARATOR_PATTERN = /[,，;；\r\n]+/u;
const FACET_IGNORED_CHARACTER_PATTERN = /[\s_\-.\[\]()（）【】《》:：,，!！?？"'“”‘’·・、/\\]+/gu;

export function normalizeTagValue(value: string): string {
  return value
    .normalize('NFKC')
    .toLocaleLowerCase()
    .replace(FACET_IGNORED_CHARACTER_PATTERN, '')
    .trim();
}

export function uniqueTagValues(values: Iterable<string>): string[] {
  const uniqueValues: string[] = [];
  const seen = new Set<string>();
  for (const rawValue of values) {
    const value = rawValue.replace(/\s+/gu, ' ').trim();
    const key = normalizeTagValue(value);
    if (!value || !key || seen.has(key)) continue;
    seen.add(key);
    uniqueValues.push(value);
  }
  return uniqueValues;
}

export function parseTagValues(value: string): string[] {
  return uniqueTagValues(value.split(TAG_SEPARATOR_PATTERN));
}

export function appendTagValues(
  currentValues: readonly string[],
  nextValues: Iterable<string>
): string[] {
  return uniqueTagValues([...currentValues, ...nextValues]);
}

export function tagValuesOverlap(
  leftValues: readonly string[],
  rightValues: readonly string[]
): string[] {
  const rightKeys = new Set(rightValues.map(normalizeTagValue).filter(Boolean));
  return uniqueTagValues(leftValues).filter((value) => rightKeys.has(normalizeTagValue(value)));
}
