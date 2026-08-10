import type { ReactNode } from 'react';
import { fireEvent, render } from '@testing-library/react-native';

import { I18nProvider } from '../../../shared/i18n/public';
import { AppThemeProvider } from '../../../shared/ui/public';
import {
  DEFAULT_BOOKS_QUERY,
  type BooksState,
  type HomeState,
  type ImportState,
  type LibraryBook,
  type ShelfOverviewState,
  type ShelfSummary,
} from '../model/library';
import { BooksScreen } from './books-screen';
import { BookshelfScreen } from './bookshelf-screen';
import { ImportScreen } from './import-screen';
import { LibraryHomeScreen } from './library-home-screen';

let mockLanguageTag = 'en-US';

jest.mock('expo-localization', () => ({
  useLocales: () => [{ languageTag: mockLanguageTag }],
}));

const noOperation = (): void => undefined;

const book: LibraryBook = {
  id: 'book-1',
  title: 'Pride and Prejudice',
  author: 'Jane Austen',
  coverUrl: '',
  mediaKinds: ['EBOOK'],
};

const recentBook: LibraryBook = {
  ...book,
  id: 'book-2',
  title: 'A recently added title that must stay on one line',
  progressPercent: 37,
};

const unreadBook: LibraryBook = {
  ...book,
  id: 'book-3',
  title: 'An unread title',
  progressPercent: 0,
};

const shelf: ShelfSummary = {
  id: 'shelf-1',
  name: 'Weekend reading',
  description: null,
  kind: 'STATIC',
  pinned: false,
  bookCount: 1,
  shelfCount: 0,
  books: [book],
  memberShelfIds: [],
  updatedAt: '2026-08-09T00:00:00Z',
};

const collection: ShelfSummary = {
  ...shelf,
  id: 'collection-1',
  name: 'Summer',
  kind: 'COLLECTION',
  bookCount: 0,
  shelfCount: 2,
  books: [],
  memberShelfIds: ['shelf-1'],
};

function Fixture({ children }: Readonly<{ children: ReactNode }>): ReactNode {
  return (
    <AppThemeProvider colorScheme="light">
      <I18nProvider>{children}</I18nProvider>
    </AppThemeProvider>
  );
}

