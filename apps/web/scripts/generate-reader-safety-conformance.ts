import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { BlobReader, ZipReader } from '@zip.js/zip.js';
import {
  READER_SAFETY_POLICY_DIGEST,
  READER_SAFETY_POLICY_ID,
  READER_SAFETY_POLICY_VERSION,
  READER_SAFETY_PROFILES,
  isReaderSafetyRuleId,
  readerSafetyAcceptsMimeType,
  readerSafetyBudget,
  readerSafetyFormatPolicy,
  readerSafetyRule,
  type ReaderSafetyAction,
  type ReaderSafetyErrorCode,
  type ReaderSafetyRuleId
} from '@shuku/reader-core';
import {
  ReaderSafetyPolicyError,
  authoredUriDisposition,
  preflightReflowableXml,
  sanitizeAuthoredCss
} from '../features/reader/v3/security/reader-safety-policy';
import { preflightEpubArchiveEntries } from '../features/reader/v3/security/epub-archive-safety';

const REPOSITORY_ROOT = path.resolve(import.meta.dirname, '../../..');
const FIXTURE_ROOT = path.join(
  REPOSITORY_ROOT,
  'packages/reader-contracts/fixtures/reader-safety-v1'
);
const MANIFEST_PATH = path.join(FIXTURE_ROOT, 'manifest.json');
const SUITE_PATH = path.join(FIXTURE_ROOT, 'conformance-suite.json');

type JsonObject = Readonly<Record<string, unknown>>;
type Evaluator =
  | 'REFLOWABLE_MARKUP'
  | 'REFLOWABLE_NAMED_ENTITIES'
  | 'REFLOWABLE_MARKUP_SANITIZE'
  | 'REFLOWABLE_URI'
  | 'REFLOWABLE_CSS'
  | 'REFLOWABLE_SVG'
  | 'ARCHIVE_STRUCTURE'
  | 'EPUB_ARCHIVE_CRC'
  | 'ORIGINAL_BYTES'
  | 'FB2_STRUCTURE'
  | 'PDF_ACTIVE_ACTIONS'
  | 'PDF_PAGE_GEOMETRY'
  | 'PDF_RANGE_PROTOCOL'
  | 'COMIC_PAGE_MIME'
  | 'COMIC_PAGE_COUNT'
  | 'COMIC_PAGE_DECODE'
  | 'COMIC_REVISION'
  | 'AUDIO_CONTAINER_MIME'
  | 'AUDIO_CODEC'
  | 'AUDIO_CHAPTER_BOUNDS'
  | 'DRM_ALGORITHM'
  | 'EXACT_FORMAT_MIME'
  | 'BINARY_RESOURCE_BYTES'
  | 'OPTIONAL_RESOURCE'
  | 'REQUIRED_READING_ORDER_MARKUP'
  | 'XML_CONTROL_DOCUMENT_BYTES'
  | 'REFLOWABLE_MARKUP_BYTES'
  | 'EPUB_ARCHIVE_ENTRY_COUNT'
  | 'EPUB_ARCHIVE_EXPANDED_BYTES'
  | 'EPUB_ARCHIVE_ENTRY_BYTES'
  | 'EPUB_ARCHIVE_COMPRESSION_RATIO'
  | 'FB2_IMAGE_BUDGET'
  | 'TXT_MEMORY_BYTES'
  | 'TXT_CHUNK_CHARACTERS'
  | 'PDF_RENDER_BUDGET'
  | 'COMIC_ARCHIVE_STRUCTURE'
  | 'COMIC_ARCHIVE_BUDGET'
  | 'COMIC_PAGE_BYTES'
  | 'COMIC_MANIFEST_BYTES'
  | 'AUDIO_ORIGINAL_BYTES'
  | 'AUDIO_METADATA_BUDGET'
  | 'AUDIO_REDIRECT_POLICY';
type SemanticProjection =
  | 'ROOT_LOCAL_NAME'
  | 'SANITIZED_TEXT'
  | 'SANITIZED_MARKUP'
  | 'INPUT'
  | 'FONT_OBFUSCATION'
  | 'NONE';

