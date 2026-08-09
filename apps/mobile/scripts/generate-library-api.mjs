import { readFile, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const [, , inputArgument, outputArgument, ...optionArguments] = process.argv;

if (!inputArgument || !outputArgument) {
  throw new Error('usage: generate-library-api.mjs OPENAPI.json OUTPUT.ts');
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

const requiredOperations = [
  ['get', '/api/auth/preferences', 'SuccessEnvelope_PreferencesPayload_'],
  ['patch', '/api/auth/preferences', 'SuccessEnvelope_PreferencesPayload_'],
  ['get', '/api/dashboard/continue-reading', 'SuccessEnvelope_ContinueReadingPayload_'],
  ['get', '/api/dashboard/recent-books', 'SuccessEnvelope_WorkSummariesPayload_'],
  ['get', '/api/dashboard/summary', 'SuccessEnvelope_DashboardSummaryPayload_'],
  ['get', '/api/monitor-folders', 'SuccessEnvelope_MonitorFoldersPayload_'],
  ['get', '/api/shelves', 'SuccessEnvelope_ShelvesPayload_'],
  ['post', '/api/shelves', 'SuccessEnvelope_ShelfPayload_'],
  ['delete', '/api/shelves/{shelf_id}', 'SuccessEnvelope_DeletedShelfPayload_'],
  ['get', '/api/shelves/{shelf_id}', 'SuccessEnvelope_ShelfPayload_'],
  ['patch', '/api/shelves/{shelf_id}', 'SuccessEnvelope_ShelfPayload_'],
  ['get', '/api/works', 'SuccessEnvelope_WorksPayload_'],
  ['post', '/api/works/import', 'SuccessEnvelope_ImportUploadPayload_'],
];

for (const [method, apiPath, expectedSchema] of requiredOperations) {
  const operation = document.paths?.[apiPath]?.[method];
  const responseReference = operation?.responses?.['200']?.content?.[
    'application/json'
  ]?.schema?.$ref;
  if (
    operation === undefined ||
    schemaBaseName(responseReference?.split('/').at(-1) ?? '') !== expectedSchema
  ) {
    throw new Error(
      `Mobile library operation is missing or changed: ${method.toUpperCase()} ${apiPath}`,
    );
  }
}

const librarySchemaRoots = new Set([
  'CodedMessageBody',
  'ContinueReadingItem',
  'ContinueReadingPayload',
  'DashboardSummaryPayload',
  'DeletedShelfPayload',
  'ErrorEnvelope_CodedMessageBody_',
  'ErrorEnvelope_ImportErrorBody_',
  'ErrorEnvelope_LibraryErrorBody_',
  'ErrorEnvelope_RequestValidationErrorBody_',
  'ErrorEnvelope_UnsupportedPreferenceBody_',
  'ImportErrorBody',
  'ImportUploadPayload',
  'LibraryErrorBody',
  'MonitorFolder',
  'MonitorFoldersPayload',
  'PreferencesPayload',
  'SavedUploadResult',
  'ShelfBook',
  'ShelfMemberView',
  'ShelfPayload',
  'ShelfView',
  'ShelvesPayload',
  'SuccessEnvelope_ContinueReadingPayload_',
  'SuccessEnvelope_DashboardSummaryPayload_',
  'SuccessEnvelope_DeletedShelfPayload_',
  'SuccessEnvelope_ImportUploadPayload_',
  'SuccessEnvelope_MonitorFoldersPayload_',
  'SuccessEnvelope_PreferencesPayload_',
  'SuccessEnvelope_ShelfPayload_',
  'SuccessEnvelope_ShelvesPayload_',
  'SuccessEnvelope_WorkSummariesPayload_',
  'SuccessEnvelope_WorksPayload_',
  'UpdateUserPreferencesRequest',
  'UserPreferences',
  'WorkSummariesPayload',
  'WorkSummary',
  'WorksPayload',
]);

function schemaBaseName(name) {
  return name.split('-')[0];
}

function matchingSchemaName(baseName) {
  return Object.keys(schemas).find(
    (candidate) => schemaBaseName(candidate) === baseName,
  );
}

const missingRoots = [...librarySchemaRoots].filter(
  (name) => matchingSchemaName(name) === undefined,
);
if (missingRoots.length > 0) {
  throw new Error(
    `Mobile library schemas are missing from OpenAPI: ${missingRoots.join(', ')}`,
  );
}

const includedNames = new Set(
  [...librarySchemaRoots].map((name) => matchingSchemaName(name)),
);
const referencePattern = /#\/components\/schemas\/([^"\\]+)/g;
let discoveredReference = true;
while (discoveredReference) {
  discoveredReference = false;
  for (const name of [...includedNames]) {
    for (const match of JSON.stringify(schemas[name]).matchAll(referencePattern)) {
      const referencedName = match[1];
      if (referencedName && !includedNames.has(referencedName)) {
        if (schemas[referencedName] === undefined) {
          throw new Error(`OpenAPI references missing schema: ${referencedName}`);
        }
        includedNames.add(referencedName);
        discoveredReference = true;
      }
    }
  }
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
    return schema.oneOf.map((item) => typeExpression(item, depth)).join(' | ');
  }
  if (Array.isArray(schema.anyOf)) {
    return schema.anyOf.map((item) => typeExpression(item, depth)).join(' | ');
  }
  if (Array.isArray(schema.allOf)) {
    return schema.allOf.map((item) => typeExpression(item, depth)).join(' & ');
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
      properties.push(`${'  '.repeat(depth + 1)}[key: string]: ${valueType};`);
    }
    if (properties.length === 0) return 'Record<string, unknown>';
    return `{\n${properties.join('\n')}\n${'  '.repeat(depth)}}`;
  }
  return 'unknown';
}

const generated = [
  '// AUTO-GENERATED from the live FastAPI Mobile library contract.',
  '// Run `node scripts/generate-library-api.mjs OPENAPI.json generated/library.ts`; do not edit by hand.',
  '',
  ...[...includedNames].sort().flatMap((name) => [
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
  throw new Error(`Mobile library generated contract is stale: ${outputPath}`);
}
