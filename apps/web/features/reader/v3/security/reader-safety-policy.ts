import {
  READER_SAFETY_BUDGETS,
  READER_SAFETY_PROFILES,
  READER_SAFETY_RULES,
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
  internalSubset: string | null;
}>;

type EntityDefinition = Readonly<{
  kind: 'internal' | 'external';
  value?: string;
}>;

type EntityTable = ReadonlyMap<string, EntityDefinition>;

function ensureXmlPreparationContract(): void {
  const rule = READER_SAFETY_RULES[READER_SAFETY_RULE_IDS.REFLOWABLE_PREPARE_XML];
  const preparation = READER_SAFETY_PROFILES.reflowable.xmlPreparation;
  if (
    rule.algorithm !== 'PREPARE_XML'
    || rule.action !== 'SANITIZE'
    || rule.errorCode !== null
    || READER_SAFETY_PROFILES.reflowable.externalDtdResolution !== false
    || preparation.declarationAction !== 'REMOVE_PARSER_DEPENDENCY'
    || preparation.externalEntityAction !== 'LITERALIZE_REFERENCE'
    || preparation.recursiveEntityAction !== 'LITERALIZE_REFERENCE'
    || preparation.unknownEntityAction !== 'LITERALIZE_REFERENCE'
    || preparation.parameterEntityAction !== 'LITERALIZE_REFERENCE'
    || preparation.internalTextEntityAction !== 'BOUNDED_EXPANSION'
    || preparation.expansionLimitAction !== 'LITERALIZE_REFERENCE'
  ) {
    readerSafetyPlatformAlgorithmUnsupported(READER_SAFETY_RULE_IDS.REFLOWABLE_PREPARE_XML);
  }
}

const XML_ENTITY_NAME = /^[A-Za-z_:][A-Za-z0-9_.:-]*$/;
const XML_ENTITY_NAME_PREFIX = /^[A-Za-z_:][A-Za-z0-9_.:-]*/;
const XML_NUMERIC_ENTITY = /^#(?:[0-9]+|x[0-9a-f]+)$/i;

function asciiStartsWith(source: string, offset: number, expected: string): boolean {
  if (offset < 0 || offset + expected.length > source.length) return false;
  for (let index = 0; index < expected.length; index += 1) {
    let actual = source.charCodeAt(offset + index);
    if (actual >= 0x41 && actual <= 0x5a) actual += 0x20;
    const wanted = expected.charCodeAt(index);
    if (actual !== (wanted >= 0x41 && wanted <= 0x5a ? wanted + 0x20 : wanted)) return false;
  }
  return true;
}

function isXmlNameCharacter(character: string | undefined): boolean {
  if (!character) return false;
  const code = character.charCodeAt(0);
  return (code >= 0x41 && code <= 0x5a)
    || (code >= 0x61 && code <= 0x7a)
    || (code >= 0x30 && code <= 0x39)
    || character === '_'
    || character === '.'
    || character === ':'
    || character === '-';
}

function skipLexicalRegion(source: string, offset: number): number | null {
  const region = source.startsWith('<!--', offset)
    ? '-->'
    : source.startsWith('<![CDATA[', offset)
      ? ']]>'
      : source.startsWith('<?', offset)
        ? '?>'
        : null;
  if (!region) return null;
  const end = source.indexOf(region, offset + (region === '-->' ? 4 : region === ']]>' ? 9 : 2));
  return end < 0 ? source.length : end + region.length;
}

function findDoctype(source: string): DoctypeDeclaration | null {
  for (let offset = 0; offset < source.length; offset += 1) {
    const skipped = source[offset] === '<' ? skipLexicalRegion(source, offset) : null;
    if (skipped !== null) {
      offset = skipped - 1;
      continue;
    }
    if (
      source[offset] !== '<'
      || !asciiStartsWith(source, offset, '<!doctype')
      || isXmlNameCharacter(source[offset + '<!doctype'.length])
    ) continue;
    let quote: '"' | "'" | null = null;
    let subsetDepth = 0;
    let subsetStart: number | null = null;
    let subsetEnd: number | null = null;
    for (let cursor = offset + 9; cursor < source.length; cursor += 1) {
      const character = source[cursor];
      if (quote) {
        if (character === quote) quote = null;
        continue;
      }
      const skipped = source[cursor] === '<' ? skipLexicalRegion(source, cursor) : null;
      if (skipped !== null) {
        cursor = skipped - 1;
        continue;
      }
      if (character === '"' || character === "'") {
        quote = character;
        continue;
      }
      if (character === '[') {
        if (subsetDepth === 0) subsetStart = cursor + 1;
        subsetDepth += 1;
        continue;
      }
      if (character === ']') {
        if (subsetDepth === 1) subsetEnd = cursor;
        if (subsetDepth > 0) subsetDepth -= 1;
        continue;
      }
      if (character !== '>' || subsetDepth !== 0) continue;
      return {
        start: offset,
        end: cursor + 1,
        internalSubset: subsetStart === null
          ? null
          : source.slice(subsetStart, subsetEnd ?? cursor)
      };
    }
    return null;
  }
  return null;
}