type ExecutableCase = Readonly<{
  caseId: string;
  ruleId: ReaderSafetyRuleId;
  input: string;
  inputSha256: string;
  evaluator: Evaluator;
  semanticProjection: SemanticProjection;
}>;

type ActualDecision = Readonly<{
  ruleId: ReaderSafetyRuleId;
  action: ReaderSafetyAction;
  errorCode: ReaderSafetyErrorCode | null;
  event: string;
  semanticProjection: string | null;
}>;

export type WebReaderSafetyConformanceReport = Readonly<{
  schemaVersion: 1;
  policyId: typeof READER_SAFETY_POLICY_ID;
  policyVersion: typeof READER_SAFETY_POLICY_VERSION;
  policyDigest: typeof READER_SAFETY_POLICY_DIGEST;
  consumer: 'WEB';
  engine: string;
  results: ReadonlyArray<Readonly<{
    caseId: string;
    inputSha256: string;
    terminalRuleId: ReaderSafetyRuleId;
    action: ReaderSafetyAction;
    errorCode: ReaderSafetyErrorCode | null;
    orderedRuleEvents: ReadonlyArray<string>;
    semanticProjectionSha256: string | null;
  }>>;
  omissions: readonly [];
}>;

const EVALUATORS: ReadonlySet<string> = new Set<Evaluator>([
  'REFLOWABLE_MARKUP',
  'REFLOWABLE_NAMED_ENTITIES',
  'REFLOWABLE_MARKUP_SANITIZE',
  'REFLOWABLE_URI',
  'REFLOWABLE_CSS',
  'REFLOWABLE_SVG',
  'ARCHIVE_STRUCTURE',
  'EPUB_ARCHIVE_CRC',
  'ORIGINAL_BYTES',
  'FB2_STRUCTURE',
  'PDF_ACTIVE_ACTIONS',
  'PDF_PAGE_GEOMETRY',
  'PDF_RANGE_PROTOCOL',
  'COMIC_PAGE_MIME',
  'COMIC_PAGE_COUNT',
  'COMIC_PAGE_DECODE',
  'COMIC_REVISION',
  'AUDIO_CONTAINER_MIME',
  'AUDIO_CODEC',
  'AUDIO_CHAPTER_BOUNDS',
  'DRM_ALGORITHM',
  'EXACT_FORMAT_MIME',
  'BINARY_RESOURCE_BYTES',
  'OPTIONAL_RESOURCE',
  'REQUIRED_READING_ORDER_MARKUP',
  'XML_CONTROL_DOCUMENT_BYTES',
  'REFLOWABLE_MARKUP_BYTES',
  'EPUB_ARCHIVE_ENTRY_COUNT',
  'EPUB_ARCHIVE_EXPANDED_BYTES',
  'EPUB_ARCHIVE_ENTRY_BYTES',
  'EPUB_ARCHIVE_COMPRESSION_RATIO',
  'FB2_IMAGE_BUDGET',
  'TXT_MEMORY_BYTES',
  'TXT_CHUNK_CHARACTERS',
  'PDF_RENDER_BUDGET',
  'COMIC_ARCHIVE_STRUCTURE',
  'COMIC_ARCHIVE_BUDGET',
  'COMIC_PAGE_BYTES',
  'COMIC_MANIFEST_BYTES',
  'AUDIO_ORIGINAL_BYTES',
  'AUDIO_METADATA_BUDGET',
  'AUDIO_REDIRECT_POLICY'
]);
const SEMANTIC_PROJECTIONS: ReadonlySet<string> = new Set<SemanticProjection>([
  'ROOT_LOCAL_NAME',
  'SANITIZED_TEXT',
  'SANITIZED_MARKUP',
  'INPUT',
  'FONT_OBFUSCATION',
  'NONE'
]);
const MARKUP_EVALUATORS: ReadonlySet<Evaluator> = new Set([
  'REFLOWABLE_MARKUP',
  'REFLOWABLE_NAMED_ENTITIES',
  'REFLOWABLE_MARKUP_SANITIZE',
  'REFLOWABLE_URI',
  'REFLOWABLE_CSS',
  'REFLOWABLE_SVG'
]);

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function objectValue(value: unknown, field: string): JsonObject {
  if (!isJsonObject(value)) throw new Error(`${field} must be an object`);
  return value;
}

