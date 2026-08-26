import type { BookView, ReadableResourceView } from '../../../types/book';
import type { SourceNodeMetadataCandidate } from './book-contents';

export type MetadataTargetScope = 'book' | 'resource';
export type RecognizedMetadataField =
  | 'book.title' | 'book.author' | 'book.description' | 'book.seriesName'
  | 'book.seriesIndex' | 'book.tags' | 'book.cover'
  | 'resource.title' | 'resource.description' | 'resource.publisher'
  | 'resource.publishedAt' | 'resource.language' | 'resource.isbn'
  | 'resource.identifier' | 'resource.narrator' | 'resource.abridged'
  | 'resource.resourceIndex' | 'resource.cover';

export type MetadataFieldDefinition = Readonly<{
  field: RecognizedMetadataField;
  group: MetadataTargetScope;
  label: string;
}>;

const bookFields: readonly MetadataFieldDefinition[] = [
  { field: 'book.title', group: 'book', label: '标题' },
  { field: 'book.author', group: 'book', label: '作者' },
  { field: 'book.description', group: 'book', label: '简介' },
  { field: 'book.seriesName', group: 'book', label: '系列名' },
  { field: 'book.seriesIndex', group: 'book', label: '系列序号' },
  { field: 'book.tags', group: 'book', label: '标签' },
  { field: 'book.cover', group: 'book', label: '封面' }
];

const resourceBookFields: readonly MetadataFieldDefinition[] = [
  { field: 'book.author', group: 'book', label: '作者' },
  { field: 'book.seriesName', group: 'book', label: '系列名' },
  { field: 'book.seriesIndex', group: 'book', label: '系列序号' },
  { field: 'book.tags', group: 'book', label: '标签' }
];

const resourceFields: readonly MetadataFieldDefinition[] = [
  { field: 'resource.title', group: 'resource', label: '卷标题' },
  { field: 'resource.description', group: 'resource', label: '简介' },
  { field: 'resource.publisher', group: 'resource', label: '出版社' },
  { field: 'resource.publishedAt', group: 'resource', label: '出版时间' },
  { field: 'resource.language', group: 'resource', label: '语言' },
  { field: 'resource.isbn', group: 'resource', label: 'ISBN' },
  { field: 'resource.identifier', group: 'resource', label: '标识符' },
  { field: 'resource.narrator', group: 'resource', label: '朗读者' },
  { field: 'resource.abridged', group: 'resource', label: '删节状态' },
  { field: 'resource.resourceIndex', group: 'resource', label: '卷号' },
  { field: 'resource.cover', group: 'resource', label: '封面' }
];

export function recognizedMetadataFields(scope: MetadataTargetScope): readonly MetadataFieldDefinition[] {
  return scope === 'book' ? bookFields : [...resourceBookFields, ...resourceFields];
}

export function candidateMetadataValue(candidate: SourceNodeMetadataCandidate | null, field: RecognizedMetadataField): unknown {
  if (!candidate) return null;
  if (field.endsWith('.title')) return candidate.title;
  if (field === 'book.author') return candidate.author;
  if (field.endsWith('.description')) return candidate.description;
  if (field === 'book.seriesName') return candidate.seriesName;
  if (field === 'book.seriesIndex') return candidate.seriesIndex;
  if (field === 'book.tags') return candidate.tags;
  if (field.endsWith('.cover')) return candidate.coverUrl;
  if (field === 'resource.publisher') return candidate.publisher;
  if (field === 'resource.publishedAt') return candidate.publishedAt;
  if (field === 'resource.language') return candidate.language;
  if (field === 'resource.isbn') return candidate.isbn;
  if (field === 'resource.identifier') return candidate.identifier;
  if (field === 'resource.narrator') return candidate.narrator;
  if (field === 'resource.abridged') return candidate.abridged;
  return candidate.resourceIndex;
}

export function currentMetadataValue(book: BookView, resource: ReadableResourceView | null, field: RecognizedMetadataField): unknown {
  if (field === 'book.title') return book.title;
  if (field === 'book.author') return book.author;
  if (field === 'book.description') return book.description;
  if (field === 'book.seriesName') return book.seriesName;
  if (field === 'book.seriesIndex') return book.seriesIndex;
  if (field === 'book.tags') return book.tags;
  if (field === 'book.cover') return book.coverUrl;
  if (!resource) return null;
  if (field === 'resource.title') return resource.title;
  if (field === 'resource.description') return resource.description;
  if (field === 'resource.publisher') return resource.publisher;
  if (field === 'resource.publishedAt') return resource.publishedAt;
  if (field === 'resource.language') return resource.language;
  if (field === 'resource.isbn') return resource.isbn;
  if (field === 'resource.identifier') return resource.identifier;
  if (field === 'resource.narrator') return resource.narrator;
  if (field === 'resource.abridged') return resource.abridged;
  if (field === 'resource.resourceIndex') return resource.resourceIndex;
  return resource.coverUrl;
}

export function hasMetadataValue(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0;
  return value !== null && value !== undefined && value !== '';
}

function normalized(value: unknown): string {
  if (Array.isArray(value)) return value.map((item) => String(item).trim().toLocaleLowerCase()).sort().join('\u0000');
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value ?? '').toLocaleLowerCase().replace(/[\s_\-.()[\]（）【】《》:：,，]+/g, '');
}

export function defaultRecognizedMetadataFields(
  book: BookView,
  resource: ReadableResourceView | null,
  candidate: SourceNodeMetadataCandidate | null,
  definitions: readonly MetadataFieldDefinition[]
): RecognizedMetadataField[] {
  if (!candidate) return [];
  return definitions.flatMap(({ field }) => {
    const value = candidateMetadataValue(candidate, field);
    return hasMetadataValue(value) && normalized(value) !== normalized(currentMetadataValue(book, resource, field)) ? [field] : [];
  });
}