function declarationEnd(source: string, start: number): number | null {
  let quote: '"' | "'" | null = null;
  for (let cursor = start; cursor < source.length; cursor += 1) {
    const character = source[cursor];
    if (quote) {
      if (character === quote) quote = null;
    } else if (character === '"' || character === "'") {
      quote = character;
    } else if (character === '>') {
      return cursor + 1;
    }
  }
  return null;
}

function quotedValue(source: string, offset: number): Readonly<{ value: string; end: number }> | null {
  const quote = source[offset];
  if (quote !== '"' && quote !== "'") return null;
  const end = source.indexOf(quote, offset + 1);
  if (end < 0) return null;
  return { value: source.slice(offset + 1, end), end: end + 1 };
}

function parseEntityDefinitions(subset: string | null): EntityTable {
  if (!subset) return new Map();
  const definitions = new Map<string, EntityDefinition>();
  let offset = 0;
  while (offset < subset.length) {
    const skipped = subset[offset] === '<' ? skipLexicalRegion(subset, offset) : null;
    if (skipped !== null) {
      offset = skipped;
      continue;
    }
    if (
      !asciiStartsWith(subset, offset, '<!entity')
      || isXmlNameCharacter(subset[offset + '<!entity'.length])
    ) {
      const declarationStart = subset[offset] === '<' && subset[offset + 1] === '!'
        && ((subset.charCodeAt(offset + 2) >= 0x41 && subset.charCodeAt(offset + 2) <= 0x5a)
          || (subset.charCodeAt(offset + 2) >= 0x61 && subset.charCodeAt(offset + 2) <= 0x7a));
      if (declarationStart) {
        const end = declarationEnd(subset, offset + 2);
        if (end !== null) {
          offset = end;
          continue;
        }
      }
      offset += 1;
      continue;
    }
    const marker = offset;
    const end = declarationEnd(subset, marker + 8);
    if (end === null) break;
    const declaration = subset.slice(marker + 8, end - 1).trim();
    offset = end;
    if (declaration.startsWith('%')) continue;
    const nameMatch = XML_ENTITY_NAME_PREFIX.exec(declaration);
    if (!nameMatch) continue;
    const name = nameMatch[0];
    let cursor = name.length;
    while (/\s/.test(declaration[cursor] ?? '')) cursor += 1;
    const literal = quotedValue(declaration, cursor);
    if (literal && !declaration.slice(literal.end).trim()) {
      definitions.set(name, { kind: 'internal', value: literal.value });
      continue;
    }
    const external = /^(?:SYSTEM\s+|PUBLIC\s+)/i.test(declaration.slice(cursor));
    if (external) definitions.set(name, { kind: 'external' });
  }
  return definitions;
}

function decodeNumericEntity(value: string): string | null {
  const hexadecimal = /^#x([0-9a-f]+)$/i.exec(value);
  const decimal = /^#([0-9]+)$/.exec(value);
  const digits = hexadecimal?.[1] ?? decimal?.[1];
  if (!digits) return null;
  const codePoint = Number.parseInt(digits, hexadecimal ? 16 : 10);
  if (!Number.isSafeInteger(codePoint) || codePoint <= 0 || codePoint > 0x10ffff) return null;
  return String.fromCodePoint(codePoint);
}

function escapeXmlText(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;');
}

