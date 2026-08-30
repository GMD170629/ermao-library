import {
  READER_SAFETY_PROFILES,
  READER_SAFETY_RULE_IDS,
  type ReaderSafetyRuleId
} from '@shuku/reader-core';
export {
  ReaderSafetyImplementationError,
  ReaderSafetyPolicyError,
  isReaderSafetyRuleId,
  readerSafetyEngineAlgorithmUnsupported,
  readerSafetyFailure,
  readerSafetyPlatformAlgorithmUnsupported,
  rejectReaderSafety,
  reviveReaderSafetyError,
  type ReaderSafetyFailure
} from '@shuku/reader-core';
import {
  readerSafetyPlatformAlgorithmUnsupported,
  rejectReaderSafety
} from '@shuku/reader-core';

type DoctypeDeclaration = Readonly<{
  start: number;
  end: number;
  name: string;
  publicId: string;
  systemId: string;
}>;

function findDoctype(source: string): DoctypeDeclaration | null {
  const start = source.search(/<!doctype\b/i);
  if (start < 0) return null;
  let quote: '"' | "'" | null = null;
  for (let cursor = start + 9; cursor < source.length; cursor += 1) {
    const character = source[cursor];
    if (quote) {
      if (character === quote) quote = null;
      continue;
    }
    if (character === '"' || character === "'") {
      quote = character;
      continue;
    }
    if (character === '[') return null;
    if (character !== '>') continue;
    const declaration = source.slice(start, cursor + 1);
    const match = /^<!doctype\s+([A-Za-z_][A-Za-z0-9_.:-]*)\s+public\s+(?:"([^"]*)"|'([^']*)')\s+(?:"([^"]*)"|'([^']*)')\s*>$/i.exec(declaration);
    if (!match) return null;
    return {
      start,
      end: cursor + 1,
      name: (match[1] ?? '').toLowerCase(),
      publicId: match[2] ?? match[3] ?? '',
      systemId: match[4] ?? match[5] ?? ''
    };
  }
  return null;
}

/**
 * Applies the generated XML declaration policy before invoking the browser XML
 * parser. The allowlisted declaration is removed from the in-memory copy so the
 * browser has no DTD resolution surface; original publication bytes are untouched.
 */
export function preflightReflowableXml(
  source: string,
  rejectRuleId: ReaderSafetyRuleId
): string {
  if (/<!entity\b/i.test(source)) rejectReaderSafety(rejectRuleId);
  const hasDoctype = /<!doctype\b/i.test(source);
  let parserSource = source;
  if (hasDoctype) {
    const declaration = findDoctype(source);
    if (!declaration || /<!doctype\b/i.test(source.slice(declaration.end))) {
      rejectReaderSafety(rejectRuleId);
    }
    const allowed = READER_SAFETY_PROFILES.reflowable.safeDoctypes.some((candidate) => (
      candidate.name === declaration.name
      && candidate.publicId === declaration.publicId
      && candidate.systemId === declaration.systemId
    ));
    if (!allowed) rejectReaderSafety(rejectRuleId);
    parserSource = `${source.slice(0, declaration.start)}${source.slice(declaration.end)}`;
  }
  return rewriteGeneratedNamedEntities(parserSource, rejectRuleId);
}

function rewriteGeneratedNamedEntities(
  source: string,
  rejectRuleId: ReaderSafetyRuleId
): string {
  const entities = READER_SAFETY_PROFILES.reflowable.namedEntityCodepoints;
  const rewriteMarkup = (markup: string): string => markup.replace(
    /&([A-Za-z][A-Za-z0-9]+);/g,
    (_match, name: string) => {
      if (!Object.prototype.hasOwnProperty.call(entities, name)) {
        rejectReaderSafety(rejectRuleId);
      }
      return `&#${entities[name as keyof typeof entities]};`;
    }
  );
  const nonMarkup = /<!--[\s\S]*?-->|<!\[CDATA\[[\s\S]*?\]\]>|<\?[\s\S]*?\?>/g;
  let rewritten = '';
  let offset = 0;
  for (const match of source.matchAll(nonMarkup)) {
    const index = match.index;
    if (index === undefined) continue;
    rewritten += rewriteMarkup(source.slice(offset, index));
    rewritten += match[0];
    offset = index + match[0].length;
  }
  return rewritten + rewriteMarkup(source.slice(offset));
}

function lowerSet(values: readonly string[]): ReadonlySet<string> {
  return new Set(values.map((value) => value.toLowerCase()));
}

