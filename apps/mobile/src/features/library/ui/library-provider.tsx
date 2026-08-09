import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from 'react';

import type { LibraryController } from '../application/library-controller';
import type { ShelfMutationOutcome } from '../application/ports';
import type {
  BooksQuery,
  LibraryBook,
  LibrarySnapshot,
} from '../model/library';
import type { LibraryCoverSource } from './library-primitives';

export type LibraryContextValue = Readonly<{
  cancelImport(): void;
  chooseAndImport(targetPath: string): Promise<void>;
  closeCollection(): void;
  coverSource(book: LibraryBook): LibraryCoverSource;
  createShelf(name: string): Promise<ShelfMutationOutcome>;
  deleteShelf(shelfId: string): Promise<ShelfMutationOutcome>;
  loadBooks(): Promise<void>;
  loadCollection(collectionId: string): Promise<void>;
  loadHome(): Promise<void>;
  loadImportTargets(): Promise<void>;
  loadNextPage(): Promise<void>;
  loadShelves(): Promise<void>;
  renameShelf(
    shelfId: string,
    name: string,
  ): Promise<ShelfMutationOutcome>;
  setBooksQuery(query: BooksQuery): Promise<void>;
  state: LibrarySnapshot;
}>;

const LibraryContext = createContext<LibraryContextValue | null>(null);

export type LibraryProviderProps = Readonly<{
  children: ReactNode;
  controller: LibraryController;
}>;

export function LibraryProvider({
  children,
  controller,
}: LibraryProviderProps): ReactNode {
  const state = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );

  useEffect(() => {
    void controller.start();
    return () => {
      void controller.dispose();
    };
  }, [controller]);

  useEffect(() => {
    for (const book of visibleBooks(state)) {
      if (
        book.coverUrl.trim().length > 0 &&
        state.covers[book.id] === undefined
      ) {
        void controller.loadCover(book.id, book.coverUrl);
      }
    }
  }, [controller, state]);

  const actions = useMemo<Omit<LibraryContextValue, 'state'>>(
    () => ({
      cancelImport: () => controller.cancel('import'),
      chooseAndImport: (targetPath) =>
        controller.chooseAndImport(targetPath),
      closeCollection: () => controller.closeCollection(),
      coverSource: (book) => {
        const cover = controller.getSnapshot().covers[book.id];
        return cover?.phase === 'ready'
          ? { uri: cover.source.uri }
          : undefined;
      },
      createShelf: (name) => controller.createShelf(name),
      deleteShelf: (shelfId) => controller.deleteShelf(shelfId),
      loadBooks: () => controller.loadBooks(),
      loadCollection: (collectionId) =>
        controller.loadCollection(collectionId),
      loadHome: () => controller.loadHome(),
      loadImportTargets: () => controller.loadImportTargets(),
      loadNextPage: () => controller.loadNextPage(),
      loadShelves: () => controller.loadShelves(),
      renameShelf: (shelfId, name) =>
        controller.renameShelf(shelfId, name),
      setBooksQuery: (query) => controller.setBooksQuery(query),
    }),
    [controller],
  );
  const value = useMemo<LibraryContextValue>(
    () => ({ state, ...actions }),
    [actions, state],
  );

  return (
    <LibraryContext.Provider value={value}>
      {children}
    </LibraryContext.Provider>
  );
}

export function useLibrary(): LibraryContextValue {
  const value = useContext(LibraryContext);
  if (value === null) {
    throw new Error('useLibrary must be used within LibraryProvider');
  }
  return value;
}

function visibleBooks(state: LibrarySnapshot): readonly LibraryBook[] {
  const books = new Map<string, LibraryBook>();
  if (state.home.phase === 'ready') {
    if (state.home.data.continueReading !== null) {
      books.set(
        state.home.data.continueReading.id,
        state.home.data.continueReading,
      );
    }
    for (const book of state.home.data.recentBooks) books.set(book.id, book);
  }
  if (state.shelves.phase === 'ready') {
    for (const shelf of [
      ...state.shelves.data.collections,
      ...state.shelves.data.shelves,
    ]) {
      for (const book of shelf.books) books.set(book.id, book);
    }
  }
  if (state.collection.phase === 'ready') {
    for (const shelf of state.collection.data.shelves) {
      for (const book of shelf.books) books.set(book.id, book);
    }
  }
  if (state.books.phase === 'ready') {
    for (const book of state.books.books) books.set(book.id, book);
  }
  return [...books.values()];
}