function arrayValue(value: unknown, field: string): ReadonlyArray<unknown> {
  if (!Array.isArray(value)) throw new Error(`${field} must be an array`);
  return value;
}

function stringValue(value: unknown, field: string): string {
  if (typeof value !== 'string' || value.length === 0) {
    throw new Error(`${field} must be a nonempty string`);
  }
  return value;
}

function sha256(value: string): string {
  return createHash('sha256').update(value, 'utf8').digest('hex');
}

function executableCases(suiteValue: unknown, manifestValue: unknown): ReadonlyArray<ExecutableCase> {
  const suite = objectValue(suiteValue, 'suite');
  const manifest = objectValue(manifestValue, 'manifest');
  if (
    suite.policyId !== READER_SAFETY_POLICY_ID
    || suite.policyVersion !== READER_SAFETY_POLICY_VERSION
    || suite.policyDigest !== READER_SAFETY_POLICY_DIGEST
  ) {
    throw new Error('Reader safety conformance suite targets a stale Web policy');
  }
  const fixtures = new Map<string, JsonObject>();
  for (const [index, rawCase] of arrayValue(manifest.cases, 'manifest.cases').entries()) {
    const fixture = objectValue(rawCase, `manifest.cases[${index}]`);
    fixtures.set(stringValue(fixture.id, `manifest.cases[${index}].id`), fixture);
  }

  const cases: ExecutableCase[] = [];
  for (const [index, rawCase] of arrayValue(suite.cases, 'suite.cases').entries()) {
    const suiteCase = objectValue(rawCase, `suite.cases[${index}]`);
    if (!arrayValue(suiteCase.consumers, `suite.cases[${index}].consumers`).includes('WEB')) continue;
    const evaluator = stringValue(suiteCase.evaluator, `suite.cases[${index}].evaluator`);
    if (!EVALUATORS.has(evaluator)) {
      throw new Error(`Unsupported Web conformance evaluator at suite.cases[${index}]`);
    }
    const caseId = stringValue(suiteCase.id, `suite.cases[${index}].id`);
    const rawRuleId = stringValue(suiteCase.ruleId, `suite.cases[${index}].ruleId`);
    if (!isReaderSafetyRuleId(rawRuleId)) {
      throw new Error(`Unknown generated Reader safety rule: ${rawRuleId}`);
    }
    const semanticProjection = stringValue(
      suiteCase.semanticProjection,
      `suite.cases[${index}].semanticProjection`
    );
    if (!SEMANTIC_PROJECTIONS.has(semanticProjection)) {
      throw new Error(`Unsupported semantic projection for ${caseId}`);
    }
    const fixture = fixtures.get(caseId);
    if (!fixture) throw new Error(`Missing Reader safety fixture: ${caseId}`);
    const input = stringValue(fixture.input, `${caseId}.input`);
    const inputSha256 = stringValue(fixture.inputSha256, `${caseId}.inputSha256`);
    if (sha256(input) !== inputSha256) {
      throw new Error(`Reader safety fixture input hash differs for ${caseId}`);
    }
    cases.push({
      caseId,
      ruleId: rawRuleId,
      input,
      inputSha256,
      evaluator: evaluator as Evaluator,
      semanticProjection: semanticProjection as SemanticProjection
    });
  }
  return cases;
}

function generatedDecision(
  ruleId: ReaderSafetyRuleId,
  semanticProjection: string | null = null
): ActualDecision {
  const rule = readerSafetyRule(ruleId);
  return {
    ruleId,
    action: rule.action,
    errorCode: rule.errorCode,
    event: `${ruleId}:${rule.action}`,
    semanticProjection
  };
}

function allowedDecision(
  ruleId: ReaderSafetyRuleId,
  event: string,
  semanticProjection: string
): ActualDecision {
  return { ruleId, action: 'ALLOW', errorCode: null, event: `${ruleId}:${event}`, semanticProjection };
}