/** Removes authored active markup according to the generated policy profile. */
export function sanitizeAuthoredMarkup(document: Document): void {
  const profile = READER_SAFETY_PROFILES.reflowable;
  const removedElements = lowerSet([
    ...profile.sanitizedElements,
    ...profile.svgSanitizedElements
  ]);
  const removedAttributes = lowerSet(profile.sanitizedAttributes);
  const removedPrefixes = profile.sanitizedAttributePrefixes.map((prefix) => prefix.toLowerCase());
  const removedHttpEquiv = lowerSet(profile.sanitizedMetaHttpEquivValues);
  for (const element of [...document.querySelectorAll('*')]) {
    if (removedElements.has(element.localName.toLowerCase())) {
      element.remove();
      continue;
    }
    if (element.localName.toLowerCase() === 'meta') {
      const httpEquiv = element.getAttribute('http-equiv')?.trim().toLowerCase();
      if (httpEquiv && removedHttpEquiv.has(httpEquiv)) {
        element.remove();
        continue;
      }
    }
    for (const attribute of [...element.attributes]) {
      const name = attribute.name.toLowerCase();
      if (removedAttributes.has(name) || removedPrefixes.some((prefix) => name.startsWith(prefix))) {
        element.removeAttributeNS(attribute.namespaceURI, attribute.localName);
      }
    }
  }
}

export type AuthoredUriPurpose = 'navigation' | 'subresource';
export type AuthoredUriDisposition = 'internal' | 'user-navigation' | 'remove';

/** Classifies an authored URI; runtime-created blob/data URLs never pass here. */
export function authoredUriDisposition(value: string, purpose: AuthoredUriPurpose): AuthoredUriDisposition {
  const trimmed = value.trim();
  if (!trimmed || trimmed.startsWith('#')) return 'internal';
  if (trimmed.startsWith('//')) return 'remove';
  const colon = trimmed.indexOf(':');
  const firstBoundary = [trimmed.indexOf('/'), trimmed.indexOf('?'), trimmed.indexOf('#')]
    .filter((index) => index >= 0)
    .reduce((minimum, index) => Math.min(minimum, index), Number.POSITIVE_INFINITY);
  if (colon < 0 || colon > firstBoundary) return 'internal';
  const scheme = trimmed.slice(0, colon).replace(/[\u0000-\u0020]/g, '').toLowerCase();
  const profile = READER_SAFETY_PROFILES.reflowable;
  if (purpose === 'navigation' && (profile.userNavigationSchemes as readonly string[]).includes(scheme)) {
    return 'user-navigation';
  }
  return 'remove';
}

function decodedCssForDetection(source: string): string {
  return source.replace(/\\([0-9a-f]{1,6})\s?|\\(.)/gi, (_match, hexadecimal: string | undefined, escaped: string | undefined) => {
    if (hexadecimal) {
      const codePoint = Number.parseInt(hexadecimal, 16);
      return Number.isSafeInteger(codePoint) && codePoint > 0 && codePoint <= 0x10ffff
        ? String.fromCodePoint(codePoint)
        : '';
    }
    return escaped ?? '';
  });
}