function rewriteReferences(
  source: string,
  definitions: EntityTable,
  maxCharacters: number,
  maxBytesRuleId: ReaderSafetyRuleId
): string {
  const generatedEntities = READER_SAFETY_PROFILES.reflowable.namedEntityCodepoints as Readonly<Record<string, number>>;
  class ExpansionLimitExceeded extends Error {}
  type ExpansionFrame = {
    name: string;
    value: string;
    offset: number;
    outputStart: number;
    outputStartBytes: number;
    literal: string;
  };
  const encoder = new TextEncoder();
  const literalReference = (name: string): string => escapeXmlText(`&${name};`);
  const appendEscaped = (
    value: string,
    append: (chunk: string) => void
  ): void => {
    let start = 0;
    for (let index = 0; index < value.length; index += 1) {
      const replacement = value[index] === '&'
        ? '&amp;'
        : value[index] === '<'
          ? '&lt;'
          : value[index] === '>'
            ? '&gt;'
            : value[index] === '"'
              ? '&quot;'
              : value[index] === "'"
                ? '&apos;'
                : null;
      if (replacement === null) continue;
      if (index > start) append(value.slice(start, index));
      append(replacement);
      start = index + 1;
    }
    if (start < value.length) append(value.slice(start));
  };

  /** Expand custom text entities with an explicit stack to bound JS stack use. */
  const expandEntity = (name: string, expansionMaxBytes: number): string => {
    const definition = definitions.get(name);
    if (!definition || definition.kind === 'external') return literalReference(name);
    let output = '';
    let outputBytes = 0;
    const active = new Set<string>([name]);
    const frames: ExpansionFrame[] = [{
      name,
      value: definition.value ?? '',
      offset: 0,
      outputStart: 0,
      outputStartBytes: 0,
      literal: literalReference(name)
    }];
    const append = (value: string): void => {
      const valueBytes = encoder.encode(value).byteLength;
      if (outputBytes + valueBytes > expansionMaxBytes) throw new ExpansionLimitExceeded();
      output += value;
      outputBytes += valueBytes;
    };
    const literalizeOverflowingFrame = (): string | null => {
      let overflowing = frames.pop();
      while (overflowing) {
        active.delete(overflowing.name);
        output = output.slice(0, overflowing.outputStart);
        outputBytes = overflowing.outputStartBytes;
        const parent = frames[frames.length - 1];
        if (!parent) return overflowing.literal;
        try {
          append(overflowing.literal);
          return null;
        } catch (cause) {
          if (!(cause instanceof ExpansionLimitExceeded)) throw cause;
          overflowing = frames.pop();
        }
      }
      return null;
    };
    for (;;) {
      try {
        while (frames.length > 0) {
          const frame = frames[frames.length - 1];
          if (!frame) return literalReference(name);
          const ampersand = frame.value.indexOf('&', frame.offset);
          if (ampersand < 0) {
            appendEscaped(frame.value.slice(frame.offset), append);
            frames.pop();
            active.delete(frame.name);
            if (frames.length === 0) return output;
            continue;
          }
          appendEscaped(frame.value.slice(frame.offset, ampersand), append);
          const semicolon = frame.value.indexOf(';', ampersand + 1);
          if (semicolon < 0) {
            appendEscaped(frame.value.slice(ampersand), append);
            frame.offset = frame.value.length;
            continue;
          }
          const reference = frame.value.slice(ampersand + 1, semicolon);
          frame.offset = semicolon + 1;
          if (XML_NUMERIC_ENTITY.test(reference)) {
            appendEscaped(decodeNumericEntity(reference) ?? `&${reference};`, append);
            continue;
          }
          const nested = definitions.get(reference);
          if (XML_ENTITY_NAME.test(reference) && nested?.kind === 'internal' && !active.has(reference)) {
            active.add(reference);
            frames.push({
              name: reference,
              value: nested.value ?? '',
              offset: 0,
              outputStart: output.length,
              outputStartBytes: outputBytes,
              literal: literalReference(reference)
            });
            continue;
          }
          const codePoint = Reflect.get(generatedEntities, reference);
          if (typeof codePoint === 'number') {
            appendEscaped(String.fromCodePoint(codePoint), append);
            continue;
          }
          // External, parameter, cyclic, undefined and malformed references
          // stay as escaped text and never become parser markup.
          append(literalReference(reference));
        }
        return literalReference(name);
      } catch (cause) {
        if (!(cause instanceof ExpansionLimitExceeded)) throw cause;
        // Literalize only the reference whose expansion crossed the existing
        // role budget. If its parent cannot retain that literal either, walk up
        // the explicit stack; the rest of the document remains readable.
        const literal = literalizeOverflowingFrame();
        if (literal !== null) return literal;
        // The overflowing child was replaced in its parent. Continue the
        // explicit stack so text after that reference is still processed.
      }
    }
  };

  const sourceTotalBytes = encoder.encode(source).byteLength;
  let sourceBytesConsumed = 0;
  let rewritten = '';
  let rewrittenBytes = 0;
  const appendRewritten = (value: string): void => {
    const valueBytes = encoder.encode(value).byteLength;
    if (rewrittenBytes + valueBytes > maxCharacters) {
      rejectReaderSafety(maxBytesRuleId);
    }
    rewritten += value;
    rewrittenBytes += valueBytes;
  };
  let offset = 0;
  while (offset < source.length) {
    const skipped = source[offset] === '<' ? skipLexicalRegion(source, offset) : null;
    if (skipped !== null) {
      const lexical = source.slice(offset, skipped);
      appendRewritten(lexical);
      sourceBytesConsumed += encoder.encode(lexical).byteLength;
      offset = skipped;
      continue;
    }
    if (source[offset] !== '&') {
      const nextAmpersand = source.indexOf('&', offset);
      const nextTag = source.indexOf('<', offset);
      const nextBoundary = [nextAmpersand, nextTag]
        .filter((boundary) => boundary >= 0)
        .reduce((minimum, boundary) => Math.min(minimum, boundary), source.length);
      if (nextBoundary > offset) {
        const plain = source.slice(offset, nextBoundary);
        appendRewritten(plain);
        sourceBytesConsumed += encoder.encode(plain).byteLength;
        offset = nextBoundary;
        continue;
      }
      // A non-lexical '<' is part of the authored markup. Copy it and batch
      // the text after it on the next iteration so entity scanning never
      // processes ordinary Unicode text one code point at a time.
      appendRewritten('<');
      sourceBytesConsumed += 1;
      offset += 1;
      continue;
    }
    const semicolon = source.indexOf(';', offset + 1);
    if (semicolon < 0) {
      const remainder = source.slice(offset);
      appendRewritten(remainder);
      sourceBytesConsumed += encoder.encode(remainder).byteLength;
      break;
    }
    const name = source.slice(offset + 1, semicolon);
    const rawReference = source.slice(offset, semicolon + 1);
    sourceBytesConsumed += encoder.encode(rawReference).byteLength;
    if (!XML_NUMERIC_ENTITY.test(name) && !XML_ENTITY_NAME.test(name)) {
      appendRewritten(rawReference);
    } else if (XML_NUMERIC_ENTITY.test(name)) {
      appendRewritten(rawReference);
    } else {
      const definition = definitions.get(name);
      if (definition) {
        const remainingSourceBytes = Math.max(0, sourceTotalBytes - sourceBytesConsumed);
        const expansionBudget = Math.max(0, maxCharacters - rewrittenBytes - remainingSourceBytes);
        appendRewritten(expandEntity(name, expansionBudget));
      } else {
        const codePoint = Reflect.get(generatedEntities, name);
        appendRewritten(typeof codePoint === 'number'
          ? `&#${codePoint};`
          : literalReference(name));
      }
    }
    offset = semicolon + 1;
  }
  return rewritten;
}