function rootLocalName(markup: string, caseId: string): string {
  const match = /<(?:[A-Za-z_][\w.-]*:)?([A-Za-z][\w.-]*)\b/.exec(markup);
  const localName = match?.[1];
  if (!localName) throw new Error(`Web safety parser did not expose a root for ${caseId}`);
  return localName.toLowerCase();
}

function removeElements(source: string, names: readonly string[]): string {
  return names.reduce((markup, name) => {
    const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const selfClosing = new RegExp(`<${escaped}\\b[^>]*/\\s*>`, 'gi');
    const paired = new RegExp(`<${escaped}\\b[^>]*>[\\s\\S]*?</${escaped}\\s*>`, 'gi');
    return markup.replace(selfClosing, '').replace(paired, '');
  }, source);
}

function sanitizeMarkupString(source: string, includeSvg: boolean): string {
  const profile = READER_SAFETY_PROFILES.reflowable;
  let markup = removeElements(
    source,
    includeSvg ? [...profile.sanitizedElements, ...profile.svgSanitizedElements] : profile.sanitizedElements
  );
  for (const attribute of profile.sanitizedAttributes) {
    markup = markup.replace(
      new RegExp(`\\s+${attribute.replace(':', '\\:')}\\s*=\\s*(?:"[^"]*"|'[^']*'|[^\\s>]+)`, 'gi'),
      ''
    );
  }
  for (const prefix of profile.sanitizedAttributePrefixes) {
    markup = markup.replace(
      new RegExp(`\\s+${prefix}[A-Za-z0-9_.:-]*\\s*=\\s*(?:"[^"]*"|'[^']*'|[^\\s>]+)`, 'gi'),
      ''
    );
  }
  return markup;
}

function sanitizeUriMarkup(source: string): string {
  return source.replace(/<([A-Za-z][\w.-]*)([^>]*)>/g, (tag, rawName: string, rawAttributes: string) => {
    const name = rawName.toLowerCase();
    const attributes = rawAttributes.replace(
      /\s+([A-Za-z_:][\w:.-]*)\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))/g,
      (attribute, rawAttributeName: string, _quoted: string, double: string | undefined, single: string | undefined, bare: string | undefined) => {
        const attributeName = rawAttributeName.toLowerCase();
        const policy = READER_SAFETY_PROFILES.reflowable.uriAttributePolicies.find((candidate) => (
          candidate.elements.some((element) => element === '*' || element.toLowerCase() === name)
          && candidate.attribute.toLowerCase() === attributeName
        ));
        if (!policy) return attribute;
        const value = double ?? single ?? bare ?? '';
        if (policy.purpose === 'ALWAYS_REMOVE') return '';
        const purpose = policy.purpose === 'USER_NAVIGATION' ? 'navigation' : 'subresource';
        return authoredUriDisposition(value, purpose) === 'remove' ? '' : attribute;
      }
    );
    return `<${rawName}${attributes}>`;
  });
}

async function evaluateMarkupCase(testCase: ExecutableCase): Promise<ActualDecision> {
  if (testCase.evaluator === 'REFLOWABLE_CSS') {
    const sanitized = await sanitizeAuthoredCss(testCase.input, async () => null);
    if (sanitized === testCase.input) throw new Error(`${testCase.caseId} did not trigger CSS policy`);
    return generatedDecision(testCase.ruleId, sanitized);
  }
  try {
    const parserMarkup = preflightReflowableXml(testCase.input, testCase.ruleId);
    if (testCase.evaluator === 'REFLOWABLE_NAMED_ENTITIES') {
      if (!parserMarkup.includes('&#160;') || !parserMarkup.includes('&#169;') || /&(nbsp|copy);/.test(parserMarkup)) {
        throw new Error(`${testCase.caseId} did not rewrite generated named entities`);
      }
    }
    if (testCase.evaluator === 'REFLOWABLE_MARKUP' || testCase.evaluator === 'REFLOWABLE_NAMED_ENTITIES') {
      return generatedDecision(testCase.ruleId, rootLocalName(parserMarkup, testCase.caseId));
    }
    let sanitized: string;
    if (testCase.evaluator === 'REFLOWABLE_URI') {
      sanitized = sanitizeUriMarkup(parserMarkup);
    } else {
      sanitized = sanitizeMarkupString(parserMarkup, testCase.evaluator === 'REFLOWABLE_SVG');
    }
    if (sanitized === parserMarkup) throw new Error(`${testCase.caseId} did not trigger markup policy`);
    return generatedDecision(testCase.ruleId, sanitized);
  } catch (reason: unknown) {
    if (!(reason instanceof ReaderSafetyPolicyError)) throw reason;
    if (reason.ruleId !== testCase.ruleId) {
      throw new Error(`${testCase.caseId} produced an unexpected Web safety decision`, { cause: reason });
    }
    return generatedDecision(reason.ruleId);
  }
}