function hasActiveCssConstruct(source: string): boolean {
  const normalized = decodedCssForDetection(source).toLowerCase();
  for (const construct of READER_SAFETY_PROFILES.reflowable.cssSanitizedConstructs) {
    switch (construct) {
      case 'REMOTE_IMPORT':
      case 'REMOTE_URL':
        break;
      case 'EXPRESSION':
        if (/expression\s*\(/i.test(normalized)) return true;
        break;
      case 'BEHAVIOR':
        if (/behavior\s*:/i.test(normalized)) return true;
        break;
      case 'MOZ_BINDING':
        if (/-moz-binding\s*:/i.test(normalized)) return true;
        break;
      default: {
        const exhaustive: never = construct;
        void exhaustive;
        readerSafetyPlatformAlgorithmUnsupported(READER_SAFETY_RULE_IDS.REFLOWABLE_SANITIZE_CSS);
      }
    }
  }
  return false;
}

function removeActiveCssDeclarations(source: string): string {
  let sanitized = source;
  for (const construct of READER_SAFETY_PROFILES.reflowable.cssSanitizedConstructs) {
    switch (construct) {
      case 'REMOTE_IMPORT':
      case 'REMOTE_URL':
        break;
      case 'EXPRESSION':
        sanitized = sanitized.replace(
          /(^|[;{])\s*[-A-Za-z_][\w-]*\s*:[^;{}]*expression\s*\([^;{}]*(?:;|(?=}))/gi,
          (_match, prefix: string) => prefix
        );
        break;
      case 'BEHAVIOR':
        sanitized = sanitized.replace(
          /(^|[;{])\s*behavior\s*:[^;{}]*(?:;|(?=}))/gi,
          (_match, prefix: string) => prefix
        );
        break;
      case 'MOZ_BINDING':
        sanitized = sanitized.replace(
          /(^|[;{])\s*-moz-binding\s*:[^;{}]*(?:;|(?=}))/gi,
          (_match, prefix: string) => prefix
        );
        break;
      default: {
        const exhaustive: never = construct;
        void exhaustive;
        readerSafetyPlatformAlgorithmUnsupported(READER_SAFETY_RULE_IDS.REFLOWABLE_SANITIZE_CSS);
      }
    }
  }
  if (hasActiveCssConstruct(sanitized)) return '';
  let previous: string;
  do {
    previous = sanitized;
    sanitized = sanitized.replace(/[^{}]+\{\s*}/g, '');
  } while (sanitized !== previous);
  return sanitized;
}

function trustedRuntimeCssUrl(value: string | null): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  const colon = trimmed.indexOf(':');
  if (colon <= 0) return null;
  const scheme = trimmed.slice(0, colon).toLowerCase();
  if (!(READER_SAFETY_PROFILES.reflowable.trustedRuntimeSchemes as readonly string[]).includes(scheme)) {
    return null;
  }
  return trimmed.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/[\r\n\f]/g, '');
}

