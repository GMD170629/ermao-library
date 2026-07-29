import type { BookshelfItem } from '../../../components/book/bookshelf';
import type { SmartShelfRules } from '../smart-shelf-rules';

export type ShelfKind = 'STATIC' | 'SMART' | 'COLLECTION';

export type ShelfView = {
  id: string;
  name: string;
  description: string | null;
  kind: ShelfKind;
  pinned?: boolean;
  createdAt: string;
  updatedAt: string;
  bookCount?: number;
  bookIds?: string[];
  books?: BookshelfItem[];
  collectionIds?: string[];
  shelfCount?: number;
  memberShelfIds?: string[];
  shelves?: ShelfView[];
  page?: number;
  pageSize?: number;
  total?: number;
  totalPages?: number;
  rules?: SmartShelfRules;
};

export type ShelfWriteInput = {
  name?: string;
  description?: string;
  kind?: ShelfKind;
  pinned?: boolean;
  bookIds?: string[];
  rules?: object;
  collectionIds?: string[];
  memberShelfIds?: string[];
};