function facts(source: string): Readonly<Record<string, string>> {
  return Object.fromEntries(source.split(';').map((component) => {
    const separator = component.indexOf('=');
    if (separator <= 0) throw new Error(`Invalid conformance fact: ${component}`);
    return [component.slice(0, separator), component.slice(separator + 1)];
  }));
}

function integerFact(values: Readonly<Record<string, string>>, name: string): number {
  const raw = values[name];
  if (raw === undefined || !/^-?\d+$/.test(raw)) throw new Error(`Invalid integer fact: ${name}`);
  return Number.parseInt(raw, 10);
}

function archiveIsUnsafe(source: string, fatalFindings: readonly string[]): boolean {
  const findings = new Set<string>();
  const canonical = new Set<string>();
  for (const entry of source.split('|')) {
    if (entry.includes('\\')) findings.add('BACKSLASH_PATH');
    if (entry.includes('\0')) findings.add('NUL_PATH');
    if (entry.startsWith('/')) findings.add('ABSOLUTE_PATH');
    const parts: string[] = [];
    let escaped = false;
    for (const part of entry.split('/')) {
      if (part === '' || part === '.') {
        if (part === '.') findings.add('DOT_SEGMENT');
        continue;
      }
      if (part === '..') {
        findings.add('DOT_SEGMENT');
        if (parts.length === 0) escaped = true;
        else parts.pop();
      } else {
        parts.push(part);
      }
    }
    if (escaped) findings.add('PATH_ESCAPE');
    const normalized = parts.join('/').toLowerCase();
    if (canonical.has(normalized)) findings.add('DUPLICATE_CANONICAL_ENTRY');
    canonical.add(normalized);
  }
  return fatalFindings.some((finding) => findings.has(finding));
}

function audioMime(extension: string): string | null {
  const mapping = READER_SAFETY_PROFILES.audio.containerMimeTypes;
  const normalized = extension.toLowerCase();
  return Object.prototype.hasOwnProperty.call(mapping, normalized)
    ? mapping[normalized as keyof typeof mapping]
    : null;
}

