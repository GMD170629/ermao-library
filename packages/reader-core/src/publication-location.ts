import {
  hasExactReadiumAnchor,
  compareExactReadiumLocators,
  parseReadiumLocatorEnvelope,
  type ReadiumLocatorEnvelope,
  type ReadiumLocatorPayload,
  type ReaderPlatform
} from './exact-locator';

export type EngineLocator = Readonly<{
  engine: 'readium';
  platform: ReaderPlatform;
  version: string;
  payload: Readonly<Record<string, unknown>>;
}>;

export type ReadiumEngineLocator = Omit<EngineLocator, 'payload'> & Readonly<{
  payload: ReadiumLocatorPayload;
}>;

export type ReflowablePublicationLocation = Readonly<{
  kind: 'reflowable';
  engineLocator: ReadiumEngineLocator;
}>;

export type PdfPublicationLocation = Readonly<{
  kind: 'pdf';
  /** Zero-based canonical document page. */
  pageIndex: number;
  /** Normalized reading-line position within the page, quantized to four decimals. */
  pageProgression: number;
  engineLocator?: EngineLocator;
}>;

export type ComicPublicationLocation = Readonly<{
  kind: 'comic';
  /** Zero-based canonical reading-order page. */
  pageIndex: number;
  resourceHref: string;
  engineLocator?: EngineLocator;
}>;

export type AudioPublicationLocation = Readonly<{
  kind: 'audio';
  assetId: string;
  chapterId?: string;
  positionMillis: number;
  engineLocator?: EngineLocator;
}>;

export type PublicationLocation =
  | ReflowablePublicationLocation
  | PdfPublicationLocation
  | ComicPublicationLocation
  | AudioPublicationLocation;

export type PublicationLocationComparison = Readonly<{
  precision: 'exact' | 'unverified';
  sameResource: boolean;
  reason:
    | 'same_reflowable_anchor'
    | 'same_pdf_position'
    | 'same_comic_page'
    | 'same_audio_position'
    | 'missing_location'
    | 'kind_mismatch'
    | 'resource_mismatch'
    | 'anchor_mismatch';
}>;

type UnknownRecord = Record<string, unknown>;

function record(value: unknown): UnknownRecord | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as UnknownRecord
    : null;
}

function nonEmptyString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim().length > 0 ? value : undefined;
}

function hasOnlyKeys(value: UnknownRecord, allowed: readonly string[]): boolean {
  const keys = new Set(allowed);
  return Object.keys(value).every((key) => keys.has(key));
}

function utf8Length(value: unknown): number {
  try {
    return new TextEncoder().encode(JSON.stringify(value)).byteLength;
  } catch {
    return Number.POSITIVE_INFINITY;
  }
}

