export const ENGINE_LOCATOR_MAX_BYTES = 64 * 1024;
export const TEXT_QUOTE_MAX_LENGTH = 512;

export type SyncPrecision = 'exact-block' | 'approximate-resource' | 'fallback' | 'unverified';

export type LocatorComparison = Readonly<{
  precision: SyncPrecision;
  sameResource: boolean;
  progressionDelta?: number;
  reason: string;
}>;

export type ComparableAnchor = Readonly<{
  href: string;
  cssSelector?: string;
  highlight?: string;
  progression?: number;
}>;

export type ComparableFingerprint = Readonly<{
  originalFileHash: string;
  parser: string;
  normalization: string;
}>;

export function compareFingerprints(
  expected: ComparableFingerprint | undefined,
  actual: ComparableFingerprint | undefined
): 'match' | 'missing' | 'mismatch' {
  if (!expected || !actual) return 'missing';
  return expected.originalFileHash === actual.originalFileHash
    && expected.parser === actual.parser
    && expected.normalization === actual.normalization
    ? 'match'
    : 'mismatch';
}

export function utf8Length(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

export function boundedText(value: string | undefined): string | undefined {
  if (!value) return undefined;
  return value.length <= TEXT_QUOTE_MAX_LENGTH ? value : value.slice(0, TEXT_QUOTE_MAX_LENGTH);
}

export function compareAnchors(
  expected: ComparableAnchor | null,
  actual: ComparableAnchor | null
): LocatorComparison {
  if (!expected || !actual) {
    return { precision: 'unverified', sameResource: false, reason: 'missing_locator' };
  }
  const sameResource = expected.href === actual.href;
  if (!sameResource) {
    return { precision: 'fallback', sameResource, reason: 'different_resource' };
  }
  if (expected.cssSelector && actual.cssSelector && expected.cssSelector === actual.cssSelector) {
    return { precision: 'exact-block', sameResource, reason: 'same_css_selector' };
  }
  if (expected.highlight && actual.highlight
    && (expected.highlight === actual.highlight || actual.highlight.startsWith(expected.highlight))) {
    return { precision: 'exact-block', sameResource, reason: 'same_text_anchor' };
  }
  if (expected.progression !== undefined && actual.progression !== undefined) {
    const progressionDelta = Math.abs(expected.progression - actual.progression);
    return {
      precision: progressionDelta <= 0.02 ? 'approximate-resource' : 'fallback',
      sameResource,
      progressionDelta,
      reason: progressionDelta <= 0.02 ? 'resource_progression_within_2_percent' : 'resource_progression_drift'
    };
  }
  return { precision: 'fallback', sameResource, reason: 'resource_only' };
}