function evaluateFactCase(testCase: ExecutableCase): ActualDecision {
  const values = testCase.input.includes('=') ? facts(testCase.input) : {};
  let detected: boolean;
  switch (testCase.evaluator) {
    case 'ARCHIVE_STRUCTURE':
      detected = archiveIsUnsafe(
        testCase.input,
        READER_SAFETY_PROFILES.reflowable.archiveFatalFindings
      );
      break;
    case 'EPUB_ARCHIVE_CRC':
      throw new Error('EPUB CRC requires the asynchronous production archive preflight');
    case 'ORIGINAL_BYTES':
      detected = integerFact(values, 'sizeBytes') > readerSafetyBudget('originalMaxBytes');
      if (!detected) return allowedDecision(testCase.ruleId, 'BOUNDARY_ALLOW', testCase.input);
      break;
    case 'FB2_STRUCTURE':
      detected = integerFact(values, 'depth') > readerSafetyBudget('fb2MaxDepth')
        || integerFact(values, 'nodes') > readerSafetyBudget('fb2MaxNodes')
        || integerFact(values, 'textChars') > readerSafetyBudget('fb2TextMaxCharacters');
      break;
    case 'PDF_ACTIVE_ACTIONS': {
      const actions = new Set((values.actions ?? '').split(',').filter(Boolean));
      const blocked = new Set<string>(
        READER_SAFETY_PROFILES.pdf.blockedActions.filter((action) => actions.has(action))
      );
      detected = blocked.size > 0;
      if (detected) {
        return generatedDecision(
          testCase.ruleId,
          [...actions].filter((action) => !blocked.has(action)).sort().join(',')
        );
      }
      break;
    }
    case 'PDF_PAGE_GEOMETRY': {
      const width = Number(values.width);
      const height = Number(values.height);
      detected = integerFact(values, 'pageCount') > readerSafetyBudget('pdfPageMaxCount');
      if (READER_SAFETY_PROFILES.pdf.requireFinitePageGeometry) {
        detected ||= !Number.isFinite(width) || width <= 0 || !Number.isFinite(height) || height <= 0;
      }
      break;
    }
    case 'PDF_RANGE_PROTOCOL':
      detected = (values.status !== '206' && !READER_SAFETY_PROFILES.pdf.allowWholeResponseFallback)
        || (values.encoding?.toLowerCase() !== 'identity' && READER_SAFETY_PROFILES.pdf.requireIdentityContentEncoding)
        || (values.revision?.toLowerCase() === 'weak' && READER_SAFETY_PROFILES.pdf.requireStrongRevision);
      break;
    case 'COMIC_PAGE_MIME':
      detected = READER_SAFETY_PROFILES.comic.allowedPageMimeTypes.some((mime) => mime === values.manifest)
        && values.response !== values.manifest;
      break;
    case 'COMIC_PAGE_COUNT':
      detected = integerFact(values, 'pageCount') > readerSafetyBudget('comicPageMaxCount');
      break;
    case 'COMIC_PAGE_DECODE':
      detected = values.decoder === 'failed'
        && READER_SAFETY_PROFILES.comic.singlePageDecodeFailureAction === 'BLOCK_RESOURCE';
      break;
    case 'COMIC_REVISION':
      detected = READER_SAFETY_PROFILES.comic.manifestRevisionRequired
        && values.manifestRevision !== values.requestRevision;
      break;
    case 'AUDIO_CONTAINER_MIME':
      detected = audioMime(values.extension ?? '') !== null
        && audioMime(values.extension ?? '') !== values.mime?.toLowerCase();
      break;
    case 'AUDIO_CODEC':
      detected = READER_SAFETY_PROFILES.audio.codecDecision === 'ENGINE_CAPABILITY'
        && values.codec === 'unsupported';
      break;
    case 'AUDIO_CHAPTER_BOUNDS': {
      const duration = Number(values.durationMs);
      const start = Number(values.chapterStartMs);
      const end = Number(values.chapterEndMs);
      detected = !(0 <= start && start <= end && end <= duration);
      if (READER_SAFETY_PROFILES.audio.requireFiniteNonNegativeDuration) {
        detected ||= ![duration, start, end].every((value) => Number.isFinite(value) && value >= 0);
      }
      break;
    }
    case 'DRM_ALGORITHM':
      detected = !READER_SAFETY_PROFILES.reflowable.allowedFontObfuscationAlgorithms.some(
        (algorithm) => algorithm === values.algorithm
      );
      if (!detected) {
        return allowedDecision(testCase.ruleId, 'ALLOW_FONT_OBFUSCATION', 'font-obfuscation-allowed');
      }
      break;
    case 'EXACT_FORMAT_MIME': {
      const formatPolicy = readerSafetyFormatPolicy(values.format ?? '');
      detected = formatPolicy === null || !readerSafetyAcceptsMimeType(formatPolicy, values.mime ?? '');
      break;
    }
    case 'BINARY_RESOURCE_BYTES':
      detected = integerFact(values, 'resourceBytes') > readerSafetyBudget('binaryResourceMaxBytes');
      break;
    case 'OPTIONAL_RESOURCE':
      detected = values.required === 'false' && values.available === 'false';
      break;
    case 'REQUIRED_READING_ORDER_MARKUP':
      detected = integerFact(values, 'readingOrderCount') > 0
        && (
          integerFact(values, 'markupCount') < integerFact(values, 'readingOrderCount')
          || !READER_SAFETY_PROFILES.reflowable.readingOrderMarkupMimeTypes.some(
            (mime) => mime === values.mime?.toLowerCase()
          )
        );
      break;
    case 'XML_CONTROL_DOCUMENT_BYTES':
      detected = integerFact(values, 'controlDocumentBytes')
        > readerSafetyBudget('xmlControlDocumentMaxBytes');
      break;
    case 'REFLOWABLE_MARKUP_BYTES':
      detected = integerFact(values, 'markupBytes') > readerSafetyBudget('reflowableMarkupMaxBytes');
      break;
    case 'EPUB_ARCHIVE_ENTRY_COUNT':
      detected = integerFact(values, 'entryCount') > readerSafetyBudget('archiveEntryMaxCount');
      break;
    case 'EPUB_ARCHIVE_EXPANDED_BYTES':
      detected = integerFact(values, 'expandedBytes') > readerSafetyBudget('archiveExpandedMaxBytes');
      break;
    case 'EPUB_ARCHIVE_ENTRY_BYTES':
      detected = integerFact(values, 'entryBytes') > readerSafetyBudget('archiveEntryMaxBytes');
      break;
    case 'EPUB_ARCHIVE_COMPRESSION_RATIO': {
      const compressedBytes = integerFact(values, 'compressedBytes');
      detected = compressedBytes <= 0
        || integerFact(values, 'expandedBytes')
          > compressedBytes * readerSafetyBudget('archiveCompressionRatioMax');
      break;
    }
    case 'FB2_IMAGE_BUDGET':
      detected = !Object.prototype.hasOwnProperty.call(
        READER_SAFETY_PROFILES.reflowable.embeddedImageExtensionsByMimeType,
        values.mime?.toLowerCase() ?? ''
      )
        || integerFact(values, 'encodedBytes') > readerSafetyBudget('fb2EncodedImageMaxBytes')
        || integerFact(values, 'decodedBytes') > readerSafetyBudget('fb2DecodedImageMaxBytes')
        || integerFact(values, 'decodedTotalBytes')
          > readerSafetyBudget('fb2DecodedImagesTotalMaxBytes');
      break;
    case 'TXT_MEMORY_BYTES':
      detected = integerFact(values, 'textBytes') > readerSafetyBudget('txtMemoryMaxBytes');
      break;
    case 'TXT_CHUNK_CHARACTERS':
      detected = integerFact(values, 'chunkCharacters') <= readerSafetyBudget('txtChunkMaxCharacters');
      if (detected) return generatedDecision(testCase.ruleId, testCase.input);
      break;
    case 'PDF_RENDER_BUDGET':
      detected = integerFact(values, 'width') > readerSafetyBudget('pdfCanvasMaxDimension')
        || integerFact(values, 'height') > readerSafetyBudget('pdfCanvasMaxDimension')
        || integerFact(values, 'pixels') > readerSafetyBudget('pdfRenderMaxPixels');
      break;
    case 'COMIC_ARCHIVE_STRUCTURE':
      detected = archiveIsUnsafe(
        testCase.input,
        READER_SAFETY_PROFILES.comic.archiveFatalFindings
      );
      break;
    case 'COMIC_ARCHIVE_BUDGET': {
      const compressedBytes = integerFact(values, 'compressedBytes');
      const expandedBytes = integerFact(values, 'expandedBytes');
      detected = expandedBytes > readerSafetyBudget('comicExpandedMaxBytes')
        || compressedBytes <= 0
        || expandedBytes > compressedBytes * readerSafetyBudget('comicCompressionRatioMax');
      break;
    }
    case 'COMIC_PAGE_BYTES':
      detected = integerFact(values, 'pageBytes') > readerSafetyBudget('comicPageMaxBytes');
      break;
    case 'COMIC_MANIFEST_BYTES':
      detected = integerFact(values, 'manifestBytes') > readerSafetyBudget('comicManifestMaxBytes');
      break;
    case 'AUDIO_ORIGINAL_BYTES':
      detected = integerFact(values, 'sizeBytes') > readerSafetyBudget('originalMaxBytes');
      break;
    case 'AUDIO_METADATA_BUDGET':
      detected = integerFact(values, 'metadataBytes') > readerSafetyBudget('audioMetadataMaxBytes')
        || integerFact(values, 'artworkBytes') > readerSafetyBudget('audioArtworkMaxBytes');
      break;
    case 'AUDIO_REDIRECT_POLICY':
      detected = READER_SAFETY_PROFILES.audio.blockedRedirectSchemes.some(
        (scheme) => scheme === values.scheme?.toLowerCase()
      );
      break;
    default:
      throw new Error(`Unsupported Web fact evaluator: ${testCase.evaluator}`);
  }
  if (!detected) throw new Error(`${testCase.caseId} did not trigger its Web policy fact`);
  return generatedDecision(testCase.ruleId);
}

