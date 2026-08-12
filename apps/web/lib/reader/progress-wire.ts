import type { FoliateProgressSnapshot, ReaderLocation, ReflowableFormat } from '@shuku/reader-core';
import {
  READER_ENGINE_PAYLOAD_MAX_BYTES,
  normalizedPercent,
  type ReaderEngineLocator,
  type ReaderLocationContentFingerprint,
  type ReaderProgressLocation,
  type ReaderProgressSnapshot,
  type ReaderTextQuote,
  type ReaderV4Location
} from './model';

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function finiteNumber(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function nonEmptyString(value: unknown) {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function jsonByteLength(value: unknown) {
  try {
    return new TextEncoder().encode(JSON.stringify(value)).byteLength;
  } catch {
    return Number.POSITIVE_INFINITY;
  }
}

function compactRecord(entries: ReadonlyArray<readonly [string, unknown]>) {
  return Object.fromEntries(entries.filter(([, value]) => value !== undefined));
}

function boundedEngineLocator(engineLocator: ReaderEngineLocator | undefined) {
  return engineLocator && jsonByteLength(engineLocator.payload) <= READER_ENGINE_PAYLOAD_MAX_BYTES
    ? engineLocator
    : undefined;
}

export function toV4WireLocation(
  location: ReaderProgressLocation,
  contentFingerprint?: ReaderLocationContentFingerprint
): ReaderV4Location | null {
  if (location.kind === 'audio') {
    return {
      kind: 'audio',
      fileId: location.fileId,
      chapterId: location.chapterId,
      positionMs: Math.max(0, Math.round(location.positionMs))
    };
  }
  if (location.kind === 'comic') {
    return { kind: 'comic', pageIndex: Math.max(1, Math.round(location.pageIndex)) };
  }
  if (location.kind === 'pdf') {
    return { kind: 'pdf', pageNumber: Math.max(1, Math.round(location.pageNumber)) };
  }

  const foliate = location.kind === 'reflowable' ? location.foliate : undefined;
  const payload = compactRecord([
    ['cfi', location.cfi],
    ['href', location.href],
    ['fraction', location.progression],
    ['foliate', foliate]
  ]);
  const engineLocator = Object.keys(payload).length
    ? boundedEngineLocator({
        engine: 'foliate',
        platform: 'web',
        version: 'foliate-web-v1',
        payload
      })
    : undefined;
  const resourceProgression = location.kind === 'reflowable'
    ? location.resourceProgression ?? foliate?.continuous?.sectionFraction
    : undefined;
  const position = location.kind === 'reflowable'
    ? location.position ?? foliate?.location?.current
    : undefined;
  const textQuote = location.kind === 'reflowable' ? location.textQuote : undefined;
  const resourceKey = location.href;
  if (!resourceKey && resourceProgression === undefined && position === undefined && !textQuote && !engineLocator) return null;
  return {
    kind: 'reflow',
    ...(resourceKey ? { resourceKey } : {}),
    ...(resourceProgression !== undefined ? { progression: resourceProgression } : {}),
    ...(position !== undefined ? { position } : {}),
    ...(textQuote ? { textQuote } : {}),
    ...(contentFingerprint ? { contentFingerprint } : {}),
    ...(engineLocator ? { engineLocator } : {})
  };
}

function parseTextQuote(value: unknown): ReaderTextQuote | undefined {
  const item = record(value);
  const exact = nonEmptyString(item.exact);
  if (!exact || exact.length > 512) return undefined;
  const prefix = nonEmptyString(item.prefix);
  const suffix = nonEmptyString(item.suffix);
  if ((prefix?.length ?? 0) > 256 || (suffix?.length ?? 0) > 256) return undefined;
  return { exact, ...(prefix ? { prefix } : {}), ...(suffix ? { suffix } : {}) };
}

function parseLocationFingerprint(value: unknown): ReaderLocationContentFingerprint | undefined {
  const item = record(value);
  const originalFileHash = nonEmptyString(item.originalFileHash);
  const parserVersion = nonEmptyString(item.parserVersion);
  const normalizationVersion = nonEmptyString(item.normalizationVersion);
  return originalFileHash && parserVersion && normalizationVersion
    ? { originalFileHash, parserVersion, normalizationVersion }
    : undefined;
}

function parseEngineLocator(value: unknown): ReaderEngineLocator | undefined {
  const item = record(value);
  const engine = item.engine === 'readium' || item.engine === 'foliate' ? item.engine : undefined;
  const platform = item.platform === 'android' || item.platform === 'ios' || item.platform === 'web'
    ? item.platform
    : undefined;
  const version = nonEmptyString(item.version);
  const payload = record(item.payload);
  if (!engine || !platform || !version || jsonByteLength(payload) > READER_ENGINE_PAYLOAD_MAX_BYTES) return undefined;
  return { engine, platform, version, payload };
}

export function parseV4Location(value: unknown): ReaderV4Location | null {
  const item = record(value);
  const engineLocator = parseEngineLocator(item.engineLocator);
  if (item.kind === 'comic') {
    const pageIndex = finiteNumber(item.pageIndex);
    return pageIndex !== undefined && pageIndex >= 1
      ? { kind: 'comic', pageIndex, ...(engineLocator ? { engineLocator } : {}) }
      : null;
  }
  if (item.kind === 'pdf') {
    const pageNumber = finiteNumber(item.pageNumber);
    return pageNumber !== undefined && pageNumber >= 1
      ? { kind: 'pdf', pageNumber, ...(engineLocator ? { engineLocator } : {}) }
      : null;
  }
  if (item.kind === 'audio') {
    const fileId = nonEmptyString(item.fileId);
    const positionMs = finiteNumber(item.positionMs);
    return fileId && positionMs !== undefined && positionMs >= 0
      ? {
          kind: 'audio',
          fileId,
          chapterId: nonEmptyString(item.chapterId) ?? null,
          positionMs,
          ...(engineLocator ? { engineLocator } : {})
        }
      : null;
  }
  if (item.kind !== 'reflow') return null;
  const resourceKey = nonEmptyString(item.resourceKey);
  const progression = finiteNumber(item.progression);
  const position = finiteNumber(item.position);
  const textQuote = parseTextQuote(item.textQuote);
  const contentFingerprint = parseLocationFingerprint(item.contentFingerprint);
  if (
    !resourceKey
    && progression === undefined
    && position === undefined
    && !textQuote
    && !engineLocator
  ) return null;
  if (progression !== undefined && (progression < 0 || progression > 1)) return null;
  if (position !== undefined && position < 0) return null;
  return {
    kind: 'reflow',
    ...(resourceKey ? { resourceKey } : {}),
    ...(progression !== undefined ? { progression } : {}),
    ...(position !== undefined ? { position } : {}),
    ...(textQuote ? { textQuote } : {}),
    ...(contentFingerprint ? { contentFingerprint } : {}),
    ...(engineLocator ? { engineLocator } : {})
  };
}

export function parseReaderV4ProgressSnapshot(value: unknown): ReaderProgressSnapshot | null {
  const item = record(value);
  const clientId = nonEmptyString(item.clientId);
  const updatedAtEpochMillis = finiteNumber(item.updatedAtEpochMillis);
  const percent = normalizedPercent(finiteNumber(item.percent) ?? null);
  const contentFingerprint = nonEmptyString(item.contentFingerprint);
  if (item.schemaVersion !== 4 || !clientId || updatedAtEpochMillis === undefined || percent === null || !contentFingerprint) return null;
  const location = item.location === null || item.location === undefined ? null : parseV4Location(item.location);
  if (item.location !== null && item.location !== undefined && !location) return null;
  return { schemaVersion: 4, clientId, updatedAtEpochMillis, percent, location, contentFingerprint };
}

export function remoteLocationMatchesPublication(
  location: ReaderV4Location | null,
  localFingerprint: ReaderLocationContentFingerprint | undefined
) {
  if (location?.kind !== 'reflow' || !location.contentFingerprint || !localFingerprint) return true;
  return location.contentFingerprint.originalFileHash === localFingerprint.originalFileHash;
}

function parseProgressPair(value: unknown) {
  const item = record(value);
  const current = finiteNumber(item.current);
  const total = finiteNumber(item.total);
  return current !== undefined && total !== undefined && current >= 0 && total >= 0
    ? { current, total }
    : undefined;
}

function parseFoliatePayload(value: unknown): FoliateProgressSnapshot | undefined {
  const item = record(value);
  const raw = record(item.foliate);
  const section = parseProgressPair(raw.section);
  const locationValue = record(raw.location);
  const current = finiteNumber(locationValue.current);
  const next = finiteNumber(locationValue.next);
  const total = finiteNumber(locationValue.total);
  const location = current !== undefined && next !== undefined && total !== undefined
    ? { current, next, total }
    : undefined;
  const parsed: FoliateProgressSnapshot = {
    ...(section ? { section } : {}),
    ...(location ? { location } : {})
  };
  return Object.keys(parsed).length ? parsed : undefined;
}

function readiumCfi(payload: Readonly<Record<string, unknown>>) {
  const direct = nonEmptyString(payload.cfi);
  if (direct) return direct;
  const locations = record(payload.locations);
  const fragments = Array.isArray(locations.fragments) ? locations.fragments : [];
  return fragments.find((fragment): fragment is string => typeof fragment === 'string' && fragment.startsWith('epubcfi('));
}

/**
 * Maps a remote v4 snapshot into the strongest Foliate location the browser
 * can actually attempt. Foliate/Readium engine payloads are tried first,
 * followed by the public resource anchors and finally the whole-book percent.
 */
export function v4LocationToDomain(
  location: ReaderV4Location | null,
  volumeId: string,
  format: ReflowableFormat | null,
  percent: number
): ReaderLocation | null {
  if (!location) return null;
  if (location.kind === 'comic') return { kind: 'comic', volumeId, pageIndex: Math.max(1, Math.round(location.pageIndex)) };
  if (location.kind === 'pdf') return { kind: 'pdf', pageNumber: Math.max(1, Math.round(location.pageNumber)) };
  if (location.kind === 'audio' || !format) return null;

  const engine = location.engineLocator;
  const payload = engine?.payload ?? {};
  const cfi = engine?.engine === 'foliate'
    ? nonEmptyString(payload.cfi)
    : engine?.engine === 'readium' ? readiumCfi(payload) : undefined;
  const href = location.resourceKey ?? nonEmptyString(payload.href);
  const fraction = engine?.engine === 'foliate' ? finiteNumber(payload.fraction) : undefined;
  const foliate = engine?.engine === 'foliate' ? parseFoliatePayload(payload) : undefined;
  const continuous = location.progression !== undefined ? { sectionFraction: location.progression } : undefined;
  return {
    kind: 'reflowable',
    format,
    ...(cfi ? { cfi } : {}),
    ...(href ? { href } : {}),
    ...(location.progression !== undefined ? { resourceProgression: location.progression } : {}),
    ...(location.position !== undefined ? { position: location.position } : {}),
    ...(location.textQuote ? { textQuote: location.textQuote } : {}),
    progression: fraction !== undefined && fraction >= 0 && fraction <= 1
      ? fraction
      : Math.max(0, Math.min(1, percent / 100)),
    ...((foliate || continuous)
      ? { foliate: { ...foliate, ...(continuous ? { continuous } : {}) } }
      : {})
  };
}
