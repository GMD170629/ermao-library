export type BookContentSort = 'name-asc' | 'name-desc' | 'updated-desc' | 'updated-asc' | 'type-asc' | 'size-desc';
export type BookContentLayout = 'grid' | 'list';

export type BookContentEntry = Readonly<{
  sourceNodeId: string;
  parentSourceNodeId: string | null;
  name: string;
  title: string;
  description: string | null;
  kind: 'FOLDER' | 'FILE';
  physicalKind: 'REGULAR_FILE' | 'DIRECTORY' | 'SYMLINK' | 'OTHER';
  sizeBytes: number | null;
  observedAt: string;
  hasChildren: boolean;
  resourceId: string | null;
  representativeResourceId: string | null;
  coverUrl: string | null;
}>;

export type BookContentsPage = Readonly<{
  bookId: string;
  currentSourceNodeId: string | null;
  currentResourceId: string | null;
  currentNode: BookContentEntry | null;
  currentResourceIds: string[];
  parentSourceNodeId: string | null;
  breadcrumbs: BookContentEntry[];
  entries: BookContentEntry[];
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
}>;

export type SourceNodeMetadataCandidate = Readonly<{
  id: string;
  source: string;
  title: string | null;
  description: string | null;
  coverUrl: string | null;
  confidence: number;
}>;

export function bookContentSortQuery(sort: BookContentSort): Readonly<{ sort: 'name' | 'type' | 'updated' | 'size'; direction: 'asc' | 'desc' }> {
  if (sort === 'name-desc') return { sort: 'name', direction: 'desc' };
  if (sort === 'updated-desc') return { sort: 'updated', direction: 'desc' };
  if (sort === 'updated-asc') return { sort: 'updated', direction: 'asc' };
  if (sort === 'type-asc') return { sort: 'type', direction: 'asc' };
  if (sort === 'size-desc') return { sort: 'size', direction: 'desc' };
  return { sort: 'name', direction: 'asc' };
}

export function isDirectResourceEntry(entry: BookContentEntry): boolean {
  return Boolean(entry.resourceId);
}

export function isSourceDirectoryEntry(entry: BookContentEntry): boolean {
  return entry.kind === 'FOLDER' && !isDirectResourceEntry(entry);
}
