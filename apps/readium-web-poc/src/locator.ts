import {
  getCssSelector,
  Locator,
  LocatorLocations,
  LocatorText
} from '@readium/shared';
import {
  boundedText,
  compareAnchors,
  compareFingerprints,
  ENGINE_LOCATOR_MAX_BYTES,
  utf8Length,
  type LocatorComparison
} from './locator-policy';
import type { PublicationFingerprint } from './api';

export { ENGINE_LOCATOR_MAX_BYTES, TEXT_QUOTE_MAX_LENGTH, type LocatorComparison } from './locator-policy';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function boundedLocator(locator: Locator): Locator {
  const text = locator.text
    ? new LocatorText({
        highlight: boundedText(locator.text.highlight),
        before: boundedText(locator.text.before),
        after: boundedText(locator.text.after)
      })
    : undefined;
  const exactCandidate = new Locator({
    href: locator.href,
    type: locator.type,
    title: locator.title,
    locations: locator.locations,
    text
  });
  if (utf8Length(JSON.stringify(exactCandidate.serialize())) <= ENGINE_LOCATOR_MAX_BYTES) {
    return exactCandidate;
  }
  return new Locator({
    href: locator.href,
    type: locator.type,
    title: locator.title,
    locations: new LocatorLocations({
      progression: locator.locations.progression,
      totalProgression: locator.locations.totalProgression,
      position: locator.locations.position
    })
  });
}

export function serializeWebEngineLocator(
  locator: Locator,
  fingerprint: PublicationFingerprint | undefined
): string {
  const payload = boundedLocator(locator).serialize();
  const envelope = {
    engine: 'readium',
    platform: 'web',
    version: 'readium-ts:2.8.2',
    publication: fingerprint,
    payload
  };
  const json = JSON.stringify(envelope, null, 2);
  if (utf8Length(JSON.stringify(envelope)) > ENGINE_LOCATOR_MAX_BYTES) {
    throw new Error('locator_payload_too_large');
  }
  return json;
}

export type ImportedLocator = Readonly<{
  locator: Locator;
  fingerprint?: PublicationFingerprint;
}>;

function deserializeFingerprint(decoded: Record<string, unknown>): PublicationFingerprint | undefined {
  const value = decoded.publication;
  if (!isRecord(value)
    || typeof value.originalFileHash !== 'string'
    || typeof value.parser !== 'string'
    || typeof value.normalization !== 'string') return undefined;
  return {
    originalFileHash: value.originalFileHash,
    parser: value.parser,
    normalization: value.normalization
  };
}

export function parseImportedLocator(input: string): ImportedLocator {
  if (utf8Length(input) > ENGINE_LOCATOR_MAX_BYTES) throw new Error('locator_payload_too_large');
  const decoded: unknown = JSON.parse(input);
  const payload = isRecord(decoded) && decoded.engine === 'readium' && 'payload' in decoded
    ? decoded.payload
    : decoded;
  if (!isRecord(payload)) throw new Error('locator_invalid');
  const locator = Locator.deserialize(payload);
  if (!locator) throw new Error('locator_invalid');
  return { locator, fingerprint: isRecord(decoded) ? deserializeFingerprint(decoded) : undefined };
}

export function compareLocators(
  expected: Locator | null,
  actual: Locator | null,
  expectedFingerprint?: PublicationFingerprint,
  actualFingerprint?: PublicationFingerprint
): LocatorComparison {
  const fingerprintComparison = compareFingerprints(expectedFingerprint, actualFingerprint);
  if (expected && actual && fingerprintComparison === 'missing') {
    return { precision: 'unverified', sameResource: expected.href === actual.href, reason: 'fingerprint_missing' };
  }
  if (fingerprintComparison === 'mismatch') {
    return { precision: 'fallback', sameResource: expected?.href === actual?.href, reason: 'fingerprint_mismatch' };
  }
  return compareAnchors(
    expected ? {
      href: expected.href,
      cssSelector: getCssSelector(expected.locations),
      highlight: expected.text?.highlight,
      progression: expected.locations.progression
    } : null,
    actual ? {
      href: actual.href,
      cssSelector: getCssSelector(actual.locations),
      highlight: actual.text?.highlight,
      progression: actual.locations.progression
    } : null
  );
}

export function locatorSummary(locator: Locator | null): Record<string, unknown> | null {
  if (!locator) return null;
  return {
    href: locator.href,
    cssSelector: getCssSelector(locator.locations) ?? null,
    progression: locator.locations.progression ?? null,
    totalProgression: locator.locations.totalProgression ?? null,
    position: locator.locations.position ?? null,
    text: boundedText(locator.text?.highlight) ?? null
  };
}
