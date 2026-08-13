export const READIUM_LOCATOR_ENVELOPE_MAX_BYTES = 64 * 1024;
export const READIUM_LOCATOR_HIGHLIGHT_MAX_LENGTH = 512;
export const READIUM_LOCATOR_CONTEXT_MAX_LENGTH = 256;

export type ReaderPlatform = 'web' | 'android' | 'ios';

export type PublicationFingerprint = Readonly<{
  originalFileHash: string;
  parser: string;
  normalization: string;
}>;

export type ReadiumLocatorText = Readonly<{
  before?: string;
  highlight?: string;
  after?: string;
}>;

export type ReadiumLocatorLocations = Readonly<{
  cssSelector?: string;
  fragments?: readonly string[];
  progression?: number;
  totalProgression?: number;
  position?: number;
}> & Readonly<Record<string, unknown>>;

export type ReadiumLocatorPayload = Readonly<{
  href: string;
  type: string;
  title?: string;
  locations: ReadiumLocatorLocations;
  text?: ReadiumLocatorText;
}> & Readonly<Record<string, unknown>>;

export type ReadiumLocatorEnvelope = Readonly<{
  engine: 'readium';
  platform: ReaderPlatform;
  version: string;
  publication: PublicationFingerprint;
  payload: ReadiumLocatorPayload;
}>;

