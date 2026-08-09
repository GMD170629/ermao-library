import type { ReactNode } from 'react';
import { fireEvent, render, waitFor } from '@testing-library/react-native';

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
const successfulMutation = async () =>
  Promise.resolve({ outcome: 'succeeded' as const });

const book: LibraryBook = {
  id: 'book-1',
  title: 'Pride and Prejudice',
  author: 'Jane Austen',
  coverUrl: '',
  mediaKinds: ['EBOOK'],
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

  test('renders dynamic Home data and keeps book content noninteractive', async () => {
    const onToggleTheme = jest.fn();
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
        recentBooks: [book],
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
          onImport={noOperation}
          onOpenBooks={noOperation}
          onRefresh={noOperation}
          onRetry={noOperation}
          onToggleTheme={onToggleTheme}
          state={home}
          themeMode="light"
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
    expect(
      view.getByLabelText('Pride and Prejudice, Jane Austen'),
    ).not.toHaveProp('accessibilityRole', 'button');
    expect(
      view.queryByRole('button', { name: /Pride and Prejudice/u }),
    ).toBeNull();

    await fireEvent.press(
      view.getByRole('button', { name: 'Use dark appearance' }),
    );
    expect(onToggleTheme).toHaveBeenCalledTimes(1);

    await fireEvent.press(
      view.getByRole('button', { name: 'Continue reading' }),
    );
    expect(
      view.getByText('Reading is not available yet'),
    ).toBeOnTheScreen();
  });

  test('uses the deliberate Chinese empty Home subtitle and import action', async () => {
    mockLanguageTag = 'zh-CN';
    const onImport = jest.fn();
    const view = await render(
      <Fixture>
        <LibraryHomeScreen
          importState={{ phase: 'idle' }}
          onImport={onImport}
          onOpenBooks={noOperation}
          onRefresh={noOperation}
          onRetry={noOperation}
          onToggleTheme={noOperation}
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
              recentBooks: [],
              unavailableSections: [],
            },
          }}
          themeMode="light"
        />
      </Fixture>,
    );

    expect(view.getAllByText('从一本书开始').length).toBeGreaterThan(0);
    expect(view.queryByText('0 本书 · 0 本未读')).toBeNull();
    await fireEvent.press(view.getByRole('button', { name: '导入书籍' }));
    expect(onImport).toHaveBeenCalledTimes(1);
  });

  test('supports shelf creation and collection drill-in as explicit actions', async () => {
    const onCreateShelf = jest.fn().mockResolvedValue({
      outcome: 'succeeded',
    });
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
          collection={{ phase: 'idle' }}
          onCloseCollection={noOperation}
          onCreateShelf={onCreateShelf}
          onDeleteShelf={successfulMutation}
          onImport={noOperation}
          onOpenAllBooks={noOperation}
          onOpenCollection={onOpenCollection}
          onOpenShelf={noOperation}
          onRefresh={noOperation}
          onRenameShelf={successfulMutation}
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
      view.getByRole('button', { name: 'Add a shelf or import books' }),
    );
    await fireEvent.changeText(
      view.getByLabelText('Shelf name'),
      'Classics',
    );
    await fireEvent.press(
      view.getByRole('button', { name: 'Create shelf' }),
    );
    expect(onCreateShelf).toHaveBeenCalledWith('Classics');
    await waitFor(() => {
      expect(view.queryByText('Add to your library')).toBeNull();
    });
  });

  test('keeps shelf input and modal context after a named mutation failure', async () => {
    const onCreateShelf = jest.fn().mockResolvedValue({
      outcome: 'failed',
      failure: { operation: 'create-shelf', reason: 'network' },
    });
    const view = await render(
      <Fixture>
        <BookshelfScreen
          collection={{ phase: 'idle' }}
          onCloseCollection={noOperation}
          onCreateShelf={onCreateShelf}
          onDeleteShelf={successfulMutation}
          onImport={noOperation}
          onOpenAllBooks={noOperation}
          onOpenCollection={noOperation}
          onOpenShelf={noOperation}
          onRefresh={noOperation}
          onRenameShelf={successfulMutation}
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
      view.getByRole('button', { name: 'Add a shelf or import books' }),
    );
    const field = view.getByLabelText('Shelf name');
    await fireEvent.changeText(field, 'Classics');
    await fireEvent.press(
      view.getByRole('button', { name: 'Create shelf' }),
    );

    await waitFor(() => {
      expect(
        view.getByText('The bookshelf change did not finish. Try again shortly.'),
      ).toBeOnTheScreen();
    });
    expect(view.getByLabelText('Shelf name')).toHaveProp('value', 'Classics');
    expect(view.getByText('Add to your library')).toBeOnTheScreen();
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
          onBack={noOperation}
          onLoadNextPage={noOperation}
          onQueryChange={onQueryChange}
          onRefresh={noOperation}
          onRetry={noOperation}
          state={books}
        />
      </Fixture>,
    );

    await fireEvent.press(view.getByRole('tab', { name: 'Unread' }));
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
          onBack={noOperation}
          onCancel={noOperation}
          onChooseFiles={onChooseFiles}
          onLoadTargets={noOperation}
          state={ready}
        />
      </Fixture>,
    );

    expect(view.getByRole('radio', { name: 'Inbox' })).toHaveProp(
      'accessibilityState',
      { checked: true, disabled: false },
    );
    await fireEvent.press(
      view.getByRole('button', { name: 'Choose book files' }),
    );
    expect(onChooseFiles).toHaveBeenCalledWith('/library/inbox/english');

    const onCancel = jest.fn();
    const uploading = await render(
      <Fixture>
        <ImportScreen
          onBack={noOperation}
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
