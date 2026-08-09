import { useRouter } from 'expo-router';
import { useState, type ReactNode } from 'react';

import {
  BookshelfScreen,
  encodeBooksRouteQuery,
  LibraryImportModal,
  useLibrary,
  type ShelfSummary,
} from '../../../features/library/public';

export default function BookshelfRoute(): ReactNode {
  const router = useRouter();
  const library = useLibrary();
  const [importVisible, setImportVisible] = useState(false);

  const openShelf = (shelf: ShelfSummary): void => {
    router.push({
      pathname: '/library/books',
      params: encodeBooksRouteQuery({
        ...library.state.books.query,
        shelfId: shelf.id,
      }),
    });
  };

  const openAllBooks = (): void => {
    router.push({
      pathname: '/library/books',
      params: encodeBooksRouteQuery({
        ...library.state.books.query,
        shelfId: null,
      }),
    });
  };

  return (
    <>
      <BookshelfScreen
        collection={library.state.collection}
        coverSource={library.coverSource}
        onCloseCollection={library.closeCollection}
        onCreateShelf={library.createShelf}
        onDeleteShelf={library.deleteShelf}
        onImport={() => setImportVisible(true)}
        onOpenAllBooks={openAllBooks}
        onOpenCollection={(collectionId) => {
          void library.loadCollection(collectionId);
        }}
        onOpenShelf={openShelf}
        onRefresh={() => {
          void library.loadShelves();
        }}
        onRenameShelf={library.renameShelf}
        onRetry={() => {
          void library.loadShelves();
        }}
        onViewChange={(view) => {
          void library.setBooksQuery({
            ...library.state.books.query,
            view,
          });
        }}
        state={library.state.shelves}
        view={library.state.books.query.view}
      />
      <LibraryImportModal
        onClose={() => setImportVisible(false)}
        visible={importVisible}
      />
    </>
  );
}
