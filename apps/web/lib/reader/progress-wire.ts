import {
  parsePublicationLocation,
  publicationFingerprintsMatch,
  quantizePageProgression,
  type PublicationFingerprint,
  type PublicationLocation,
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
  const locator = parsePublicationLocation(item.locator);
  if (item.schemaVersion !== 4 || revision === undefined || revision < 1 || !Number.isInteger(revision)
    || displayPercent === null || receivedAtEpochMillis === undefined || receivedAtEpochMillis < 0
    || !locator) return null;
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
  locator: PublicationLocation | null,
  publicationFingerprint: PublicationFingerprint | undefined
) {
  return Boolean(locator && publicationFingerprintsMatch(locator.publication, publicationFingerprint));
}

/** Maps only an exact Readium payload. No progression or percentage fallback exists. */
export function v4LocationToDomain(
  locator: PublicationLocation | null,
  volumeId: string,
  format: ReflowableFormat | null
): ReaderLocation | null {
  if (!locator) return null;
  if (locator.kind === 'pdf') {
    return { kind: 'pdf', pageNumber: locator.pageIndex + 1, pageProgression: locator.pageProgression };
  }
  if (locator.kind === 'comic') {
    return { kind: 'comic', volumeId, pageIndex: locator.pageIndex + 1, resourceHref: locator.resourceHref };
  }
  if (locator.kind !== 'reflowable' || !format) return null;
  const envelope = { ...locator.engineLocator, publication: locator.publication };
  const locations = locator.engineLocator.payload.locations;
  const fragments = Array.isArray(locations.fragments) ? locations.fragments : [];
  const cfi = fragments.find((fragment) => fragment.startsWith('epubcfi('));
  const highlight = locator.engineLocator.payload.text?.highlight;
  return {
    kind: 'reflowable',
    format,
    href: locator.engineLocator.payload.href,
    ...(cfi ? { cfi } : {}),
    ...(typeof locations.progression === 'number' ? { resourceProgression: locations.progression } : {}),
    ...(typeof locations.position === 'number' ? { position: locations.position } : {}),
    ...(highlight ? {
      textQuote: {
        exact: highlight,
        ...(locator.engineLocator.payload.text?.before ? { prefix: locator.engineLocator.payload.text.before } : {}),
        ...(locator.engineLocator.payload.text?.after ? { suffix: locator.engineLocator.payload.text.after } : {})
      }
    } : {}),
    exactLocator: envelope
  };
}

export function exactLocatorFromDomain(location: ReaderLocation): PublicationLocation | null {
  return location.kind === 'reflowable' && location.exactLocator
    ? parsePublicationLocation({
        kind: 'reflowable',
        publication: location.exactLocator.publication,
        engineLocator: {
          engine: location.exactLocator.engine,
          platform: location.exactLocator.platform,
          version: location.exactLocator.version,
          payload: location.exactLocator.payload
        }
      })
    : null;
}

export function publicationLocationFromDomain(
  location: ReaderLocation,
  publication: PublicationFingerprint
): PublicationLocation | null {
  if (location.kind === 'reflowable') return exactLocatorFromDomain(location);
  if (location.kind === 'pdf') {
    return parsePublicationLocation({
      kind: 'pdf',
      publication,
      pageIndex: location.pageNumber - 1,
      pageProgression: quantizePageProgression(location.pageProgression ?? 0)
    });
  }
  if (location.kind === 'comic' && location.resourceHref) {
    return parsePublicationLocation({
      kind: 'comic',
      publication,
      pageIndex: location.pageIndex - 1,
      resourceHref: location.resourceHref
    });
  }
  return null;
}