export type ExactLocatorComparison = Readonly<{
  precision: 'exact-block' | 'unverified';
  sameResource: boolean;
  reason:
    | 'same_css_selector'
    | 'same_fragment'
    | 'same_text_anchor'
    | 'fingerprint_missing'
    | 'fingerprint_mismatch'
    | 'different_resource'
    | 'missing_locator'
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

function finiteNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function codePointLength(value: string): number {
  return Array.from(value).length;
}

function utf8Length(value: unknown): number {
  try {
    return new TextEncoder().encode(JSON.stringify(value)).byteLength;
  } catch {
    return Number.POSITIVE_INFINITY;
  }
}

export function parsePublicationFingerprint(value: unknown): PublicationFingerprint | null {
  const item = record(value);
  if (!item) return null;
  const originalFileHash = nonEmptyString(item.originalFileHash);
  const parser = nonEmptyString(item.parser);
  const normalization = nonEmptyString(item.normalization);
  return originalFileHash && /^(?:sha256:)?[a-f\d]{64}$/iu.test(originalFileHash)
    && parser && codePointLength(parser) <= 256 && normalization && codePointLength(normalization) <= 256
    ? { originalFileHash: `sha256:${originalFileHash.replace(/^sha256:/iu, '').toLowerCase()}`, parser, normalization }
    : null;
}

function parseText(value: unknown): ReadiumLocatorText | undefined | null {
  if (value === undefined) return undefined;
  const item = record(value);
  if (!item) return null;
  if (item.before !== undefined && typeof item.before !== 'string') return null;
  if (item.highlight !== undefined && typeof item.highlight !== 'string') return null;
  if (item.after !== undefined && typeof item.after !== 'string') return null;
  const before = nonEmptyString(item.before);
  const highlight = nonEmptyString(item.highlight);
  const after = nonEmptyString(item.after);
  if ((before ? codePointLength(before) : 0) > READIUM_LOCATOR_CONTEXT_MAX_LENGTH
    || (after ? codePointLength(after) : 0) > READIUM_LOCATOR_CONTEXT_MAX_LENGTH
    || (highlight ? codePointLength(highlight) : 0) > READIUM_LOCATOR_HIGHLIGHT_MAX_LENGTH) return null;
  return before || highlight || after
    ? { ...(before ? { before } : {}), ...(highlight ? { highlight } : {}), ...(after ? { after } : {}) }
    : undefined;
}

function parseLocations(value: unknown): ReadiumLocatorLocations | null {
  const item = record(value);
  if (!item) return null;
  const cssSelector = nonEmptyString(item.cssSelector);
  if (item.cssSelector !== undefined && !cssSelector) return null;
  if (item.fragments !== undefined && !Array.isArray(item.fragments)) return null;
  const fragmentValues = Array.isArray(item.fragments) ? item.fragments : undefined;
  if (fragmentValues?.some((fragment) => typeof fragment !== 'string' || fragment.trim().length === 0)) return null;
  const fragments = fragmentValues?.filter((fragment): fragment is string => typeof fragment === 'string');
  const progression = finiteNumber(item.progression);
  const totalProgression = finiteNumber(item.totalProgression);
  const position = finiteNumber(item.position);
  if (progression !== undefined && (progression < 0 || progression > 1)) return null;
  if (totalProgression !== undefined && (totalProgression < 0 || totalProgression > 1)) return null;
  if (position !== undefined && (!Number.isInteger(position) || position < 1)) return null;
  if ((cssSelector ? codePointLength(cssSelector) : 0) > 4096 || (fragments?.length ?? 0) > 16
    || fragments?.some((fragment) => codePointLength(fragment) > 4096)) return null;
  return {
    ...item,
    ...(cssSelector ? { cssSelector } : {}),
    ...(fragments?.length ? { fragments } : {}),
    ...(progression !== undefined ? { progression } : {}),
    ...(totalProgression !== undefined ? { totalProgression } : {}),
    ...(position !== undefined ? { position } : {})
  };
}

export function parseReadiumLocatorEnvelope(value: unknown): ReadiumLocatorEnvelope | null {
  if (utf8Length(value) > READIUM_LOCATOR_ENVELOPE_MAX_BYTES) return null;
  const item = record(value);
  if (!item || item.engine !== 'readium') return null;
  const platform = item.platform === 'web' || item.platform === 'android' || item.platform === 'ios'
    ? item.platform
    : null;
  const version = nonEmptyString(item.version);
  const publication = parsePublicationFingerprint(item.publication);
  const payload = record(item.payload);
  if (!platform || !version || codePointLength(version) > 256 || !publication || !payload) return null;
  const href = nonEmptyString(payload.href);
  const type = nonEmptyString(payload.type);
  const locations = parseLocations(payload.locations);
  const text = parseText(payload.text);
  const hrefPath = href?.split(/[?#]/u, 1)[0] ?? '';
  const invalidHref = !href || /^[a-z][a-z\d+.-]*:/iu.test(href) || href.startsWith('/')
    || href.includes('\\') || hrefPath.split('/').includes('..');
  const title = nonEmptyString(payload.title);
  if (invalidHref || codePointLength(href) > 8192 || !type || codePointLength(type) > 256 || !locations
    || text === null || (payload.title !== undefined && (!title || codePointLength(title) > 4096))) return null;
  const parsed: ReadiumLocatorEnvelope = {
    engine: 'readium',
    platform,
    version,
    publication,
    payload: {
      ...payload,
      href,
      type,
      locations,
      ...(title ? { title } : {}),
      ...(text ? { text } : {})
    }
  };
  return utf8Length(parsed) <= READIUM_LOCATOR_ENVELOPE_MAX_BYTES ? parsed : null;
}

export function readiumLocatorFragments(locator: ReadiumLocatorPayload): readonly string[] {
  return Array.isArray(locator.locations.fragments)
    ? locator.locations.fragments.filter((fragment): fragment is string => typeof fragment === 'string' && fragment.length > 0)
    : [];
}

export function hasExactReadiumAnchor(locator: ReadiumLocatorPayload): boolean {
  return Boolean(
    nonEmptyString(locator.locations.cssSelector)
    || readiumLocatorFragments(locator).length > 0
    || nonEmptyString(locator.text?.highlight)
  );
}

export function isExactReadiumLocatorEnvelope(value: unknown): value is ReadiumLocatorEnvelope {
  const envelope = parseReadiumLocatorEnvelope(value);
  return Boolean(envelope && hasExactReadiumAnchor(envelope.payload));
}

export function publicationFingerprintsMatch(
  expected: PublicationFingerprint | null | undefined,
  actual: PublicationFingerprint | null | undefined
): boolean {
  return Boolean(expected && actual
    && expected.originalFileHash === actual.originalFileHash
    && expected.parser === actual.parser
    && expected.normalization === actual.normalization);
}

/** NFC and collapsed whitespace are comparison-only; user content is never rewritten. */
export function normalizeLocatorText(value: string | undefined): string | undefined {
  const normalized = value?.normalize('NFC').replace(/\s+/gu, ' ').trim();
  return normalized || undefined;
}

function sameTextAnchor(expected: ReadiumLocatorText | undefined, actual: ReadiumLocatorText | undefined): boolean {
  const expectedHighlight = normalizeLocatorText(expected?.highlight);
  const actualHighlight = normalizeLocatorText(actual?.highlight);
  if (!expectedHighlight || !actualHighlight || expectedHighlight !== actualHighlight) return false;
  const expectedBefore = normalizeLocatorText(expected?.before);
  const actualBefore = normalizeLocatorText(actual?.before);
  const expectedAfter = normalizeLocatorText(expected?.after);
  const actualAfter = normalizeLocatorText(actual?.after);
  return (!expectedBefore || expectedBefore === actualBefore)
    && (!expectedAfter || expectedAfter === actualAfter);
}

export function compareExactReadiumLocators(
  expected: ReadiumLocatorEnvelope | null,
  actual: ReadiumLocatorEnvelope | null
): ExactLocatorComparison {
  if (!expected || !actual) return { precision: 'unverified', sameResource: false, reason: 'missing_locator' };
  if (!expected.publication || !actual.publication) {
    return { precision: 'unverified', sameResource: expected.payload.href === actual.payload.href, reason: 'fingerprint_missing' };
  }
  if (!publicationFingerprintsMatch(expected.publication, actual.publication)) {
    return { precision: 'unverified', sameResource: expected.payload.href === actual.payload.href, reason: 'fingerprint_mismatch' };
  }
  if (expected.payload.href !== actual.payload.href) {
    return { precision: 'unverified', sameResource: false, reason: 'different_resource' };
  }
  const expectedSelector = nonEmptyString(expected.payload.locations.cssSelector);
  const actualSelector = nonEmptyString(actual.payload.locations.cssSelector);
  if (expectedSelector && actualSelector && expectedSelector === actualSelector) {
    return { precision: 'exact-block', sameResource: true, reason: 'same_css_selector' };
  }
  const expectedFragments = new Set(readiumLocatorFragments(expected.payload));
  if (readiumLocatorFragments(actual.payload).some((fragment) => expectedFragments.has(fragment))) {
    return { precision: 'exact-block', sameResource: true, reason: 'same_fragment' };
  }
  if (sameTextAnchor(expected.payload.text, actual.payload.text)) {
    return { precision: 'exact-block', sameResource: true, reason: 'same_text_anchor' };
  }
  return { precision: 'unverified', sameResource: true, reason: 'anchor_mismatch' };
}
