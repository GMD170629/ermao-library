import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useMemo, type ReactNode } from 'react';

import {
  BooksScreen,
  booksQueriesMatch,
  booksRouteParametersMatch,
  decodeBooksRouteQuery,
  encodeBooksRouteQuery,
  useLibrary,
  type BooksRouteParameters,
  type ShelfSummary,
} from '../../../features/library/public';

export default function BooksRoute(): ReactNode {
  const router = useRouter();
  const parameters: BooksRouteParameters = useLocalSearchParams();
  const {
    direction,
    mediaKind,
    search,
    shelfId,
    sort,
    status,
    view,
  } = parameters;
  const {
    coverSource,
    loadBooks,
    loadNextPage,
    setBooksQuery,
    state,
  } = useLibrary();
  const currentQuery = state.books.query;
  const routeParameters = useMemo<BooksRouteParameters>(
    () => ({ direction, mediaKind, search, shelfId, sort, status, view }),
    [direction, mediaKind, search, shelfId, sort, status, view],
  );
  const requestedQuery = useMemo(
    () => decodeBooksRouteQuery(routeParameters, currentQuery),
    [currentQuery, routeParameters],
  );
  const encodedQuery = useMemo(
    () => encodeBooksRouteQuery(requestedQuery),
    [requestedQuery],
  );

  useEffect(() => {
    if (!booksRouteParametersMatch(routeParameters, encodedQuery)) {
      router.setParams(encodedQuery);
    }
    if (!booksQueriesMatch(currentQuery, requestedQuery)) {
      void setBooksQuery(requestedQuery);
    }
  }, [
    currentQuery,
    encodedQuery,
    requestedQuery,
    routeParameters,
    router,
    setBooksQuery,
  ]);

  const shelf = findShelf(state, requestedQuery.shelfId);
  return (
    <BooksScreen
      coverSource={coverSource}
      onBack={() => {
        if (router.canGoBack()) router.back();
        else router.replace('/library');
      }}
      onLoadNextPage={() => {
        void loadNextPage();
      }}
      onQueryChange={(query) => {
        router.setParams(encodeBooksRouteQuery(query));
        void setBooksQuery(query);
      }}
      onRefresh={() => {
        void loadBooks();
      }}
      onRetry={() => {
        void loadBooks();
      }}
      {...(shelf === undefined ? {} : { shelfName: shelf.name })}
      state={state.books}
    />
  );
}

function findShelf(
  state: ReturnType<typeof useLibrary>['state'],
  shelfId: string | null,
): ShelfSummary | undefined {
  if (shelfId === null) return undefined;
  const shelves =
    state.shelves.phase === 'ready'
      ? [
          ...state.shelves.data.collections,
          ...state.shelves.data.shelves,
        ]
      : [];
  const collectionShelves =
    state.collection.phase === 'ready'
      ? state.collection.data.shelves
      : [];
  return [...shelves, ...collectionShelves].find(
    (candidate) => candidate.id === shelfId,
  );
}
