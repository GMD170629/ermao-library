import type {
  LibraryCancellationFactory,
  LibraryCancellationSource,
  LibraryCoverStore,
  LibraryFilePicker,
  LibraryGateway,
  LibraryImportFile,
  ShelfMutationOutcome,
} from './ports';
import {
  DEFAULT_BOOKS_QUERY,
  isSupportedImportFileName,
  isImportTargetPathWithinRoot,
  normalizeBooksQuery,
  type BooksQuery,
  type LibraryContext,
  type LibraryFailure,
  type LibraryPreferences,
  type LibrarySnapshot,
  type ShelfOverviewState,
} from '../model/library';

type Listener = () => void;
type Scope =
  | 'books'
  | 'collection'
  | 'cover'
  | 'home'
  | 'import'
  | 'preferences'
  | 'shelves';
type OperationKey = Exclude<Scope, 'cover'> | `cover:${string}`;
type ActiveOperation = Readonly<{
  sequence: number;
  cancellation: LibraryCancellationSource;
}>;

export type LibraryControllerOptions = Readonly<{
  context: LibraryContext;
  filePicker: LibraryFilePicker;
  coverStore: LibraryCoverStore;
  onSessionExpired: () => void;
}>;

function withWarning<State extends Readonly<{ phase: 'ready' }>>(
  state: State,
  warning: LibraryFailure,
): State & Readonly<{ warning: LibraryFailure }> {
  return { ...state, warning };
}

function uniqueBooks<
  Book extends Readonly<{ id: string }>,
>(current: readonly Book[], next: readonly Book[]): Book[] {
  const seen = new Set(current.map((book) => book.id));
  return [...current, ...next.filter((book) => !seen.has(book.id))];
}

export class LibraryController {
  private state: LibrarySnapshot = {
    home: { phase: 'idle' },
    shelves: { phase: 'idle' },
    collection: { phase: 'idle' },
    books: { phase: 'idle', query: DEFAULT_BOOKS_QUERY },
    import: { phase: 'idle' },
    covers: {},
  };
  private readonly listeners = new Set<Listener>();
  private readonly operations = new Map<OperationKey, ActiveOperation>();
  private sequence = 0;
  private sessionExpiryReported = false;

  constructor(
    private readonly gateway: LibraryGateway,
    private readonly cancellations: LibraryCancellationFactory,
    private readonly options: LibraryControllerOptions,
  ) {}

  readonly getSnapshot = (): LibrarySnapshot => this.state;

  readonly subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  async start(): Promise<void> {
    const preferences = await this.restorePreferences();
    if (this.sessionExpiryReported) return;
    if (preferences !== null) {
      this.update({
        books: {
          phase: 'idle',
          query: { ...DEFAULT_BOOKS_QUERY, ...preferences },
        },
      });
    }
    await Promise.all([this.loadHome(), this.loadShelves(), this.loadBooks()]);
  }

  async loadHome(): Promise<void> {
    const operation = this.begin('home');
    const previous = this.state.home;
    this.update({
      home: previous.phase === 'ready'
        ? { ...previous, refreshing: true }
        : { phase: 'loading' },
    });
    const result = await this.gateway.loadHome(
      this.options.context.baseUrl,
      operation.cancellation.token,
    );
    if (!this.isCurrent('home', operation)) return;
    this.complete('home', operation);
    if (result.outcome === 'loaded') {
      this.update({ home: { phase: 'ready', data: result.value, refreshing: false } });
      return;
    }
    this.reportSessionExpiry(result.failure);
    this.update({
      home: previous.phase === 'ready'
        ? withWarning({ ...previous, refreshing: false }, result.failure)
        : { phase: 'failure', failure: result.failure },
    });
  }

  readonly refreshHome = (): Promise<void> => this.loadHome();

  async loadShelves(): Promise<void> {
    const operation = this.begin('shelves');
    const previous = this.state.shelves;
    this.update({
      shelves: previous.phase === 'ready'
        ? { ...previous, refreshing: true }
        : { phase: 'loading' },
    });
    const result = await this.gateway.loadShelves(
      this.options.context.baseUrl,
      operation.cancellation.token,
    );
    if (!this.isCurrent('shelves', operation)) return;
    this.complete('shelves', operation);
    if (result.outcome === 'loaded') {
      this.update({
        shelves: {
          phase: 'ready',
          data: result.value,
          refreshing: false,
          mutatingShelfId: null,
        },
      });
      return;
    }
    this.reportSessionExpiry(result.failure);
    this.update({
      shelves: previous.phase === 'ready'
        ? withWarning({ ...previous, refreshing: false }, result.failure)
        : { phase: 'failure', failure: result.failure },
    });
  }