/**
 * Removes any authored DTD dependency from an in-memory XML copy. Internal
 * literal entities are expanded as text within the existing publication budget;
 * external, cyclic, parameter and unknown references are escaped so the parser
 * renders the original reference literally. Original publication bytes remain
 * untouched and no external resource is resolved. The caller supplies the
 * existing role budget and its generated limit rule.
 */
export function preflightReflowableXml(
  source: string,
  maxBytes: number = READER_SAFETY_BUDGETS.reflowableMarkupMaxBytes,
  maxBytesRuleId: ReaderSafetyRuleId = READER_SAFETY_RULE_IDS.REFLOWABLE_MARKUP_MAX_BYTES
): string {
  ensureXmlPreparationContract();
  const declaration = findDoctype(source);
  const definitions = parseEntityDefinitions(declaration?.internalSubset ?? null);
  const parserSource = declaration
    ? `${source.slice(0, declaration.start)}${source.slice(declaration.end)}`
    : source;
  const prepared = rewriteReferences(parserSource, definitions, maxBytes, maxBytesRuleId);
  if (new TextEncoder().encode(prepared).byteLength > maxBytes) {
    rejectReaderSafety(maxBytesRuleId);
  }
  return prepared;
}

function lowerSet(values: readonly string[]): ReadonlySet<string> {
  return new Set(values.map((value) => value.toLowerCase()));
}

