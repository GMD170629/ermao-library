import { readFile, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const [, , inputArg, outputArg] = process.argv;
if (!inputArg || !outputArg) throw new Error('usage: generate-api-v2.mjs OPENAPI.json OUTPUT.ts');

const input = path.resolve(inputArg);
const output = path.resolve(outputArg);
const document = JSON.parse(await readFile(input, 'utf8'));
const schemas = document.components?.schemas ?? {};

function refName(ref) {
  return ref.split('/').at(-1);
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
  if (Array.isArray(schema.oneOf)) return schema.oneOf.map((item) => typeExpression(item, depth)).join(' | ');
  if (Array.isArray(schema.anyOf)) return schema.anyOf.map((item) => typeExpression(item, depth)).join(' | ');
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
      properties.push(`${'  '.repeat(depth + 1)}[key: string]: ${schema.additionalProperties === true ? 'unknown' : typeExpression(schema.additionalProperties, depth + 1)};`);
    }
    if (!properties.length) return 'Record<string, unknown>';
    return `{\n${properties.join('\n')}\n${'  '.repeat(depth)}}`;
  }
  return 'unknown';
}

function responseType(operation) {
  const success = Object.entries(operation.responses ?? {}).find(([status]) => /^2\d\d$/.test(status));
  if (!success) return 'never';
  const response = success[1];
  if (response?.$ref) return refName(response.$ref);
  const content = response?.content ?? {};
  const schema = content['application/json']?.schema
    ?? content['application/problem+json']?.schema
    ?? content[Object.keys(content)[0]]?.schema;
  return schema ? typeExpression(schema) : 'void';
}

function requestType(operation) {
  const body = operation.requestBody;
  if (!body) return 'never';
  const resolved = body.$ref
    ? { schema: body }
    : body.content?.['application/json'] ?? body.content?.['multipart/form-data'];
  return resolved?.schema ? typeExpression(resolved.schema) : 'unknown';
}

const schemaTypes = Object.keys(schemas)
  .sort()
  .flatMap((name) => [`export type ${name} = ${typeExpression(schemas[name])};`, '']);

const pathLines = Object.entries(document.paths ?? {}).flatMap(([apiPath, item]) => {
  const methods = Object.entries(item)
    .filter(([method]) => ['get', 'post', 'put', 'patch', 'delete'].includes(method))
    .map(([method, operation]) => {
      const parameters = (operation.parameters ?? []).filter((parameter) => parameter.in === 'query');
      const query = parameters.length
        ? `{ ${parameters.map((parameter) => `${propertyName(parameter.name)}${parameter.required ? '' : '?'}: ${typeExpression(parameter.schema)}`).join('; ')} }`
        : 'never';
      return `    ${method}: { request: ${requestType(operation)}; query: ${query}; response: ${responseType(operation)} };`;
    });
  return [`  ${JSON.stringify(apiPath)}: {`, ...methods, '  };'];
});

const generated = [
  '/* eslint-disable */',
  '// AUTO-GENERATED from appv2 FastAPI OpenAPI. Do not edit by hand.',
  '// Run `pnpm --filter @shuku/web generate:api-v2`.',
  '',
  ...schemaTypes,
  'export interface ApiV2Paths {',
  ...pathLines,
  '}',
  ''
].join('\n');

await writeFile(output, generated, 'utf8');
await unlink(input).catch(() => undefined);
