import {
  READER_SAFETY_BUDGETS,
  READER_SAFETY_PROFILES,
  READER_SAFETY_RULE_IDS,
  type ReaderSafetyRuleId
} from '@shuku/reader-core';
import { rejectReaderSafety } from '../security/reader-safety-policy';

export type StrictFb2ChapterSource = Readonly<{
  title: string | null;
  paragraphs: readonly string[];
  text: string;
}>;

export type StrictFb2Document = Readonly<{
  title: string | null;
  language: string | null;
  chapters: readonly StrictFb2ChapterSource[];
  blockedResources: readonly Readonly<{
    id: string | null;
    ruleId: ReaderSafetyRuleId;
  }>[];
}>;

type ParserLimits = Readonly<{
  maxDepth: number;
  maxNodes: number;
  maxTextChars: number;
}>;

type ImageLimits = Readonly<{
  maxEncodedBytes: number;
  maxDecodedBytes: number;
  maxDecodedTotalBytes: number;
}>;

const DEFAULT_LIMITS: ParserLimits = {
  maxDepth: READER_SAFETY_BUDGETS.fb2MaxDepth,
  maxNodes: READER_SAFETY_BUDGETS.fb2MaxNodes,
  maxTextChars: READER_SAFETY_BUDGETS.fb2TextMaxCharacters
};

const DEFAULT_IMAGE_LIMITS: ImageLimits = {
  maxEncodedBytes: READER_SAFETY_BUDGETS.fb2EncodedImageMaxBytes,
  maxDecodedBytes: READER_SAFETY_BUDGETS.fb2DecodedImageMaxBytes,
  maxDecodedTotalBytes: READER_SAFETY_BUDGETS.fb2DecodedImagesTotalMaxBytes
};

type SectionAccumulator = {
  titleParts: string[];
  paragraphs: string[];
  textParts: string[];
};

type BodyAccumulator = {
  loose: SectionAccumulator;
  sections: SectionAccumulator[];
  sectionDepth: number;
  currentSection: SectionAccumulator | null;
};

type Capture = {
  depth: number;
  parts: string[];
  finish(value: string): void;
};

type ParsedAttribute = Readonly<{ qName: string; value: string }>;
type QualifiedName = Readonly<{ prefix: string | null; local: string }>;

type BinaryAccumulator = {
  depth: number;
  id: string | null;
  mediaType: string | null;
  encodedParts: string[];
};

const XML_NAMESPACE = 'http://www.w3.org/XML/1998/namespace';
const XMLNS_NAMESPACE = 'http://www.w3.org/2000/xmlns/';

function normalized(parts: readonly string[]): string {
  return parts.join(' ').replace(/\s+/g, ' ').trim();
}

function validXmlCodePoint(codePoint: number): boolean {
  return codePoint === 0x09 || codePoint === 0x0a || codePoint === 0x0d
    || (codePoint >= 0x20 && codePoint <= 0xd7ff)
    || (codePoint >= 0xe000 && codePoint <= 0xfffd)
    || (codePoint >= 0x10000 && codePoint <= 0x10ffff);
}

function decodeXmlEntities(value: string): string {
  let decoded = '';
  let offset = 0;
  while (offset < value.length) {
    const ampersand = value.indexOf('&', offset);
    if (ampersand < 0) return decoded + value.slice(offset);
    decoded += value.slice(offset, ampersand);
    const semicolon = value.indexOf(';', ampersand + 1);
    if (semicolon < 0 || semicolon - ampersand > 32) throw new Error('PUBLICATION_MARKUP_INVALID');
    const entity = value.slice(ampersand + 1, semicolon);
    const named: Readonly<Record<string, string>> = {
      amp: '&', lt: '<', gt: '>', quot: '"', apos: "'"
    };
    if (entity in named) {
      decoded += named[entity] ?? '';
    } else {
      const decimal = /^#([0-9]+)$/.exec(entity);
      const hexadecimal = /^#x([0-9a-f]+)$/i.exec(entity);
      const digits = decimal?.[1] ?? hexadecimal?.[1];
      if (!digits) throw new Error('PUBLICATION_MARKUP_INVALID');
      const codePoint = Number.parseInt(digits, decimal ? 10 : 16);
      if (!Number.isSafeInteger(codePoint) || !validXmlCodePoint(codePoint)) {
        throw new Error('PUBLICATION_MARKUP_INVALID');
      }
      decoded += String.fromCodePoint(codePoint);
    }
    offset = semicolon + 1;
  }
  return decoded;
}

