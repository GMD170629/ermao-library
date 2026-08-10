export const LIBRARY_QUERY_DEBOUNCE_MS = 250;

export type LibraryQueryDraft = {
  search: string;
  smartFilterQuery: string;
};

type Schedule = (callback: () => void, delayMs: number) => () => void;

function scheduleTimeout(callback: () => void, delayMs: number): () => void {
  const timer = globalThis.setTimeout(callback, delayMs);
  return () => globalThis.clearTimeout(timer);
}

export class LibraryQueryDebouncer {
  private cancelTimer: (() => void) | null = null;

  constructor(
    private readonly onSettled: (query: LibraryQueryDraft) => void,
    private readonly schedule: Schedule = scheduleTimeout
  ) {}

  update(query: LibraryQueryDraft): void {
    this.cancelTimer?.();
    const nextQuery = { ...query };
    this.cancelTimer = this.schedule(() => {
      this.cancelTimer = null;
      this.onSettled(nextQuery);
    }, LIBRARY_QUERY_DEBOUNCE_MS);
  }

  dispose(): void {
    this.cancelTimer?.();
    this.cancelTimer = null;
  }
}

export function libraryQueryDraftIsSettled(
  draft: LibraryQueryDraft,
  settled: LibraryQueryDraft
): boolean {
  return draft.search === settled.search
    && draft.smartFilterQuery === settled.smartFilterQuery;
}
