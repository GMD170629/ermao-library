import { useRouter } from 'expo-router';
import type { ReactNode } from 'react';

import {
  encodeBooksRouteQuery,
  LibraryHomeScreen,
  type ContinueReadingBook,
  useLibrary,
} from '../../../features/library/public';

export default function HomeRoute(): ReactNode {
  const router = useRouter();
  const library = useLibrary();

  function openBooks(sort: 'recent_import' | 'recent_read'): void {
    router.push({
      pathname: '/library/books',
      params: encodeBooksRouteQuery({
        ...library.state.books.query,
        direction: 'desc',
        shelfId: null,
        sort,
      }),
    });
  }

  function continueReading(book: ContinueReadingBook): void {
    router.push({
      pathname: '/reader',
      params: {
        workId: book.id,
        ...(book.resumeVolumeId === null
          ? {}
          : { volumeId: book.resumeVolumeId }),
      },
    });
  }

  return (
    <LibraryHomeScreen
      coverSource={library.coverSource}
      importState={library.state.import}
      onContinueReading={continueReading}
      onImport={() => router.push('/library/import')}
      onOpenBooks={() =>
        router.push({
          pathname: '/library/books',
          params: encodeBooksRouteQuery({
            ...library.state.books.query,
            shelfId: null,
          }),
        })
      }
      onOpenRecentBooks={() => openBooks('recent_import')}
      onOpenRecentReading={() => openBooks('recent_read')}
      onRefresh={() => {
        void library.loadHome();
      }}
      onRetry={() => {
        void library.loadHome();
      }}
      state={library.state.home}
    />
  );
}