function localName(qName: string): string {
  return qName.split(':').at(-1) ?? qName;
}

function qualifiedName(qName: string): QualifiedName {
  const parts = qName.split(':');
  if (parts.length > 2 || parts.some((part) => !/^[A-Za-z_][A-Za-z0-9_.-]*$/.test(part))) {
    throw new Error('PUBLICATION_MARKUP_INVALID');
  }
  return parts.length === 2
    ? { prefix: parts[0] ?? null, local: parts[1] ?? '' }
    : { prefix: null, local: parts[0] ?? '' };
}

function parseStartTag(raw: string): Readonly<{
  qName: string;
  selfClosing: boolean;
  attributes: readonly ParsedAttribute[];
}> {
  let source = raw.trim();
  const selfClosing = source.endsWith('/');
  if (selfClosing) source = source.slice(0, -1).trimEnd();
  const nameMatch = /^[A-Za-z_][A-Za-z0-9_.:-]*/.exec(source);
  if (!nameMatch) throw new Error('PUBLICATION_MARKUP_INVALID');
  const qName = nameMatch[0];
  qualifiedName(qName);
  let offset = qName.length;
  const attributeNames = new Set<string>();
  const attributes: ParsedAttribute[] = [];
  while (offset < source.length) {
    const whitespace = /^[\t\n\r ]+/.exec(source.slice(offset));
    if (!whitespace) throw new Error('PUBLICATION_MARKUP_INVALID');
    offset += whitespace[0].length;
    if (offset >= source.length) break;
    const attributeMatch = /^[A-Za-z_][A-Za-z0-9_.:-]*/.exec(source.slice(offset));
    if (!attributeMatch) throw new Error('PUBLICATION_MARKUP_INVALID');
    const attributeName = attributeMatch[0];
    qualifiedName(attributeName);
    if (attributeNames.has(attributeName)) throw new Error('PUBLICATION_MARKUP_INVALID');
    attributeNames.add(attributeName);
    offset += attributeName.length;
    offset += /^[\t\n\r ]*/.exec(source.slice(offset))?.[0].length ?? 0;
    if (source[offset] !== '=') throw new Error('PUBLICATION_MARKUP_INVALID');
    offset += 1;
    offset += /^[\t\n\r ]*/.exec(source.slice(offset))?.[0].length ?? 0;
    const quote = source[offset];
    if (quote !== '"' && quote !== "'") throw new Error('PUBLICATION_MARKUP_INVALID');
    const end = source.indexOf(quote, offset + 1);
    if (end < 0) throw new Error('PUBLICATION_MARKUP_INVALID');
    const attributeValue = source.slice(offset + 1, end);
    if (attributeValue.includes('<')) throw new Error('PUBLICATION_MARKUP_INVALID');
    attributes.push({ qName: attributeName, value: decodeXmlEntities(attributeValue) });
    offset = end + 1;
  }
  return { qName, selfClosing, attributes };
}