/** Removes authored active markup according to the generated policy profile. */
export function sanitizeAuthoredMarkupWithProfile(
  document: Document,
  profile: typeof READER_SAFETY_PROFILES.reflowable
): void {
  const removedElements = new Set([
    ...profile.sanitizedElements,
    ...profile.svgSanitizedElements
  ].map((value) => value.toLowerCase()));
  const removedAttributes = new Set(profile.sanitizedAttributes.map((value) => value.toLowerCase()));
  const removedPrefixes = profile.sanitizedAttributePrefixes.map((prefix) => prefix.toLowerCase());
  const removedHttpEquiv = new Set(profile.sanitizedMetaHttpEquivValues.map((value) => value.toLowerCase()));
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

/** Removes authored active markup using the bundled generated profile. */
export function sanitizeAuthoredMarkup(document: Document): void {
  sanitizeAuthoredMarkupWithProfile(document, READER_SAFETY_PROFILES.reflowable);
}

export type AuthoredUriPurpose = 'navigation' | 'subresource';
export type AuthoredUriDisposition = 'internal' | 'user-navigation' | 'preserve' | 'remove';

/** Classifies an authored URI; runtime-created URLs never pass here. */
export function authoredUriDispositionWithProfile(
  value: string,
  purpose: AuthoredUriPurpose,
  profile: typeof READER_SAFETY_PROFILES.reflowable
): AuthoredUriDisposition {
  const trimmed = value.trim();
  if (!trimmed || trimmed.startsWith('#')) return 'internal';
  if (trimmed.startsWith('//')) return purpose === 'navigation' ? 'user-navigation' : 'remove';
  const colon = trimmed.indexOf(':');
  const firstBoundary = [trimmed.indexOf('/'), trimmed.indexOf('?'), trimmed.indexOf('#')]
    .filter((index) => index >= 0)
    .reduce((minimum, index) => Math.min(minimum, index), Number.POSITIVE_INFINITY);
  if (colon < 0 || colon > firstBoundary) return 'internal';
  const scheme = trimmed.slice(0, colon).replace(/[\u0000-\u0020]/g, '').toLowerCase();
  if ((profile.blockedAuthorSchemes as readonly string[]).some((candidate) => candidate.toLowerCase() === scheme)) {
    return 'remove';
  }
  if ((profile.remoteSubresourceSchemes as readonly string[]).some((candidate) => candidate.toLowerCase() === scheme)) {
    return purpose === 'navigation' ? 'user-navigation' : 'remove';
  }
  // Navigation is an explicit user action. Its disposition must not become a
  // security rejection merely because a future or uncommon scheme is absent
  // from a membership list. Unknown subresources are retained as inert author
  // values; the explicit network and active-content blacklists above remain.
  return purpose === 'navigation' ? 'user-navigation' : 'preserve';
}

/** Classifies an authored URI using the bundled generated profile. */
export function authoredUriDisposition(value: string, purpose: AuthoredUriPurpose): AuthoredUriDisposition {
  return authoredUriDispositionWithProfile(value, purpose, READER_SAFETY_PROFILES.reflowable);
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
  if (!trimmed) return null;
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
    const disposition = authoredUriDisposition(raw, 'subresource');
    const replacement = disposition === 'internal'
      ? trustedRuntimeCssUrl(await resolveInternalUrl(raw))
      : disposition === 'preserve'
        ? trustedRuntimeCssUrl(raw)
        : null;
    if (replacement) {
      const placeholderIndex = rewrittenImports.push(`@import url("${replacement}");`) - 1;
      withoutImports += `\uE000${placeholderIndex}\uE001`;
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
    const disposition = authoredUriDisposition(raw, 'subresource');
    const replacement = disposition === 'internal'
      ? trustedRuntimeCssUrl(await resolveInternalUrl(raw))
      : disposition === 'preserve'
        ? trustedRuntimeCssUrl(raw)
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

/**
 * Rewrites generated URI descriptors against a supplied profile. The profile
 * argument keeps this adapter self-contained so browser conformance can run
 * the same production function in a real DOM.
 */
export async function rewriteAuthoredDocumentReferencesWithProfile(
  document: Document,
  profile: typeof READER_SAFETY_PROFILES.reflowable,
  classify: (
    value: string,
    purpose: AuthoredUriPurpose
  ) => AuthoredUriDisposition,
  resolveInternalUrl: InternalPublicationUrlResolver,
  sanitizeCss: (
    source: string,
    resolveInternalUrl: InternalPublicationUrlResolver
  ) => Promise<string>,
  unsupported: (ruleId: ReaderSafetyRuleId) => never
): Promise<void> {
  const trustedUri = (value: string | null): string | null => {
    if (!value) return null;
    const trimmed = value.trim();
    return trimmed || null;
  };
  const matching = (element: Element, policyAttribute: string): Attr | null => {
    const expected = policyAttribute.toLowerCase();
    return [...element.attributes].find((attribute) => (
      attribute.name.toLowerCase() === expected
      || (expected === 'xlink:href'
        && attribute.namespaceURI === 'http://www.w3.org/1999/xlink'
        && attribute.localName.toLowerCase() === 'href')
    )) ?? null;
  };
  const matches = (element: Element, policyElements: readonly string[]): boolean => {
    const localName = element.localName.toLowerCase();
    return policyElements.some((candidate) => candidate === '*' || candidate.toLowerCase() === localName);
  };
  const remove = (element: Element, attribute: Attr) => {
    element.removeAttributeNS(attribute.namespaceURI, attribute.localName);
  };
  const rewriteToken = async (value: string): Promise<string | null> => {
    const trimmed = value.trim();
    if (trimmed.startsWith('#')) return trimmed;
    const kind = classify(trimmed, 'subresource');
    if (kind === 'preserve') return trustedUri(trimmed);
    if (kind !== 'internal') return null;
    return trustedUri(await resolveInternalUrl(trimmed));
  };
  const rewriteSrcsetValue = async (value: string): Promise<string | null> => {
    const rewritten: string[] = [];
    for (const component of value.split(',')) {
      const candidate = component.trim();
      if (!candidate) continue;
      const [rawUrl, ...descriptorParts] = candidate.split(/\s+/);
      if (!rawUrl) continue;
      const replacement = await rewriteToken(rawUrl);
      if (replacement) rewritten.push([replacement, ...descriptorParts].join(' '));
    }
    return rewritten.length > 0 ? rewritten.join(', ') : null;
  };
  const rewriteSpaceSeparatedValue = async (value: string): Promise<string | null> => {
    const rewritten = (
      await Promise.all(value.split(/\s+/).filter(Boolean).map((candidate) => rewriteToken(candidate)))
    ).filter((candidate): candidate is string => candidate !== null);
    return rewritten.length > 0 ? rewritten.join(' ') : null;
  };

  for (const element of [...document.querySelectorAll('*')]) {
    for (const policy of profile.uriAttributePolicies) {
      if (!matches(element, policy.elements)) continue;
      const attribute = matching(element, policy.attribute);
      if (!attribute) continue;
      if (policy.purpose === 'ALWAYS_REMOVE') {
        remove(element, attribute);
        continue;
      }
      if (policy.purpose === 'USER_NAVIGATION') {
        if (classify(attribute.value, 'navigation') === 'remove') remove(element, attribute);
        continue;
      }
      let replacement: string | null;
      switch (policy.syntax) {
        case 'CSS':
          replacement = await sanitizeCss(attribute.value, resolveInternalUrl);
          break;
        case 'SRCSET':
          replacement = await rewriteSrcsetValue(attribute.value);
          break;
        case 'SPACE_SEPARATED':
          replacement = await rewriteSpaceSeparatedValue(attribute.value);
          break;
        case 'SCALAR':
          replacement = await rewriteToken(attribute.value);
          break;
        default:
          unsupported(READER_SAFETY_RULE_IDS.REFLOWABLE_SANITIZE_URI);
      }
      if (replacement) element.setAttributeNS(attribute.namespaceURI, attribute.name, replacement);
      else remove(element, attribute);
    }
  }

  const cssTextElements = new Set(profile.cssTextElements.map((value) => value.toLowerCase()));
  for (const element of [...document.querySelectorAll('*')]) {
    if (!cssTextElements.has(element.localName.toLowerCase())) continue;
    element.textContent = await sanitizeCss(element.textContent ?? '', resolveInternalUrl);
  }
}

/**
 * Applies the generated URI/CSS descriptor table to one in-memory authored
 * document. Platforms provide only the publication-local URL resolver.
 */
export async function rewriteAuthoredDocumentReferences(
  document: Document,
  resolveInternalUrl: InternalPublicationUrlResolver
): Promise<void> {
  await rewriteAuthoredDocumentReferencesWithProfile(
    document,
    READER_SAFETY_PROFILES.reflowable,
    authoredUriDisposition,
    resolveInternalUrl,
    sanitizeAuthoredCss,
    readerSafetyPlatformAlgorithmUnsupported
  );
}
