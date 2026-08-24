import type { BookshelfItem } from '../../../components/book/bookshelf';
import type { SmartShelfCondition, SmartShelfRules } from '../smart-shelf-rules';
import type { ShelfKind, ShelfView } from '../model/types';

type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== 'string') throw new Error(`Invalid shelf field: ${field}`);
  return value;
}

function optionalString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

function optionalNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function progressPercent(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error('Invalid shelf book progress');
  }
  return Math.max(0, Math.min(100, value));
}

function stringList(value: unknown): string[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string')) {
    throw new Error('Invalid shelf string list');
  }
  return value;
}

function shelfKind(value: unknown): ShelfKind {
  if (value === 'STATIC' || value === 'SMART' || value === 'COLLECTION') return value;
  if (value === undefined) return 'STATIC';
  throw new Error('Invalid shelf kind');
}

function parseBook(value: unknown): BookshelfItem {
  if (!isObject(value)) throw new Error('Invalid shelf book');
  return {
    id: requiredString(value.id, 'book.id'),
    title: requiredString(value.title, 'book.title'),
    author: typeof value.author === 'string' ? value.author : '',
    coverUrl: optionalString(value.coverUrl),
    progress: progressPercent(value.progress),
    gradient: optionalString(value.gradient),
    coverStatus: optionalString(value.coverStatus)
  };
}

function parseCondition(value: unknown): SmartShelfCondition {
  if (!isObject(value)) throw new Error('Invalid smart shelf condition');
  const rawValue = value.value;
  if (
    rawValue !== undefined
    && typeof rawValue !== 'string'
    && (!Array.isArray(rawValue) || rawValue.some((item) => typeof item !== 'string'))
  ) {
    throw new Error('Invalid smart shelf condition value');
  }
  return {
    field: requiredString(value.field, 'rules.conditions.field'),
    operator: requiredString(value.operator, 'rules.conditions.operator'),
    value: rawValue
  };
}

function parseRules(value: unknown): SmartShelfRules | undefined {
  if (value === undefined || value === null) return undefined;
  if (!isObject(value)) throw new Error('Invalid smart shelf rules');
  const conditions = value.conditions;
  if (conditions !== undefined && !Array.isArray(conditions)) {
    throw new Error('Invalid smart shelf conditions');
  }
  const combinator = value.combinator;
  if (combinator !== undefined && combinator !== 'ALL' && combinator !== 'ANY') {
    throw new Error('Invalid smart shelf combinator');
  }
  return {
    search: optionalString(value.search),
    statuses: stringList(value.statuses),
    tags: stringList(value.tags),
    authors: stringList(value.authors),
    publishers: stringList(value.publishers),
    combinator,
    conditions: conditions?.map(parseCondition)
  };
}

export function parseShelfView(value: unknown): ShelfView {
  if (!isObject(value)) throw new Error('Invalid shelf response');
  const description = value.description;
  if (description !== undefined && description !== null && typeof description !== 'string') {
    throw new Error('Invalid shelf description');
  }
  if (value.books !== undefined && !Array.isArray(value.books)) {
    throw new Error('Invalid shelf books');
  }
  if (value.shelves !== undefined && !Array.isArray(value.shelves)) {
    throw new Error('Invalid shelf members');
  }
  return {
    id: requiredString(value.id, 'id'),
    name: requiredString(value.name, 'name'),
    description: description ?? null,
    kind: shelfKind(value.kind),
    pinned: typeof value.pinned === 'boolean' ? value.pinned : undefined,
    createdAt: optionalString(value.createdAt) ?? '1970-01-01T00:00:00Z',
    updatedAt: optionalString(value.updatedAt) ?? '1970-01-01T00:00:00Z',
    bookCount: optionalNumber(value.bookCount),
    bookIds: stringList(value.bookIds),
    books: value.books?.map(parseBook),
    collectionIds: stringList(value.collectionIds),
    shelfCount: optionalNumber(value.shelfCount),
    memberShelfIds: stringList(value.memberShelfIds),
    shelves: value.shelves?.map(parseShelfView),
    page: optionalNumber(value.page),
    pageSize: optionalNumber(value.pageSize),
    total: optionalNumber(value.total),
    totalPages: optionalNumber(value.totalPages),
    rules: parseRules(value.rules),
    rulesStatus: value.rulesStatus === 'UNSUPPORTED' ? 'UNSUPPORTED' : 'VALID',
    unsupportedRuleFields: stringList(value.unsupportedRuleFields) ?? []
  };
}

export function parseShelfListPayload(value: unknown): { shelves: ShelfView[] } {
  if (!isObject(value) || !Array.isArray(value.shelves)) {
    throw new Error('Invalid shelf list response');
  }
  return { shelves: value.shelves.map(parseShelfView) };
}

export function parseShelfPayload(value: unknown): { shelf: ShelfView } {
  if (!isObject(value)) throw new Error('Invalid shelf response');
  return { shelf: parseShelfView(value.shelf) };
}

export function parseDeletedShelfPayload(value: unknown): { deleted: boolean; id: string } {
  if (!isObject(value) || typeof value.deleted !== 'boolean') {
    throw new Error('Invalid deleted shelf response');
  }
  return {
    deleted: value.deleted,
    id: requiredString(value.id, 'id')
  };
}

export function parseShelfEnvelope(
  value: unknown
): { ok: boolean; data?: unknown; error?: { message?: string; code?: string } } {
  if (!isObject(value) || typeof value.ok !== 'boolean') {
    throw new Error('Invalid shelf API envelope');
  }
  const error = isObject(value.error)
    ? {
        message: optionalString(value.error.message),
        code: optionalString(value.error.code)
      }
    : undefined;
  return { ok: value.ok, data: value.data, error };
}
