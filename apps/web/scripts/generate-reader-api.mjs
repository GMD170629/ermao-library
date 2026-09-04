import { readFile, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const [, , inputArg, outputArg] = process.argv;
if (!inputArg || !outputArg) throw new Error('usage: generate-reader-api.mjs OPENAPI.json OUTPUT.ts');

const input = path.resolve(inputArg);
const output = path.resolve(outputArg);
const document = JSON.parse(await readFile(input, 'utf8'));
const schemas = document.components?.schemas ?? {};
const included = new Set(
  Object.keys(schemas).filter((name) => /^(Appearance|Audio|Epub|Reflowable|Comic|Pdf|Reader)/.test(name))
);
let discoveredReference = true;
while (discoveredReference) {
  discoveredReference = false;
  for (const name of [...included]) {
    const serialized = JSON.stringify(schemas[name]);
    for (const match of serialized.matchAll(/#\/components\/schemas\/([^"\\]+)/g)) {
      if (included.has(match[1])) continue;
      if (!Object.hasOwn(schemas, match[1])) throw new Error(`Reader schema references missing model: ${match[1]}`);
      included.add(match[1]);
      discoveredReference = true;
    }
  }
}
const includedNames = [...included].sort();

function typeName(name) {
  const normalized = String(name ?? '').replace(/[^A-Za-z0-9_$]/g, '_');
  return /^[A-Za-z_$]/.test(normalized) ? normalized : `_${normalized}`;
}

function refName(ref) {
  return typeName(ref.split('/').at(-1));
}

function propertyName(name) {
  return /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(name) ? name : JSON.stringify(name);
}

function literal(value) {
  return typeof value === 'string' ? JSON.stringify(value) : String(value);
}

function typeExpression(schema, depth = 0) {
  if (!schema || typeof schema !== 'object') return 'unknown';
  if (schema.$ref) return refName(schema.$ref);
  if (Object.hasOwn(schema, 'const')) return literal(schema.const);
  if (Array.isArray(schema.enum)) return schema.enum.map(literal).join(' | ') || 'never';
  if (Array.isArray(schema.oneOf)) return [...new Set(schema.oneOf.map((item) => typeExpression(item, depth)))].join(' | ');
  if (Array.isArray(schema.anyOf)) return [...new Set(schema.anyOf.map((item) => typeExpression(item, depth)))].join(' | ');
  if (Array.isArray(schema.allOf)) return schema.allOf.map((item) => typeExpression(item, depth)).join(' & ');
  if (schema.type === 'array') return `Array<${typeExpression(schema.items, depth + 1)}>`;
  if (schema.type === 'string') return 'string';
  if (schema.type === 'integer' || schema.type === 'number') return 'number';
  if (schema.type === 'boolean') return 'boolean';
  if (schema.type === 'null') return 'null';
  if (schema.type === 'object' || schema.properties || schema.additionalProperties) {
    const required = new Set(schema.required ?? []);
    const properties = Object.entries(schema.properties ?? {}).map(([name, value]) => {
      const optional = required.has(name) ? '' : '?';
      return `${'  '.repeat(depth + 1)}${propertyName(name)}${optional}: ${typeExpression(value, depth + 1)};`;
    });
    if (schema.additionalProperties) {
      const valueType = schema.additionalProperties === true ? 'unknown' : typeExpression(schema.additionalProperties, depth + 1);
      properties.push(`${'  '.repeat(depth + 1)}[key: string]: ${valueType} | null | undefined;`);
    }
    if (!properties.length) return 'Record<string, unknown>';
    return `{\n${properties.join('\n')}\n${'  '.repeat(depth)}}`;
  }
  return 'unknown';
}

const missingRefs = new Set();
for (const name of includedNames) {
  const serialized = JSON.stringify(schemas[name]);
  for (const match of serialized.matchAll(/#\/components\/schemas\/([^"\\]+)/g)) {
    if (!included.has(match[1])) missingRefs.add(match[1]);
  }
}
if (missingRefs.size) throw new Error(`Reader schemas reference excluded models: ${[...missingRefs].join(', ')}`);

const generated = [
  '/* eslint-disable */',
  '// AUTO-GENERATED from the Reader v5 FastAPI OpenAPI contract.',
  '// Run `pnpm --filter @shuku/web generate:reader-api`; do not edit by hand.',
  '',
  ...includedNames.flatMap((name) => [`export type ${typeName(name)} = ${typeExpression(schemas[name])};`, ''])
].join('\n');

await writeFile(output, generated, 'utf8');
await unlink(input).catch(() => undefined);