  readonly refreshShelves = (): Promise<void> => this.loadShelves();

  async loadCollection(collectionId: string): Promise<void> {
    const normalizedId = collectionId.trim();
    if (normalizedId.length === 0 || normalizedId.length > 191) return;
    const operation = this.begin('collection');
    this.update({
      collection: { phase: 'loading', collectionId: normalizedId },
    });
    const result = await this.gateway.loadCollection(
      this.options.context.baseUrl,
      normalizedId,
      operation.cancellation.token,
    );
    if (!this.isCurrent('collection', operation)) return;
    this.complete('collection', operation);
    if (result.outcome === 'loaded') {
      this.update({ collection: { phase: 'ready', data: result.value } });
      return;
    }
    this.reportSessionExpiry(result.failure);
    this.update({
      collection: {
        phase: 'failure',
        collectionId: normalizedId,
        failure: result.failure,
      },
    });
  }

  closeCollection(): void {
    this.cancel('collection');
    this.update({ collection: { phase: 'idle' } });
  }

  async setBooksQuery(query: BooksQuery): Promise<void> {
    const normalized = normalizeBooksQuery(query);
    this.update({ books: { phase: 'idle', query: normalized } });
    await Promise.all([
      this.loadBooks(),
      this.persistPreferences({
        view: normalized.view,
        sort: normalized.sort,
        direction: normalized.direction,
      }),
    ]);
  }

  async loadBooks(): Promise<void> {
    const operation = this.begin('books');
    const previous = this.state.books;
    const query = previous.query;
    this.update({
      books: previous.phase === 'ready'
        ? { ...previous, refreshing: true, loadingNextPage: false }
        : { phase: 'loading', query },
    });
    const result = await this.gateway.loadBooks(
      this.options.context.baseUrl,
      query,
      1,
      operation.cancellation.token,
    );
    if (!this.isCurrent('books', operation)) return;
    this.complete('books', operation);
    if (result.outcome === 'loaded') {
      this.update({
        books: {
          phase: 'ready',
          query,
          ...result.value,
          refreshing: false,
          loadingNextPage: false,
        },
      });
      return;
    }
    this.reportSessionExpiry(result.failure);
    this.update({
      books: previous.phase === 'ready'
        ? withWarning(
            { ...previous, refreshing: false, loadingNextPage: false },
            result.failure,
          )
        : { phase: 'failure', query, failure: result.failure },
    });
  }

  async loadNextPage(): Promise<void> {
    const current = this.state.books;
    if (
      current.phase !== 'ready' || current.loadingNextPage || current.refreshing ||
      current.page >= current.totalPages
    ) {
      return;
    }
    const operation = this.begin('books');
    this.update({ books: { ...current, loadingNextPage: true } });
    const result = await this.gateway.loadBooks(
      this.options.context.baseUrl,
      current.query,
      current.page + 1,
      operation.cancellation.token,
    );
    if (!this.isCurrent('books', operation)) return;
    this.complete('books', operation);
    if (result.outcome === 'loaded') {
      this.update({
        books: {
          ...current,
          books: uniqueBooks(current.books, result.value.books),
          page: result.value.page,
          total: result.value.total,
          totalPages: result.value.totalPages,
          loadingNextPage: false,
        },
      });
      return;
    }
    this.reportSessionExpiry(result.failure);
    this.update({
      books: withWarning(
        { ...current, loadingNextPage: false },
        result.failure,
      ),
    });
  }

