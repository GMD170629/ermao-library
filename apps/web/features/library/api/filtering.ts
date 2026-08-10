import type {
  LibraryFilterOptionPage,
  LibraryFilterOptionSource,
  LibraryFilterSchema,
  SmartFilterField,
  SmartFilterOption
} from '../model/filter-schema';

type JsonObject = Record<string, unknown>;
type SmartFilterFieldType = SmartFilterField['type'];

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isSmartFilterFieldType(value: string): value is SmartFilterFieldType {
  return value === 'text'
    || value === 'select'
    || value === 'number'
    || value === 'date'
    || value === 'boolean';
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== 'string') throw new Error(`Invalid library filter field: ${field}`);
  return value;
}

function optionalString(value: unknown, field: string): string | undefined {
  if (value === undefined || value === null) return undefined;
  return requiredString(value, field);
}

function optionalBoolean(value: unknown, field: string): boolean | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value !== 'boolean') throw new Error(`Invalid library filter field: ${field}`);
  return value;
}

function requiredNumber(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`Invalid library filter field: ${field}`);
  }
  return value;
}

function optionalNumber(value: unknown, field: string): number | undefined {
  if (value === undefined || value === null) return undefined;
  return requiredNumber(value, field);
}

function parseOption(value: unknown, requireCount = false): SmartFilterOption {
  if (!isObject(value)) throw new Error('Invalid library filter option');
  const count = optionalNumber(value.count, 'option.count');
  const rootPath = optionalString(value.rootPath, 'option.rootPath');
  if (requireCount && count === undefined) throw new Error('Invalid library filter option count');
  return {
    value: requiredString(value.value, 'option.value'),
    label: requiredString(value.label, 'option.label'),
    ...(count === undefined ? {} : { count }),
    ...(rootPath === undefined ? {} : { rootPath })
  };
}

function parseField(value: unknown): SmartFilterField {
  if (!isObject(value) || !Array.isArray(value.operators) || !Array.isArray(value.options)) {
    throw new Error('Invalid library filter field');
  }
  const fieldType = requiredString(value.type, 'field.type');
  if (!isSmartFilterFieldType(fieldType)) {
    throw new Error('Invalid library filter field type');
  }
  const optionSource = optionalString(value.optionSource, 'field.optionSource');
  const allowCustom = optionalBoolean(value.allowCustom, 'field.allowCustom');
  const unit = optionalString(value.unit, 'field.unit');
  const valueScale = optionalNumber(value.valueScale, 'field.valueScale');
  return {
    key: requiredString(value.key, 'field.key'),
    label: requiredString(value.label, 'field.label'),
    group: requiredString(value.group, 'field.group'),
    type: fieldType,
    operators: value.operators.map((operator) => requiredString(operator, 'field.operator')),
    options: value.options.map((option) => parseOption(option)),
    ...(optionSource === undefined ? {} : { optionSource }),
    ...(allowCustom === undefined ? {} : { allowCustom }),
    ...(unit === undefined ? {} : { unit }),
    ...(valueScale === undefined ? {} : { valueScale })
  };
}

export function parseLibraryFilterSchema(value: unknown): LibraryFilterSchema {
  if (!isObject(value) || !Array.isArray(value.fields)) {
    throw new Error('Invalid library filter schema response');
  }
  return {
    fields: value.fields.map(parseField),
    maxConditions: requiredNumber(value.maxConditions, 'maxConditions')
  };
}

export function parseLibraryFilterOptionPage(value: unknown): LibraryFilterOptionPage {
  if (!isObject(value) || !Array.isArray(value.options)) {
    throw new Error('Invalid library filter options response');
  }
  const source = requiredString(value.source, 'source');
  if (source !== 'authors' && source !== 'tags' && source !== 'series') {
    throw new Error('Invalid library filter option source');
  }
  if (typeof value.hasMore !== 'boolean' || typeof value.indexReady !== 'boolean') {
    throw new Error('Invalid library filter option state');
  }
  return {
    source,
    query: requiredString(value.query, 'query'),
    options: value.options.map((option) => {
      const parsed = parseOption(option, true);
      return { value: parsed.value, label: parsed.label, count: parsed.count ?? 0 };
    }),
    hasMore: value.hasMore,
    indexReady: value.indexReady
  };
}

async function readData(response: Response, fallback: string): Promise<unknown> {
  const payload: unknown = await response.json().catch(() => null);
  if (!isObject(payload) || payload.ok !== true || !('data' in payload)) {
    const message = isObject(payload) && isObject(payload.error) && typeof payload.error.message === 'string'
      ? payload.error.message
      : fallback;
    throw new Error(message);
  }
  if (!response.ok) throw new Error(fallback);
  return payload.data;
}

export async function fetchLibraryFilterSchema(signal?: AbortSignal): Promise<LibraryFilterSchema> {
  const response = await fetch('/api/library/filter-schema', {
    cache: 'no-store',
    credentials: 'same-origin',
    signal
  });
  return parseLibraryFilterSchema(await readData(response, '读取筛选维度失败'));
}

export async function fetchLibraryFilterOptions(
  source: LibraryFilterOptionSource,
  query: string,
  signal?: AbortSignal,
  limit = 20
): Promise<LibraryFilterOptionPage> {
  const params = new URLSearchParams({ source, query, limit: String(limit) });
  const response = await fetch(`/api/library/filter-options?${params}`, {
    cache: 'no-store',
    credentials: 'same-origin',
    signal
  });
  return parseLibraryFilterOptionPage(await readData(response, '读取筛选建议失败'));
}