async function evaluateEpubArchiveCrc(testCase: ExecutableCase): Promise<ActualDecision> {
  const prefix = 'base64:';
  if (!testCase.input.startsWith(prefix)) throw new Error('EPUB CRC fixture is not base64');
  const bytes = Uint8Array.from(Buffer.from(testCase.input.slice(prefix.length), 'base64'));
  const reader = new ZipReader(new BlobReader(
    new Blob([bytes.buffer], { type: 'application/epub+zip' })
  ));
  try {
    const entries = await reader.getEntries({ strictness: 'strict', filenameValidation: 'strict' });
    try {
      await preflightEpubArchiveEntries(entries);
    } catch (reason: unknown) {
      if (reason instanceof ReaderSafetyPolicyError && reason.ruleId === testCase.ruleId) {
        return generatedDecision(reason.ruleId);
      }
      throw reason;
    }
    throw new Error('Web EPUB preflight accepted a corrupted unused entry');
  } finally {
    await reader.close();
  }
}

async function evaluateCase(testCase: ExecutableCase) {
  const decision = MARKUP_EVALUATORS.has(testCase.evaluator)
    ? await evaluateMarkupCase(testCase)
    : testCase.evaluator === 'EPUB_ARCHIVE_CRC'
      ? await evaluateEpubArchiveCrc(testCase)
      : evaluateFactCase(testCase);
  return {
    caseId: testCase.caseId,
    inputSha256: testCase.inputSha256,
    terminalRuleId: decision.ruleId,
    action: decision.action,
    errorCode: decision.errorCode,
    orderedRuleEvents: [decision.event],
    semanticProjectionSha256: decision.semanticProjection === null
      ? null
      : sha256(decision.semanticProjection)
  };
}