  async createShelf(name: string): Promise<ShelfMutationOutcome> {
    const normalized = name.trim();
    if (normalized.length === 0 || normalized.length > 200) {
      return {
        outcome: 'failed',
        failure: {
          operation: 'create-shelf',
          reason: 'invalid-request',
          code: 'INVALID_SHELF_NAME',
        },
      };
    }
    const operation = this.begin('shelves');
    const previous = this.state.shelves;
    if (previous.phase === 'ready') {
      this.update({ shelves: { ...previous, mutatingShelfId: 'new' } });
    }
    const result = await this.gateway.createShelf(
      this.options.context.baseUrl,
      normalized,
      operation.cancellation.token,
    );
    if (!this.isCurrent('shelves', operation)) {
      return {
        outcome: 'failed',
        failure: { operation: 'create-shelf', reason: 'cancelled' },
      };
    }
    this.complete('shelves', operation);
    if (result.outcome === 'loaded') {
      if (previous.phase === 'ready') {
        this.update({
          shelves: {
            ...previous,
            data: {
              ...previous.data,
              shelves: [...previous.data.shelves, result.value],
            },
            mutatingShelfId: null,
          },
        });
      } else {
        await this.loadShelves();
      }
      return { outcome: 'succeeded' };
    }
    this.reportShelfMutationFailure(previous, result.failure);
    return { outcome: 'failed', failure: result.failure };
  }

  async renameShelf(
    shelfId: string,
    name: string,
  ): Promise<ShelfMutationOutcome> {
    const normalizedShelfId = shelfId.trim();
    const normalized = name.trim();
    if (
      normalizedShelfId.length === 0 || normalizedShelfId.length > 191 ||
      normalized.length === 0 || normalized.length > 200
    ) {
      return {
        outcome: 'failed',
        failure: {
          operation: 'rename-shelf',
          reason: 'invalid-request',
          code: normalizedShelfId.length === 0 || normalizedShelfId.length > 191
            ? 'INVALID_SHELF_ID'
            : 'INVALID_SHELF_NAME',
        },
      };
    }
    const operation = this.begin('shelves');
    const previous = this.state.shelves;
    if (previous.phase === 'ready') {
      this.update({ shelves: { ...previous, mutatingShelfId: normalizedShelfId } });
    }
    const result = await this.gateway.renameShelf(
      this.options.context.baseUrl,
      normalizedShelfId,
      normalized,
      operation.cancellation.token,
    );
    if (!this.isCurrent('shelves', operation)) {
      return {
        outcome: 'failed',
        failure: { operation: 'rename-shelf', reason: 'cancelled' },
      };
    }
    this.complete('shelves', operation);
    if (result.outcome === 'loaded' && previous.phase === 'ready') {
      const replace = (shelf: typeof result.value): typeof result.value =>
        shelf.id === result.value.id ? result.value : shelf;
      this.update({
        shelves: {
          ...previous,
          data: {
            collections: previous.data.collections.map(replace),
            shelves: previous.data.shelves.map(replace),
          },
          mutatingShelfId: null,
        },
      });
      return { outcome: 'succeeded' };
    }
    if (result.outcome === 'loaded') {
      await this.loadShelves();
      return { outcome: 'succeeded' };
    }
    this.reportShelfMutationFailure(previous, result.failure);
    return { outcome: 'failed', failure: result.failure };
  }

  async deleteShelf(shelfId: string): Promise<ShelfMutationOutcome> {
    const normalizedShelfId = shelfId.trim();
    if (normalizedShelfId.length === 0 || normalizedShelfId.length > 191) {
      return {
        outcome: 'failed',
        failure: {
          operation: 'delete-shelf',
          reason: 'invalid-request',
          code: 'INVALID_SHELF_ID',
        },
      };
    }
    const operation = this.begin('shelves');
    const previous = this.state.shelves;
    if (previous.phase === 'ready') {
      this.update({ shelves: { ...previous, mutatingShelfId: normalizedShelfId } });
    }
    const result = await this.gateway.deleteShelf(
      this.options.context.baseUrl,
      normalizedShelfId,
      operation.cancellation.token,
    );
    if (!this.isCurrent('shelves', operation)) {
      return {
        outcome: 'failed',
        failure: { operation: 'delete-shelf', reason: 'cancelled' },
      };
    }
    this.complete('shelves', operation);
    if (result.outcome === 'loaded' && previous.phase === 'ready') {
      this.update({
        shelves: {
          ...previous,
          data: {
            collections: previous.data.collections.filter(
              (shelf) => shelf.id !== result.value.id,
            ),
            shelves: previous.data.shelves.filter(
              (shelf) => shelf.id !== result.value.id,
            ),
          },
          mutatingShelfId: null,
        },
      });
      return { outcome: 'succeeded' };
    }
    if (result.outcome === 'loaded') {
      await this.loadShelves();
      return { outcome: 'succeeded' };
    }
    this.reportShelfMutationFailure(previous, result.failure);
    return { outcome: 'failed', failure: result.failure };
  }