function safeRelativeHref(value: unknown): string | undefined {
  const href = nonEmptyString(value);
  if (!href || href.length > 8192 || /^[a-z][a-z\d+.-]*:/iu.test(href) || href.startsWith('/') || href.includes('\\')) return undefined;
  const path = href.split(/[?#]/u, 1)[0] ?? '';
  return path.split('/').includes('..') ? undefined : href;
}

function parseEngineLocator(value: unknown): EngineLocator | null {
  const item = record(value);
  if (!item || !hasOnlyKeys(item, ['engine', 'platform', 'version', 'payload'])) return null;
  const version = nonEmptyString(item.version);
  const payload = record(item.payload);
  if (item.engine !== 'readium'
    || (item.platform !== 'web' && item.platform !== 'android' && item.platform !== 'ios')
    || !version || version.length > 256 || !payload) return null;
  return {
    engine: 'readium',
    platform: item.platform,
    version,
    payload
  };
}

export function quantizePageProgression(value: number): number {
  return Math.round(Math.max(0, Math.min(1, value)) * 10_000) / 10_000;
}

export function parsePublicationLocation(value: unknown): PublicationLocation | null {
  if (utf8Length(value) > 64 * 1024) return null;
  const item = record(value);
  if (!item) return null;
  const engineLocator = item.engineLocator === undefined
    ? undefined
    : parseEngineLocator(item.engineLocator) ?? null;
  if (engineLocator === null) return null;
  if (item.kind === 'reflowable') {
    const envelope = engineLocator
      ? parseReadiumLocatorEnvelope(engineLocator)
      : null;
    if (!hasOnlyKeys(item, ['kind', 'engineLocator'])
      || !envelope || !hasExactReadiumAnchor(envelope.payload)) return null;
    return {
      kind: 'reflowable',
      engineLocator: {
        engine: envelope.engine,
        platform: envelope.platform,
        version: envelope.version,
        payload: envelope.payload
      }
    };
  }
  if (item.kind === 'pdf') {
    const pageIndex = item.pageIndex;
    const pageProgression = item.pageProgression;
    if (!hasOnlyKeys(item, ['kind', 'pageIndex', 'pageProgression', 'engineLocator'])
      || !Number.isInteger(pageIndex) || (pageIndex as number) < 0
      || typeof pageProgression !== 'number' || !Number.isFinite(pageProgression)
      || pageProgression < 0 || pageProgression > 1
      || pageProgression !== quantizePageProgression(pageProgression)) return null;
    return { kind: 'pdf', pageIndex: pageIndex as number, pageProgression, ...(engineLocator ? { engineLocator } : {}) };
  }
  if (item.kind === 'comic') {
    const pageIndex = item.pageIndex;
    const resourceHref = safeRelativeHref(item.resourceHref);
    if (!hasOnlyKeys(item, ['kind', 'pageIndex', 'resourceHref', 'engineLocator'])
      || !Number.isInteger(pageIndex) || (pageIndex as number) < 0 || !resourceHref) return null;
    return { kind: 'comic', pageIndex: pageIndex as number, resourceHref, ...(engineLocator ? { engineLocator } : {}) };
  }
  if (item.kind === 'audio') {
    const assetId = nonEmptyString(item.assetId);
    const chapterId = item.chapterId === undefined ? undefined : nonEmptyString(item.chapterId);
    const positionMillis = item.positionMillis;
    if (!hasOnlyKeys(item, ['kind', 'assetId', 'chapterId', 'positionMillis', 'engineLocator'])
      || !assetId || assetId.length > 191 || (item.chapterId !== undefined && (!chapterId || chapterId.length > 191))
      || !Number.isInteger(positionMillis) || (positionMillis as number) < 0) return null;
    return { kind: 'audio', assetId, ...(chapterId ? { chapterId } : {}), positionMillis: positionMillis as number, ...(engineLocator ? { engineLocator } : {}) };
  }
  return null;
}

export function isExactPublicationLocation(value: unknown): value is PublicationLocation {
  return parsePublicationLocation(value) !== null;
}

export function reflowablePublicationLocation(envelope: ReadiumLocatorEnvelope): ReflowablePublicationLocation {
  return {
    kind: 'reflowable',
    engineLocator: {
      engine: envelope.engine,
      platform: envelope.platform,
      version: envelope.version,
      payload: envelope.payload
    }
  };
}

export function readiumEnvelopeFromPublicationLocation(location: ReflowablePublicationLocation): ReadiumLocatorEnvelope {
  return location.engineLocator;
}

export function comparePublicationLocations(
  expected: PublicationLocation | null,
  actual: PublicationLocation | null
): PublicationLocationComparison {
  if (!expected || !actual) return { precision: 'unverified', sameResource: false, reason: 'missing_location' };
  if (expected.kind !== actual.kind) return { precision: 'unverified', sameResource: false, reason: 'kind_mismatch' };
  if (expected.kind === 'reflowable' && actual.kind === 'reflowable') {
    const comparison = compareExactReadiumLocators(
      readiumEnvelopeFromPublicationLocation(expected),
      readiumEnvelopeFromPublicationLocation(actual)
    );
    return comparison.precision === 'exact-block'
      ? { precision: 'exact', sameResource: true, reason: 'same_reflowable_anchor' }
      : {
          precision: 'unverified',
          sameResource: comparison.sameResource,
          reason: comparison.reason === 'different_resource' ? 'resource_mismatch' : 'anchor_mismatch'
        };
  }
  if (expected.kind === 'pdf' && actual.kind === 'pdf') {
    const samePage = expected.pageIndex === actual.pageIndex;
    return samePage && expected.pageProgression === actual.pageProgression
      ? { precision: 'exact', sameResource: true, reason: 'same_pdf_position' }
      : { precision: 'unverified', sameResource: samePage, reason: samePage ? 'anchor_mismatch' : 'resource_mismatch' };
  }
  if (expected.kind === 'comic' && actual.kind === 'comic') {
    const sameResource = expected.resourceHref === actual.resourceHref;
    return sameResource && expected.pageIndex === actual.pageIndex
      ? { precision: 'exact', sameResource: true, reason: 'same_comic_page' }
      : { precision: 'unverified', sameResource, reason: sameResource ? 'anchor_mismatch' : 'resource_mismatch' };
  }
  if (expected.kind === 'audio' && actual.kind === 'audio') {
    const sameResource = expected.assetId === actual.assetId && expected.chapterId === actual.chapterId;
    return sameResource && expected.positionMillis === actual.positionMillis
      ? { precision: 'exact', sameResource: true, reason: 'same_audio_position' }
      : { precision: 'unverified', sameResource, reason: sameResource ? 'anchor_mismatch' : 'resource_mismatch' };
  }
  return { precision: 'unverified', sameResource: false, reason: 'kind_mismatch' };
}
