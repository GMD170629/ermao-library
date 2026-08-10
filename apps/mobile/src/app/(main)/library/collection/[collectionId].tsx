import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, type ReactNode } from 'react';

import {
  encodeBooksRouteQuery,
  LibraryCollectionScreen,
  useLibrary,
  type ShelfSummary,
} from '../../../../features/library/public';
import { useI18n } from '../../../../shared/i18n/public';

export default function CollectionRoute(): ReactNode {
  const { collectionId } = useLocalSearchParams<{ collectionId: string }>();
  const router = useRouter();
  const library = useLibrary();
  const { closeCollection, loadCollection } = library;
  const { t } = useI18n();

  useEffect(() => {
    void loadCollection(collectionId);
    return closeCollection;
  }, [closeCollection, collectionId, loadCollection]);

  const collection = library.state.collection;
  if (collection.phase === 'idle') return null;

  const openShelf = (shelf: ShelfSummary): void => {
    router.push({
      pathname: '/library/books',
      params: encodeBooksRouteQuery({
        ...library.state.books.query,
        shelfId: shelf.id,
      }),
    });
  };

  return (
    <>
      <Stack.Screen
        options={{
          title:
            collection.phase === 'ready'
              ? collection.data.name
              : t('library.shelves.collectionTitle'),
        }}
      />
      <LibraryCollectionScreen
        collection={collection}
        coverSource={library.coverSource}
        onOpenCollection={(id) => {
          void library.loadCollection(id);
        }}
        onOpenShelf={openShelf}
        view={library.state.books.query.view}
      />
    </>
  );
}