  async loadImportTargets(): Promise<void> {
    if (!this.options.context.canImport) {
      this.update({
        import: {
          phase: 'failure',
          failure: { operation: 'load-import-targets', reason: 'forbidden' },
        },
      });
      return;
    }
    const operation = this.begin('import');
    this.update({ import: { phase: 'loading-targets' } });
    const result = await this.gateway.loadImportTargets(
      this.options.context.baseUrl,
      operation.cancellation.token,
    );
    if (!this.isCurrent('import', operation)) return;
    this.complete('import', operation);
    if (result.outcome === 'loaded') {
      this.update({
        import: { phase: 'ready', targets: result.value, upload: { phase: 'idle' } },
      });
      return;
    }
    this.reportSessionExpiry(result.failure);
    this.update({ import: { phase: 'failure', failure: result.failure } });
  }

  async chooseAndImport(targetPath: string): Promise<void> {
    if (!this.options.context.canImport) return;
    const operation = this.begin('import');
    const picked = await this.options.filePicker.pickFiles();
    if (!this.isCurrent('import', operation)) return;
    if (picked.outcome === 'cancelled') {
      this.complete('import', operation);
      return;
    }
    if (picked.outcome === 'failed') {
      this.complete('import', operation);
      this.publishImportFailure({
        operation: 'import-files',
        reason: 'unknown',
        code: picked.reason,
      });
      return;
    }
    await this.importSelectedFiles(picked.files, targetPath, operation);
  }

  async importFiles(
    files: readonly LibraryImportFile[],
    targetPath: string,
  ): Promise<void> {
    const operation = this.begin('import');
    await this.importSelectedFiles(files, targetPath, operation);
  }

  async loadCover(bookId: string, coverUrl: string): Promise<void> {
    if (bookId.trim().length === 0 || coverUrl.trim().length === 0) return;
    const operationKey: OperationKey = `cover:${bookId}`;
    const operation = this.begin(operationKey);
    this.update({
      covers: { ...this.state.covers, [bookId]: { phase: 'loading' } },
    });
    const result = await this.gateway.loadCover(
      this.options.context.baseUrl,
      coverUrl,
      operation.cancellation.token,
    );
    if (!this.isCurrent(operationKey, operation)) return;
    if (result.outcome === 'failed') {
      this.complete(operationKey, operation);
      this.reportSessionExpiry(result.failure);
      this.update({
        covers: {
          ...this.state.covers,
          [bookId]: { phase: 'failure', failure: result.failure },
        },
      });
      return;
    }
    const stored = await this.options.coverStore.store(result.value);
    if (!this.isCurrent(operationKey, operation)) return;
    this.complete(operationKey, operation);
    this.update({
      covers: {
        ...this.state.covers,
        [bookId]: stored.outcome === 'stored'
          ? { phase: 'ready', source: stored.source }
          : {
              phase: 'failure',
              failure: {
                operation: 'load-cover',
                reason: 'unknown',
                code: stored.reason,
              },
            },
      },
    });
  }

  cancel(scope: Scope | 'all' = 'all'): void {
    if (scope === 'all') {
      for (const operation of this.operations.values()) operation.cancellation.cancel();
      this.operations.clear();
      this.sequence += 1;
      return;
    }
    if (scope === 'cover') {
      for (const [key, operation] of this.operations) {
        if (key.startsWith('cover:')) {
          operation.cancellation.cancel();
          this.operations.delete(key);
        }
      }
      this.sequence += 1;
      return;
    }
    const operation = this.operations.get(scope);
    operation?.cancellation.cancel();
    this.operations.delete(scope);
    this.sequence += 1;
  }

  async dispose(): Promise<void> {
    this.cancel('all');
    this.gateway.clearCoverCache(this.options.context.baseUrl);
    await this.options.coverStore.clearServer(this.options.context.baseUrl.value);
    this.listeners.clear();
  }

