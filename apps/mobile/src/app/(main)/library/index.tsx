import { useRouter } from 'expo-router';
import type { ReactNode } from 'react';
import { Alert } from 'react-native';

import {
  BookshelfScreen,
  encodeBooksRouteQuery,
  useLibrary,
  type ShelfSummary,
} from '../../../features/library/public';
import { useI18n } from '../../../shared/i18n/public';
import {
  notifyOperationSucceeded,
  notifyOperationWarning,
} from '../../../shared/ui/public';

export default function BookshelfRoute(): ReactNode {
  const router = useRouter();
  const library = useLibrary();
  const { t } = useI18n();

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

  const confirmDelete = (shelf: ShelfSummary): void => {
    Alert.alert(
      t('library.shelves.deleteTitle'),
      t('library.shelves.deleteBody', { name: shelf.name }),
      [
        { style: 'cancel', text: t('common.cancel') },
        {
          onPress: () => {
            void library.deleteShelf(shelf.id).then((outcome) => {
              if (outcome.outcome === 'succeeded') {
                void notifyOperationSucceeded();
              } else {
                void notifyOperationWarning();
                Alert.alert(
                  t('library.issue.title'),
                  t('library.issue.shelfMutation'),
                );
              }
            });
          },
          style: 'destructive',
          text: t('library.shelves.deleteAction'),
        },
      ],
    );
  };

  return (
    <BookshelfScreen
      coverSource={library.coverSource}
      onCreateShelf={() => router.push('/library/shelf-editor')}
      onDeleteShelf={confirmDelete}
      onEditShelf={(shelf) =>
        router.push({
          pathname: '/library/shelf-editor',
          params: { shelfId: shelf.id },
        })
      }
      onImport={() => router.push('/library/import')}
      onOpenAllBooks={openAllBooks}
      onOpenCollection={(collectionId) =>
        router.push({
          pathname: '/library/collection/[collectionId]',
          params: { collectionId },
        })
      }
      onOpenShelf={openShelf}
      onRefresh={() => {
        void library.loadShelves();
      }}
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
  );
}