export async function sanitizeAuthoredCss(
  source: string,
  resolveInternalUrl: (value: string) => Promise<string | null>
): Promise<string> {
  const declarationSafeSource = removeActiveCssDeclarations(source);
  if (!declarationSafeSource) return '';
  const importExpression = /@import\s+(?:url\(\s*)?(?:(["'])(.*?)\1|([^\s;)'\"]+))\s*\)?[^;]*;/gi;
  const rewrittenImports: string[] = [];
  let withoutImports = '';
  let importOffset = 0;
  for (const match of declarationSafeSource.matchAll(importExpression)) {
    const index = match.index;
    if (index === undefined) continue;
    withoutImports += declarationSafeSource.slice(importOffset, index);
    const raw = match[2] ?? match[3] ?? '';
    if (authoredUriDisposition(raw, 'subresource') === 'internal') {
      const replacement = trustedRuntimeCssUrl(await resolveInternalUrl(raw));
      if (replacement) {
        const placeholderIndex = rewrittenImports.push(`@import url("${replacement}");`) - 1;
        withoutImports += `\uE000${placeholderIndex}\uE001`;
      }
    }
    importOffset = index + match[0].length;
  }
  withoutImports += declarationSafeSource.slice(importOffset);

  const urlExpression = /url\(\s*(?:(["'])(.*?)\1|((?:[^()]|\([^()]*\))*))\s*\)/gi;
  let rewritten = '';
  let offset = 0;
  for (const match of withoutImports.matchAll(urlExpression)) {
    const index = match.index;
    if (index === undefined) continue;
    rewritten += withoutImports.slice(offset, index);
    const raw = (match[2] ?? match[3] ?? '').trim();
    const replacement = authoredUriDisposition(raw, 'subresource') === 'internal'
      ? trustedRuntimeCssUrl(await resolveInternalUrl(raw))
      : null;
    rewritten += replacement ? `url("${replacement}")` : 'url("")';
    offset = index + match[0].length;
  }
  rewritten += withoutImports.slice(offset);
  rewritten = rewritten.replace(/\uE000(\d+)\uE001/g, (_match, rawIndex: string) => (
    rewrittenImports[Number(rawIndex)] ?? ''
  ));
  const residual = decodedCssForDetection(rewritten)
    .replace(/@import\s+url\("[^"]*"\)\s*;/gi, '')
    .replace(/url\("[^"]*"\)/gi, '');
  if (/(?:@import|url\s*\()/i.test(residual) || hasActiveCssConstruct(rewritten)) return '';
  let previous: string;
  do {
    previous = rewritten;
    rewritten = rewritten.replace(/[^{}]+\{\s*}/g, '');
  } while (rewritten !== previous);
  return rewritten;
}

type InternalPublicationUrlResolver = (value: string) => Promise<string | null>;

function matchingAttribute(element: Element, policyAttribute: string): Attr | null {
  const expected = policyAttribute.toLowerCase();
  return [...element.attributes].find((attribute) => (
    attribute.name.toLowerCase() === expected
    || (!expected.includes(':') && attribute.localName.toLowerCase() === expected)
  )) ?? null;
}

function matchesPolicyElement(element: Element, policyElements: readonly string[]): boolean {
  const localName = element.localName.toLowerCase();
  return policyElements.some((candidate) => candidate === '*' || candidate.toLowerCase() === localName);
}

function removeAttribute(element: Element, attribute: Attr): void {
  element.removeAttributeNS(attribute.namespaceURI, attribute.localName);
}

function trustedRuntimeUri(value: string | null): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  const colon = trimmed.indexOf(':');
  if (colon <= 0) return null;
  const scheme = trimmed.slice(0, colon).toLowerCase();
  return (READER_SAFETY_PROFILES.reflowable.trustedRuntimeSchemes as readonly string[]).includes(scheme)
    ? trimmed
    : null;
}

async function rewriteSubresourceToken(
  value: string,
  resolveInternalUrl: InternalPublicationUrlResolver
): Promise<string | null> {
  const trimmed = value.trim();
  if (trimmed.startsWith('#')) return trimmed;
  if (authoredUriDisposition(trimmed, 'subresource') !== 'internal') return null;
  return trustedRuntimeUri(await resolveInternalUrl(trimmed));
}

async function rewriteSrcset(
  value: string,
  resolveInternalUrl: InternalPublicationUrlResolver
): Promise<string | null> {
  const rewritten: string[] = [];
  for (const component of value.split(',')) {
    const candidate = component.trim();
    if (!candidate) continue;
    const [rawUrl, ...descriptor] = candidate.split(/\s+/);
    if (!rawUrl) continue;
    const replacement = await rewriteSubresourceToken(rawUrl, resolveInternalUrl);
    if (replacement) rewritten.push([replacement, ...descriptor].join(' '));
  }
  return rewritten.length > 0 ? rewritten.join(', ') : null;
}

async function rewriteSpaceSeparated(
  value: string,
  resolveInternalUrl: InternalPublicationUrlResolver
): Promise<string | null> {
  const rewritten = (
    await Promise.all(value.split(/\s+/).filter(Boolean).map((candidate) => (
      rewriteSubresourceToken(candidate, resolveInternalUrl)
    )))
  ).filter((candidate): candidate is string => candidate !== null);
  return rewritten.length > 0 ? rewritten.join(' ') : null;
}

/**
 * Applies the generated URI/CSS descriptor table to one in-memory authored
 * document. Platforms provide only the publication-local URL resolver.
 */
export async function rewriteAuthoredDocumentReferences(
  document: Document,
  resolveInternalUrl: InternalPublicationUrlResolver
): Promise<void> {
  const profile = READER_SAFETY_PROFILES.reflowable;
  for (const element of [...document.querySelectorAll('*')]) {
    for (const policy of profile.uriAttributePolicies) {
      if (!matchesPolicyElement(element, policy.elements)) continue;
      const attribute = matchingAttribute(element, policy.attribute);
      if (!attribute) continue;
      if (policy.purpose === 'ALWAYS_REMOVE') {
        removeAttribute(element, attribute);
        continue;
      }
      if (policy.purpose === 'USER_NAVIGATION') {
        if (authoredUriDisposition(attribute.value, 'navigation') === 'remove') {
          removeAttribute(element, attribute);
        }
        continue;
      }

      let replacement: string | null;
      switch (policy.syntax) {
        case 'CSS':
          replacement = await sanitizeAuthoredCss(attribute.value, resolveInternalUrl);
          break;
        case 'SRCSET':
          replacement = await rewriteSrcset(attribute.value, resolveInternalUrl);
          break;
        case 'SPACE_SEPARATED':
          replacement = await rewriteSpaceSeparated(attribute.value, resolveInternalUrl);
          break;
        case 'SCALAR':
          replacement = await rewriteSubresourceToken(attribute.value, resolveInternalUrl);
          break;
        default:
          readerSafetyPlatformAlgorithmUnsupported(READER_SAFETY_RULE_IDS.REFLOWABLE_SANITIZE_URI);
      }
      if (replacement) {
        element.setAttributeNS(attribute.namespaceURI, attribute.name, replacement);
      } else {
        removeAttribute(element, attribute);
      }
    }
  }

  const cssTextElements = lowerSet(profile.cssTextElements);
  for (const element of [...document.querySelectorAll('*')]) {
    if (!cssTextElements.has(element.localName.toLowerCase())) continue;
    element.textContent = await sanitizeAuthoredCss(
      element.textContent ?? '',
      resolveInternalUrl
    );
  }
}