export async function generateWebReaderSafetyConformanceReport(
  suite: unknown,
  manifest: unknown,
  engine = `node-${process.versions.node}/production+generated-policy`
): Promise<WebReaderSafetyConformanceReport> {
  return {
    schemaVersion: 1,
    policyId: READER_SAFETY_POLICY_ID,
    policyVersion: READER_SAFETY_POLICY_VERSION,
    policyDigest: READER_SAFETY_POLICY_DIGEST,
    consumer: 'WEB',
    engine,
    results: await Promise.all(executableCases(suite, manifest).map(evaluateCase)),
    omissions: []
  };
}

async function parseJsonFile(filePath: string): Promise<unknown> {
  return JSON.parse(await readFile(filePath, 'utf8')) as unknown;
}

async function main(): Promise<void> {
  const outputIndex = process.argv.indexOf('--output');
  const outputPath = outputIndex >= 0 ? process.argv[outputIndex + 1] : undefined;
  if (!outputPath) throw new Error('Usage: generate-reader-safety-conformance.ts --output <path>');
  const report = await generateWebReaderSafetyConformanceReport(
    await parseJsonFile(SUITE_PATH),
    await parseJsonFile(MANIFEST_PATH)
  );
  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  process.stdout.write(`${outputPath}\n`);
}

const entryPath = process.argv[1];
if (entryPath && import.meta.url === pathToFileURL(path.resolve(entryPath)).href) {
  void main().catch((reason: unknown) => {
    process.stderr.write(`${reason instanceof Error ? reason.stack ?? reason.message : String(reason)}\n`);
    process.exitCode = 1;
  });
}