function namespacesForElement(
  parent: ReadonlyMap<string, string> | undefined,
  elementQName: string,
  attributes: readonly ParsedAttribute[]
): ReadonlyMap<string, string> {
  const namespaces = new Map(parent ?? [['xml', XML_NAMESPACE]]);
  for (const attribute of attributes) {
    const name = qualifiedName(attribute.qName);
    const declaration = attribute.qName === 'xmlns'
      ? ''
      : name.prefix === 'xmlns'
        ? name.local
        : null;
    if (declaration === null) continue;
    const uri = attribute.value;
    if (uri !== uri.trim() || declaration === 'xmlns' || uri === XMLNS_NAMESPACE) {
      throw new Error('PUBLICATION_MARKUP_INVALID');
    }
    if (declaration === 'xml') {
      if (uri !== XML_NAMESPACE) throw new Error('PUBLICATION_MARKUP_INVALID');
    } else {
      if (uri === XML_NAMESPACE || declaration && !uri) throw new Error('PUBLICATION_MARKUP_INVALID');
    }
    namespaces.set(declaration, uri);
  }

  const elementName = qualifiedName(elementQName);
  if (elementName.prefix === 'xmlns'
    || elementName.prefix && !namespaces.get(elementName.prefix)) {
    throw new Error('PUBLICATION_MARKUP_INVALID');
  }

  const expandedAttributes = new Set<string>();
  for (const attribute of attributes) {
    const name = qualifiedName(attribute.qName);
    if (attribute.qName === 'xmlns' || name.prefix === 'xmlns') continue;
    const namespace = name.prefix ? namespaces.get(name.prefix) : '';
    if (name.prefix && !namespace) throw new Error('PUBLICATION_MARKUP_INVALID');
    const expandedName = `${namespace ?? ''}\u0000${name.local}`;
    if (expandedAttributes.has(expandedName)) throw new Error('PUBLICATION_MARKUP_INVALID');
    expandedAttributes.add(expandedName);
  }
  return namespaces;
}

function materialize(accumulator: SectionAccumulator): StrictFb2ChapterSource | null {
  const text = normalized(accumulator.textParts);
  if (!text) return null;
  const title = normalized(accumulator.titleParts) || null;
  return { title, paragraphs: accumulator.paragraphs, text };
}

function decodedBase64Length(value: string): number | null {
  const compact = value.replace(/[\t\n\r ]+/g, '');
  if (!compact || compact.length % 4 !== 0 || !/^[A-Za-z0-9+/]*={0,2}$/.test(compact)) {
    return null;
  }
  const padding = compact.endsWith('==') ? 2 : compact.endsWith('=') ? 1 : 0;
  return (compact.length / 4) * 3 - padding;
}