  private async restorePreferences(): Promise<LibraryPreferences | null> {
    const operation = this.begin('preferences');
    const result = await this.gateway.loadPreferences(
      this.options.context.baseUrl,
      operation.cancellation.token,
    );
    if (!this.isCurrent('preferences', operation)) return null;
    this.complete('preferences', operation);
    if (result.outcome === 'failed') this.reportSessionExpiry(result.failure);
    return result.outcome === 'loaded' ? result.value : null;
  }

  private async persistPreferences(preferences: LibraryPreferences): Promise<void> {
    const operation = this.begin('preferences');
    const result = await this.gateway.savePreferences(
      this.options.context.baseUrl,
      preferences,
      operation.cancellation.token,
    );
    if (!this.isCurrent('preferences', operation)) return;
    this.complete('preferences', operation);
    if (result.outcome === 'failed') this.reportSessionExpiry(result.failure);
  }

  private async importSelectedFiles(
    files: readonly LibraryImportFile[],
    targetPath: string,
    operation: ActiveOperation,
  ): Promise<void> {
    const current = this.state.import;
    if (
      !this.options.context.canImport || current.phase !== 'ready' ||
      files.length === 0 || files.length > 100 ||
      !current.targets.targets.some(
        (target) => isImportTargetPathWithinRoot(targetPath, target.rootPath),
      )
    ) {
      this.complete('import', operation);
      this.publishImportFailure({
        operation: 'import-files',
        reason: this.options.context.canImport ? 'invalid-request' : 'forbidden',
      });
      return;
    }
    const unsupported = files.find((file) => !isSupportedImportFileName(file.name));
    if (unsupported !== undefined) {
      this.complete('import', operation);
      this.publishImportFailure({
        operation: 'import-files',
        reason: 'invalid-request',
        code: 'UNSUPPORTED_FILE_EXTENSION',
      });
      return;
    }
    this.update({
      import: {
        ...current,
        upload: { phase: 'uploading', completedFiles: 0, totalFiles: files.length },
      },
    });
    const result = await this.gateway.importFiles(
      this.options.context.baseUrl,
      files,
      targetPath,
      operation.cancellation.token,
    );
    if (!this.isCurrent('import', operation)) return;
    this.complete('import', operation);
    if (result.outcome === 'loaded') {
      this.update({
        import: { ...current, upload: { phase: 'succeeded', result: result.value } },
      });
      await Promise.all([this.loadHome(), this.loadBooks()]);
      return;
    }
    this.reportSessionExpiry(result.failure);
    this.publishImportFailure(result.failure);
  }

  private publishImportFailure(failure: LibraryFailure): void {
    const current = this.state.import;
    this.update({
      import: current.phase === 'ready'
        ? { ...current, upload: { phase: 'failed', failure } }
        : { phase: 'failure', failure },
    });
  }

  private reportShelfMutationFailure(
    previous: ShelfOverviewState,
    failure: LibraryFailure,
  ): void {
    this.reportSessionExpiry(failure);
    this.update({
      shelves: previous.phase === 'ready'
        ? withWarning({ ...previous, mutatingShelfId: null }, failure)
        : { phase: 'failure', failure },
    });
  }

  private reportSessionExpiry(failure: LibraryFailure): void {
    if (failure.reason !== 'session-expired' || this.sessionExpiryReported) return;
    this.sessionExpiryReported = true;
    this.cancel('all');
    this.gateway.clearCoverCache(this.options.context.baseUrl);
    this.options.onSessionExpired();
  }

  private begin(scope: OperationKey): ActiveOperation {
    this.operations.get(scope)?.cancellation.cancel();
    const operation = {
      sequence: ++this.sequence,
      cancellation: this.cancellations.create(),
    };
    this.operations.set(scope, operation);
    return operation;
  }

  private isCurrent(scope: OperationKey, operation: ActiveOperation): boolean {
    return this.operations.get(scope)?.sequence === operation.sequence;
  }

  private complete(scope: OperationKey, operation: ActiveOperation): void {
    if (this.isCurrent(scope, operation)) this.operations.delete(scope);
  }

  private update(patch: Partial<LibrarySnapshot>): void {
    this.state = { ...this.state, ...patch };
    for (const listener of this.listeners) listener();
  }
}