describe('mobile library screens', () => {
  beforeEach(() => {
    mockLanguageTag = 'en-US';
  });

  test('renders the Home reading entry and progress-only bookshelf rails', async () => {
    const onOpenBooks = jest.fn();
    const onContinueReading = jest.fn();
    const onOpenRecentBooks = jest.fn();
    const onOpenRecentReading = jest.fn();
    const home: HomeState = {
      phase: 'ready',
      refreshing: false,
      data: {
        summary: {
          totalBooks: 12,
          unreadBooks: 7,
          ebookBooks: 12,
          comicBooks: 0,
          audiobookBooks: 0,
        },
        continueReading: {
          ...book,
          readerType: 'reflowable',
          resumeVolumeId: 'volume-1',
          progressPercent: 42,
          chapter: 'Chapter 3',
          volumeTitle: null,
          lastReadAt: '2026-08-09T00:00:00Z',
        },
        recentReading: [recentBook],
        recentBooks: [recentBook, unreadBook],
        unavailableSections: ['unread'],
      },
    };
    const view = await render(
      <Fixture>
        <LibraryHomeScreen
          importState={{
            phase: 'ready',
            targets: { selectedTargetPath: null, targets: [] },
            upload: {
              phase: 'succeeded',
              result: {
                saved: 2,
                autoImport: true,
                files: [],
              },
            },
          }}
          onContinueReading={onContinueReading}
          onImport={noOperation}
          onOpenBooks={onOpenBooks}
          onOpenRecentBooks={onOpenRecentBooks}
          onOpenRecentReading={onOpenRecentReading}
          onRefresh={noOperation}
          onRetry={noOperation}
          state={home}
        />
      </Fixture>,
    );

    expect(view.getByText('12 books · 7 unread')).toBeOnTheScreen();
    expect(
      view.getByText(
        'Some content was not updated. The last successfully loaded results remain visible.',
      ),
    ).toBeOnTheScreen();
    expect(view.getByText('Files saved and being added')).toBeOnTheScreen();
    expect(
      view.getByText(
        'Saved 2 files. The library is organizing them in the background.',
      ),
    ).toBeOnTheScreen();
    expect(view.queryByText('Chapter 3')).toBeNull();
    expect(
      view.getAllByText(recentBook.title).every((title) =>
        title.props.numberOfLines === 1,
      ),
    ).toBe(true);
    const shelfProgress = view.getAllByLabelText('Reading progress 37%');
    expect(shelfProgress).toHaveLength(2);
    for (const progress of shelfProgress) {
      expect(progress).toHaveProp('accessibilityRole', 'progressbar');
      expect(progress).toHaveProp('accessibilityValue', {
        max: 100,
        min: 0,
        now: 37,
      });
    }
    expect(view.queryByText('37% read')).toBeNull();
    expect(view.queryByLabelText('Reading progress 0%')).toBeNull();

    const shelfLedges = view.getAllByTestId('home-shelf-ledge', {
      includeHiddenElements: true,
    });
    expect(shelfLedges).toHaveLength(2);
    for (const ledge of shelfLedges) {
      expect(ledge).toHaveStyle({
        height: 17,
        marginTop: -3,
        zIndex: 1,
      });
    }

    const shelfCoverRows = view.getAllByTestId('home-shelf-covers');
    expect(shelfCoverRows).toHaveLength(2);
    for (const coverRow of shelfCoverRows) {
      expect(coverRow).toHaveStyle({ zIndex: 3 });
    }

    const shelfMetadataItems = view.getAllByTestId(
      'home-shelf-metadata-items',
    );
    expect(shelfMetadataItems).toHaveLength(2);
    for (const metadataItems of shelfMetadataItems) {
      expect(metadataItems).toHaveStyle({ paddingHorizontal: 8 });
    }

    const shelfMetadataSurfaces = view.getAllByTestId(
      'home-shelf-metadata-surface',
      { includeHiddenElements: true },
    );
    expect(shelfMetadataSurfaces).toHaveLength(2);
    for (const surface of shelfMetadataSurfaces) {
      expect(surface).toHaveStyle({
        backgroundColor: '#E6E1DB',
        opacity: 0.38,
      });
    }

    const seeAllActions = view.getAllByRole('button', {
      name: 'See all',
    });
    expect(seeAllActions).toHaveLength(3);
    const continueSeeAll = seeAllActions[0];
    if (continueSeeAll === undefined) {
      throw new Error('Expected the continue-reading See all action');
    }
    await fireEvent.press(continueSeeAll);
    expect(onOpenRecentReading).toHaveBeenCalledTimes(1);
    const recentReadingSeeAll = seeAllActions[1];
    const recentBooksSeeAll = seeAllActions[2];
    if (recentReadingSeeAll === undefined || recentBooksSeeAll === undefined) {
      throw new Error('Expected both bookshelf See all actions');
    }
    await fireEvent.press(recentReadingSeeAll);
    await fireEvent.press(recentBooksSeeAll);
    expect(onOpenRecentReading).toHaveBeenCalledTimes(2);
    expect(onOpenRecentBooks).toHaveBeenCalledTimes(1);

    const continueActions = view.getAllByRole('button', {
      name: 'Continue reading Pride and Prejudice',
    });
    expect(continueActions).toHaveLength(2);
    for (const action of continueActions) await fireEvent.press(action);
    expect(onContinueReading).toHaveBeenCalledTimes(2);
    expect(onContinueReading).toHaveBeenNthCalledWith(
      1,
      home.data.continueReading,
    );
  });

  test('uses the deliberate Chinese empty Home subtitle and import action', async () => {
    mockLanguageTag = 'zh-CN';
    const onImport = jest.fn();
    const view = await render(
      <Fixture>
        <LibraryHomeScreen
          importState={{ phase: 'idle' }}
          onContinueReading={noOperation}
          onImport={onImport}
          onOpenBooks={noOperation}
          onOpenRecentBooks={noOperation}
          onOpenRecentReading={noOperation}
          onRefresh={noOperation}
          onRetry={noOperation}
          state={{
            phase: 'ready',
            refreshing: false,
            data: {
              summary: {
                totalBooks: 0,
                unreadBooks: 0,
                ebookBooks: 0,
                comicBooks: 0,
                audiobookBooks: 0,
              },
              continueReading: null,
              recentReading: [],
              recentBooks: [],
              unavailableSections: [],
            },
          }}
        />
      </Fixture>,
    );

    expect(view.getAllByText('从一本书开始').length).toBeGreaterThan(0);
    expect(view.queryByText('0 本书 · 0 本未读')).toBeNull();
    await fireEvent.press(view.getByRole('button', { name: '导入书籍' }));
    expect(onImport).toHaveBeenCalledTimes(1);
  });

  test('supports shelf creation and collection drill-in as explicit actions', async () => {
    const onCreateShelf = jest.fn();
    const onOpenCollection = jest.fn();
    const state: ShelfOverviewState = {
      phase: 'ready',
      refreshing: false,
      mutatingShelfId: null,
      data: { collections: [collection], shelves: [shelf] },
    };
    const view = await render(
      <Fixture>
        <BookshelfScreen
          onCreateShelf={onCreateShelf}
          onDeleteShelf={noOperation}
          onEditShelf={noOperation}
          onImport={noOperation}
          onOpenAllBooks={noOperation}
          onOpenCollection={onOpenCollection}
          onOpenShelf={noOperation}
          onRefresh={noOperation}
          onRetry={noOperation}
          onViewChange={noOperation}
          state={state}
          view="grid"
        />
      </Fixture>,
    );

    await fireEvent.press(
      view.getByRole('button', { name: 'Summer, 2 shelves' }),
    );
    expect(onOpenCollection).toHaveBeenCalledWith('collection-1');

    await fireEvent.press(
      view.getByRole('menuitem', { name: 'Create shelf' }),
    );
    expect(onCreateShelf).toHaveBeenCalledTimes(1);
  });

  test('keeps shelf creation and import as visible native menu actions', async () => {
    const onCreateShelf = jest.fn();
    const onImport = jest.fn();
    const view = await render(
      <Fixture>
        <BookshelfScreen
          onCreateShelf={onCreateShelf}
          onDeleteShelf={noOperation}
          onEditShelf={noOperation}
          onImport={onImport}
          onOpenAllBooks={noOperation}
          onOpenCollection={noOperation}
          onOpenShelf={noOperation}
          onRefresh={noOperation}
          onRetry={noOperation}
          onViewChange={noOperation}
          state={{
            phase: 'ready',
            refreshing: false,
            mutatingShelfId: null,
            data: { collections: [], shelves: [] },
          }}
          view="grid"
        />
      </Fixture>,
    );

    await fireEvent.press(
      view.getByRole('menuitem', { name: 'Import books' }),
    );
    expect(onImport).toHaveBeenCalledTimes(1);
    expect(onCreateShelf).not.toHaveBeenCalled();
  });

  test('emits typed book filters while books remain informational', async () => {
    const onQueryChange = jest.fn();
    const books: BooksState = {
      phase: 'ready',
      query: DEFAULT_BOOKS_QUERY,
      books: [book],
      page: 1,
      pageSize: 24,
      total: 1,
      totalPages: 1,
      refreshing: false,
      loadingNextPage: false,
    };
    const view = await render(
      <Fixture>
        <BooksScreen
          onLoadNextPage={noOperation}
          onQueryChange={onQueryChange}
          onRefresh={noOperation}
          onRetry={noOperation}
          state={books}
        />
      </Fixture>,
    );

    await fireEvent.press(view.getByRole('menuitem', { name: 'Unread' }));
    expect(onQueryChange).toHaveBeenCalledWith({
      ...DEFAULT_BOOKS_QUERY,
      status: 'UNREAD',
    });
    expect(
      view.queryByRole('button', { name: /Pride and Prejudice/u }),
    ).toBeNull();
  });

  test('preserves a nested import preference and exposes upload cancellation', async () => {
    const onChooseFiles = jest.fn();
    const ready: ImportState = {
      phase: 'ready',
      targets: {
        selectedTargetPath: '/library/inbox/english',
        targets: [
          {
            folderId: 'folder-1',
            name: 'Inbox',
            rootPath: '/library/inbox',
            enabled: true,
          },
        ],
      },
      upload: { phase: 'idle' },
    };
    const view = await render(
      <Fixture>
        <ImportScreen
          onCancel={noOperation}
          onChooseFiles={onChooseFiles}
          onLoadTargets={noOperation}
          state={ready}
        />
      </Fixture>,
    );

    expect(view.getByRole('button', { name: 'Inbox' })).toBeOnTheScreen();
    await fireEvent.press(
      view.getByRole('button', { name: 'Choose book files' }),
    );
    expect(onChooseFiles).toHaveBeenCalledWith('/library/inbox/english');

    const onCancel = jest.fn();
    const uploading = await render(
      <Fixture>
        <ImportScreen
          onCancel={onCancel}
          onChooseFiles={noOperation}
          onLoadTargets={noOperation}
          state={{
            ...ready,
            upload: { phase: 'uploading', completedFiles: 1, totalFiles: 2 },
          }}
        />
      </Fixture>,
    );
    await fireEvent.press(
      uploading.getByRole('button', { name: 'Cancel' }),
    );
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
