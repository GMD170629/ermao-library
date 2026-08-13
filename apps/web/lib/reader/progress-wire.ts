import {
  hasExactReadiumAnchor,
  parseReadiumLocatorEnvelope,
  publicationFingerprintsMatch,
  type PublicationFingerprint,
  type ReadiumLocatorEnvelope,
  type ReaderLocation,
  type ReflowableFormat
} from '@shuku/reader-core';
import { normalizedPercent, type ReaderProgressSnapshot } from './model';

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function finiteNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

export function parseReaderV4ProgressSnapshot(value: unknown): ReaderProgressSnapshot | null {
  const item = record(value);
  const revision = finiteNumber(item.revision);
  const displayPercent = normalizedPercent(finiteNumber(item.displayPercent) ?? null);
  const receivedAtEpochMillis = finiteNumber(item.receivedAtEpochMillis);
  const capturedAtEpochMillis = finiteNumber(item.capturedAtEpochMillis);
  const locator = parseReadiumLocatorEnvelope(item.locator);
  if (item.schemaVersion !== 4 || revision === undefined || revision < 1 || !Number.isInteger(revision)
    || displayPercent === null || receivedAtEpochMillis === undefined || receivedAtEpochMillis < 0
    || !locator || !hasExactReadiumAnchor(locator.payload)) return null;
  return {
    schemaVersion: 4,
    revision,
    locator,
    displayPercent,
    receivedAtEpochMillis,
    ...(capturedAtEpochMillis !== undefined && capturedAtEpochMillis >= 0 ? { capturedAtEpochMillis } : {})
  };
}

export function remoteLocationMatchesPublication(
  locator: ReadiumLocatorEnvelope | null,
  publicationFingerprint: PublicationFingerprint | undefined
) {
  return Boolean(locator && publicationFingerprintsMatch(locator.publication, publicationFingerprint));
}

/** Maps only an exact Readium payload. No progression or percentage fallback exists. */
export function v4LocationToDomain(
  locator: ReadiumLocatorEnvelope | null,
  _volumeId: string,
  format: ReflowableFormat | null
): ReaderLocation | null {
  if (!locator || !format || !hasExactReadiumAnchor(locator.payload)) return null;
  const locations = locator.payload.locations;
  const fragments = Array.isArray(locations.fragments) ? locations.fragments : [];
  const cfi = fragments.find((fragment) => fragment.startsWith('epubcfi('));
  const highlight = locator.payload.text?.highlight;
  return {
    kind: 'reflowable',
    format,
    href: locator.payload.href,
    ...(cfi ? { cfi } : {}),
    ...(typeof locations.progression === 'number' ? { resourceProgression: locations.progression } : {}),
    ...(typeof locations.position === 'number' ? { position: locations.position } : {}),
    ...(highlight ? {
      textQuote: {
        exact: highlight,
        ...(locator.payload.text?.before ? { prefix: locator.payload.text.before } : {}),
        ...(locator.payload.text?.after ? { suffix: locator.payload.text.after } : {})
      }
    } : {}),
    exactLocator: locator
  };
}

export function exactLocatorFromDomain(location: ReaderLocation): ReadiumLocatorEnvelope | null {
  return location.kind === 'reflowable' && location.exactLocator
    ? parseReadiumLocatorEnvelope(location.exactLocator)
    : null;
}
