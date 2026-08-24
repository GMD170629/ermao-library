import type { BookView } from '../../../types/book';
import {
  fetchBook,
  removeBookCover,
  replaceBookTags,
  updateBookMetadata,
  uploadBookCover
} from '../api/client';

export type BookCoverChange =
  | Readonly<{ kind: 'keep' }>
  | Readonly<{ kind: 'replace'; file: File }>
  | Readonly<{ kind: 'remove' }>;

export type SaveBookMetadataInput = Readonly<{
  title: string;
  author: string;
  description: string;
  seriesName: string | null;
  seriesIndex: number | null;
  tags: readonly string[];
  cover: BookCoverChange;
}>;

export type BookMetadataSaveStage = 'metadata' | 'tags' | 'cover' | 'refresh';

export class BookMetadataSaveError extends Error {
  readonly stage: BookMetadataSaveStage;

  constructor(stage: BookMetadataSaveStage, cause: unknown) {
    super(`BOOK_METADATA_SAVE_${stage.toUpperCase()}_FAILED`, { cause });
    this.name = 'BookMetadataSaveError';
    this.stage = stage;
  }
}

export async function saveBookMetadata(book: BookView, input: SaveBookMetadataInput): Promise<BookView> {
  let updatedBook: BookView;
  try {
    updatedBook = await updateBookMetadata(book.id, {
      title: input.title,
      author: input.author,
      description: input.description,
      seriesName: input.seriesName,
      seriesIndex: input.seriesIndex
    });
  } catch (cause) {
    throw new BookMetadataSaveError('metadata', cause);
  }

  try {
    await replaceBookTags(book.id, book.tags, input.tags);
  } catch (cause) {
    throw new BookMetadataSaveError('tags', cause);
  }

  try {
    if (input.cover.kind === 'replace') await uploadBookCover(updatedBook, input.cover.file);
    if (input.cover.kind === 'remove') await removeBookCover(updatedBook);
  } catch (cause) {
    throw new BookMetadataSaveError('cover', cause);
  }

  try {
    return await fetchBook(book.id);
  } catch (cause) {
    throw new BookMetadataSaveError('refresh', cause);
  }
}
