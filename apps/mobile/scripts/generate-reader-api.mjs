import { readFile, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const [, , inputArgument, outputArgument, ...optionArguments] = process.argv;

if (!inputArgument || !outputArgument) {
  throw new Error(
    'usage: generate-reader-api.mjs OPENAPI.json OUTPUT.ts',
  );
}

const options = new Set(optionArguments);
const supportedOptions = new Set(['--check', '--delete-input']);
const unsupportedOptions = optionArguments.filter(
  (option) => !supportedOptions.has(option),
);
if (unsupportedOptions.length > 0) {
  throw new Error(`unsupported options: ${unsupportedOptions.join(', ')}`);
}

const inputPath = path.resolve(inputArgument);
const outputPath = path.resolve(outputArgument);
const document = JSON.parse(await readFile(inputPath, 'utf8'));
const schemas = document.components?.schemas ?? {};

const readerSchemaNames = new Set([
  'AudioLocation',
  'ComicLocation',
  'EpubLocation',
  'ErrorEnvelope_ReaderErrorBody_',
  'PdfLocation',
  'ReaderBookSummary',
  'ReaderBookmark',
  'ReaderBookmarksData',
  'ReaderBookmarksReplaceRequest',
  'ReaderBookmarksResponse',
  'ReaderBootstrapData',
  'ReaderBootstrapResponse',
  'ReaderCapabilities',
  'ReaderErrorBody',
  'ReaderFileSummary',
  'ReaderJsonValue',
  'ReaderMediaVersionSummary',
  'ReaderProgressData',
  'ReaderProgressPut',
  'ReaderProgressRecord',
  'ReaderProgressResponse',
  'ReaderReadingStatusData',
  'ReaderReadingStatusPut',
  'ReaderReadingStatusResponse',
  'ReaderUnitSummary',
  'ReaderVolumeSummary',
  'ReflowableLocation',
]);

function schemaBaseName(name) {
  return name.split('-')[0];
}

const includedNames = Object.keys(schemas)
  .filter((name) => readerSchemaNames.has(schemaBaseName(name)))
  .sort();

const missingSchemas = [...readerSchemaNames].filter(
  (name) => !includedNames.some((included) => schemaBaseName(included) === name),
);
if (missingSchemas.length > 0) {
  throw new Error(
    `Reader v3 schemas are missing from OpenAPI: ${missingSchemas.join(', ')}`,
  );
}

function typeName(name) {
  const normalized = String(name ?? '').replace(/[^A-Za-z0-9_$]/g, '_');
  return /^[A-Za-z_$]/.test(normalized) ? normalized : `_${normalized}`;
}

function referenceName(reference) {
  return typeName(reference.split('/').at(-1));
}

function propertyName(name) {
  return /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(name)
    ? name
    : JSON.stringify(name);
}

function literal(value) {
  return typeof value === 'string' ? JSON.stringify(value) : String(value);
}

function typeExpression(schema, depth = 0) {
  if (!schema || typeof schema !== 'object') return 'unknown';
  if (schema.$ref) return referenceName(schema.$ref);
  if (Object.hasOwn(schema, 'const')) return literal(schema.const);
  if (Array.isArray(schema.enum)) {
    return schema.enum.map(literal).join(' | ') || 'never';
  }
  if (Array.isArray(schema.oneOf)) {
    return schema.oneOf
      .map((item) => typeExpression(item, depth))
      .join(' | ');
  }
  if (Array.isArray(schema.anyOf)) {
    return schema.anyOf
      .map((item) => typeExpression(item, depth))
      .join(' | ');
  }
  if (Array.isArray(schema.allOf)) {
    return schema.allOf
      .map((item) => typeExpression(item, depth))
      .join(' & ');
  }
  if (schema.type === 'array') {
    const itemType = typeExpression(schema.items, depth + 1);
    return /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(itemType)
      ? `${itemType}[]`
      : `(${itemType})[]`;
  }
  if (schema.type === 'string') return 'string';
  if (schema.type === 'integer' || schema.type === 'number') return 'number';
  if (schema.type === 'boolean') return 'boolean';
  if (schema.type === 'null') return 'null';
  if (schema.type === 'object' || schema.properties || schema.additionalProperties) {
    const required = new Set(schema.required ?? []);
    const properties = Object.entries(schema.properties ?? {}).map(
      ([name, value]) => {
        const optional = required.has(name) ? '' : '?';
        return `${'  '.repeat(depth + 1)}${propertyName(name)}${optional}: ${typeExpression(value, depth + 1)};`;
      },
    );
    if (schema.additionalProperties) {
      const valueType =
        schema.additionalProperties === true
          ? 'unknown'
          : typeExpression(schema.additionalProperties, depth + 1);
      properties.push(
        `${'  '.repeat(depth + 1)}[key: string]: ${valueType};`,
      );
    }
    if (properties.length === 0) return 'Record<string, unknown>';
    return `{\n${properties.join('\n')}\n${'  '.repeat(depth)}}`;
  }
  return 'unknown';
}

const excludedReferences = new Set();
for (const name of includedNames) {
  const serialized = JSON.stringify(schemas[name]);
  for (const match of serialized.matchAll(
    /#\/components\/schemas\/([^"\\]+)/g,
  )) {
    const referencedName = match[1];
    if (referencedName && !includedNames.includes(referencedName)) {
      excludedReferences.add(referencedName);
    }
  }
}
if (excludedReferences.size > 0) {
  throw new Error(
    `Reader v3 schemas reference excluded models: ${[...excludedReferences].join(', ')}`,
  );
}

const generated = [
  '// AUTO-GENERATED from the Reader v3 FastAPI OpenAPI contract.',
  '// Run `node scripts/generate-reader-api.mjs OPENAPI.json generated/reader-v3.ts`; do not edit by hand.',
  '',
  ...includedNames.flatMap((name) => [
    `export type ${typeName(name)} = ${typeExpression(schemas[name])};`,
    '',
  ]),
].join('\n');

let mismatch = false;
if (options.has('--check')) {
  const current = await readFile(outputPath, 'utf8').catch(() => '');
  mismatch = current !== generated;
} else {
  await writeFile(outputPath, generated, 'utf8');
}

if (options.has('--delete-input')) {
  await unlink(inputPath);
}

if (mismatch) {
  throw new Error(
    `Reader v3 generated contract is stale: ${outputPath}`,
  );
}