export function parseStrictFb2(
  source: string,
  limits: ParserLimits = DEFAULT_LIMITS,
  imageLimits: ImageLimits = DEFAULT_IMAGE_LIMITS
): StrictFb2Document {
  if (/<!DOCTYPE|<!ENTITY/i.test(source)) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.REFLOWABLE_REJECT_XML_ENTITY);
  }
  if (limits.maxDepth < 1 || limits.maxNodes < 1 || limits.maxTextChars < 1) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.FB2_STRUCTURE_BUDGET);
  }

  const stack: Array<Readonly<{
    qName: string;
    local: string;
    namespaces: ReadonlyMap<string, string>;
  }>> = [];
  const captures: Capture[] = [];
  const bodies: BodyAccumulator[] = [];
  let currentBody: BodyAccumulator | null = null;
  let bookTitle: string | null = null;
  let language: string | null = null;
  let rootSeen = false;
  let rootClosed = false;
  let nodeCount = 0;
  let textChars = 0;
  let decodedImagesTotalBytes = 0;
  let currentBinary: BinaryAccumulator | null = null;
  const blockedResources: Array<Readonly<{
    id: string | null;
    ruleId: ReaderSafetyRuleId;
  }>> = [];
  let offset = 0;

  const addText = (raw: string, cdata = false) => {
    if (!raw) return;
    if (currentBinary) {
      currentBinary.encodedParts.push(raw);
      return;
    }
    const value = cdata ? raw : decodeXmlEntities(raw);
    if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value)) {
      throw new Error('PUBLICATION_MARKUP_INVALID');
    }
    if (!rootSeen || rootClosed) {
      if (value.trim()) throw new Error('PUBLICATION_MARKUP_INVALID');
      return;
    }
    textChars += value.length;
    if (textChars > limits.maxTextChars) {
      rejectReaderSafety(READER_SAFETY_RULE_IDS.FB2_STRUCTURE_BUDGET);
    }
    for (const capture of captures) capture.parts.push(value);
    const target = currentBody?.currentSection ?? currentBody?.loose;
    target?.textParts.push(value);
  };

  const finishCaptures = (depth: number) => {
    for (let index = captures.length - 1; index >= 0; index -= 1) {
      const capture = captures[index];
      if (capture?.depth !== depth) continue;
      capture.finish(normalized(capture.parts));
      captures.splice(index, 1);
    }
  };

  const openElement = (
    qName: string,
    selfClosing: boolean,
    attributes: readonly ParsedAttribute[]
  ) => {
    const local = localName(qName);
    if (rootClosed) throw new Error('PUBLICATION_MARKUP_INVALID');
    if (!rootSeen) {
      if (local !== 'FictionBook') throw new Error('PUBLICATION_STRUCTURE_INVALID');
      rootSeen = true;
    }
    nodeCount += 1;
    if (nodeCount > limits.maxNodes) rejectReaderSafety(READER_SAFETY_RULE_IDS.FB2_STRUCTURE_BUDGET);
    const namespaces = namespacesForElement(stack.at(-1)?.namespaces, qName, attributes);
    stack.push({ qName, local, namespaces });
    if (stack.length > limits.maxDepth) rejectReaderSafety(READER_SAFETY_RULE_IDS.FB2_STRUCTURE_BUDGET);
    const depth = stack.length;

    if (currentBinary && local !== 'binary') {
      throw new Error('PUBLICATION_MARKUP_INVALID');
    }
    if (local === 'binary') {
      if (currentBinary) throw new Error('PUBLICATION_MARKUP_INVALID');
      const attributeValue = (name: string): string | null => attributes.find(
        (attribute) => localName(attribute.qName).toLowerCase() === name
      )?.value.trim() || null;
      currentBinary = {
        depth,
        id: attributeValue('id'),
        mediaType: attributeValue('content-type')?.toLowerCase() ?? null,
        encodedParts: []
      };
    }

    if (local === 'body') {
      if (currentBody) throw new Error('PUBLICATION_MARKUP_INVALID');
      currentBody = {
        loose: { titleParts: [], paragraphs: [], textParts: [] },
        sections: [],
        sectionDepth: 0,
        currentSection: null
      };
    } else if (local === 'section' && currentBody) {
      if (currentBody.sectionDepth === 0) {
        currentBody.currentSection = { titleParts: [], paragraphs: [], textParts: [] };
      }
      currentBody.sectionDepth += 1;
    }

    if (local === 'book-title' && bookTitle === null) {
      captures.push({ depth, parts: [], finish: (value) => { bookTitle = value || null; } });
    } else if (local === 'lang' && language === null) {
      captures.push({ depth, parts: [], finish: (value) => { language = value || null; } });
    } else if (local === 'title' && currentBody) {
      const target = currentBody.currentSection ?? currentBody.loose;
      if (target.titleParts.length === 0) {
        captures.push({ depth, parts: [], finish: (value) => { if (value) target.titleParts.push(value); } });
      }
    } else if (local === 'p' && currentBody) {
      const target = currentBody.currentSection ?? currentBody.loose;
      captures.push({ depth, parts: [], finish: (value) => { if (value) target.paragraphs.push(value); } });
    }

    if (selfClosing) closeElement(qName);
  };

  const closeElement = (qName: string) => {
    const current = stack.at(-1);
    if (!current || current.qName !== qName) throw new Error('PUBLICATION_MARKUP_INVALID');
    finishCaptures(stack.length);
    if (current.local === 'binary') {
      if (!currentBinary || currentBinary.depth !== stack.length) {
        throw new Error('PUBLICATION_MARKUP_INVALID');
      }
      const encoded = currentBinary.encodedParts.join('');
      const decodedBytes = decodedBase64Length(encoded);
      const supportedMediaType = currentBinary.mediaType !== null
        && Object.prototype.hasOwnProperty.call(
          READER_SAFETY_PROFILES.reflowable.embeddedImageExtensionsByMimeType,
          currentBinary.mediaType
        );
      const exceedsBudget = encoded.length > imageLimits.maxEncodedBytes
        || decodedBytes === null
        || decodedBytes > imageLimits.maxDecodedBytes
        || decodedImagesTotalBytes + decodedBytes > imageLimits.maxDecodedTotalBytes
        || !supportedMediaType;
      if (exceedsBudget) {
        blockedResources.push({
          id: currentBinary.id,
          ruleId: READER_SAFETY_RULE_IDS.FB2_IMAGE_BUDGET
        });
      } else {
        decodedImagesTotalBytes += decodedBytes;
      }
      currentBinary = null;
    } else if (current.local === 'section' && currentBody) {
      if (currentBody.sectionDepth <= 0) throw new Error('PUBLICATION_MARKUP_INVALID');
      currentBody.sectionDepth -= 1;
      if (currentBody.sectionDepth === 0) {
        const section = currentBody.currentSection;
        if (!section) throw new Error('PUBLICATION_MARKUP_INVALID');
        currentBody.sections.push(section);
        currentBody.currentSection = null;
      }
    } else if (current.local === 'body') {
      if (!currentBody || currentBody.sectionDepth !== 0) throw new Error('PUBLICATION_MARKUP_INVALID');
      bodies.push(currentBody);
      currentBody = null;
    }
    stack.pop();
    if (stack.length === 0) rootClosed = true;
  };

  while (offset < source.length) {
    const opening = source.indexOf('<', offset);
    if (opening < 0) {
      addText(source.slice(offset));
      offset = source.length;
      break;
    }
    addText(source.slice(offset, opening));
    if (source.startsWith('<!--', opening)) {
      const end = source.indexOf('-->', opening + 4);
      if (end < 0 || source.slice(opening + 4, end).includes('--')) throw new Error('PUBLICATION_MARKUP_INVALID');
      offset = end + 3;
      continue;
    }
    if (source.startsWith('<![CDATA[', opening)) {
      const end = source.indexOf(']]>', opening + 9);
      if (end < 0) throw new Error('PUBLICATION_MARKUP_INVALID');
      addText(source.slice(opening + 9, end), true);
      offset = end + 3;
      continue;
    }
    if (source.startsWith('<?', opening)) {
      const end = source.indexOf('?>', opening + 2);
      if (end < 0 || rootSeen || !/^<\?xml(?:\s|\?)/i.test(source.slice(opening, end + 2))) {
        throw new Error('PUBLICATION_MARKUP_INVALID');
      }
      offset = end + 2;
      continue;
    }
    if (source.startsWith('<!', opening)) {
      rejectReaderSafety(READER_SAFETY_RULE_IDS.REFLOWABLE_REJECT_XML_ENTITY);
    }
    const end = source.indexOf('>', opening + 1);
    if (end < 0) throw new Error('PUBLICATION_MARKUP_INVALID');
    const raw = source.slice(opening + 1, end);
    if (raw.startsWith('/')) {
      const closingName = raw.slice(1).trim();
      if (!/^[A-Za-z_][A-Za-z0-9_.:-]*$/.test(closingName)) throw new Error('PUBLICATION_MARKUP_INVALID');
      closeElement(closingName);
    } else {
      const tag = parseStartTag(raw);
      openElement(tag.qName, tag.selfClosing, tag.attributes);
    }
    offset = end + 1;
  }

  if (!rootSeen || !rootClosed || stack.length > 0 || currentBody || captures.length > 0 || bodies.length === 0) {
    throw new Error('PUBLICATION_STRUCTURE_INVALID');
  }
  const chapters = bodies.flatMap((body) => {
    const loose = materialize(body.loose);
    const sections = body.sections.map(materialize).filter((item): item is StrictFb2ChapterSource => item !== null);
    return loose ? [loose, ...sections] : sections;
  });
  if (chapters.length === 0) throw new Error('PUBLICATION_STRUCTURE_INVALID');
  return { title: bookTitle, language, chapters, blockedResources };
}
