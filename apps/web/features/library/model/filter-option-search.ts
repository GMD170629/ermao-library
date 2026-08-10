import type {
  LibraryFilterOptionPage,
  LibraryFilterOptionSource,
  SmartFilterOption
} from './filter-schema';

export const FILTER_OPTION_DEBOUNCE_MS = 250;

export type FilterOptionSearchState =
  | { kind: 'idle'; options: SmartFilterOption[] }
  | { kind: 'loading'; options: SmartFilterOption[] }
  | { kind: 'ready'; options: SmartFilterOption[]; hasMore: boolean }
  | { kind: 'indexing'; options: SmartFilterOption[] }
  | { kind: 'error'; options: SmartFilterOption[] };

type FilterOptionRequest = (
  source: LibraryFilterOptionSource,
  query: string,
  signal: AbortSignal
) => Promise<LibraryFilterOptionPage>;

type Schedule = (callback: () => void, delayMs: number) => () => void;

function scheduleTimeout(callback: () => void, delayMs: number): () => void {
  const timer = globalThis.setTimeout(callback, delayMs);
  return () => globalThis.clearTimeout(timer);
}

export class FilterOptionSearchController {
  private state: FilterOptionSearchState = { kind: 'idle', options: [] };
  private requestSequence = 0;
  private cancelTimer: (() => void) | null = null;
  private requestController: AbortController | null = null;

  constructor(
    private readonly source: LibraryFilterOptionSource,
    private readonly request: FilterOptionRequest,
    private readonly onStateChange: (state: FilterOptionSearchState) => void,
    private readonly schedule: Schedule = scheduleTimeout
  ) {}

  inputChanged(input: string): void {
    this.cancel();
    const query = input.trim();
    if (!query) {
      this.publish({ kind: 'idle', options: [] });
      return;
    }

    const sequence = this.requestSequence;
    this.cancelTimer = this.schedule(() => {
      this.cancelTimer = null;
      const controller = new AbortController();
      this.requestController = controller;
      this.publish({ kind: 'loading', options: this.state.options });
      void this.request(this.source, query, controller.signal)
        .then((page) => {
          if (sequence !== this.requestSequence) return;
          this.requestController = null;
          if (!page.indexReady) {
            this.publish({ kind: 'indexing', options: [] });
            return;
          }
          this.publish({
            kind: 'ready',
            options: page.options,
            hasMore: page.hasMore
          });
        })
        .catch((reason: unknown) => {
          if (sequence !== this.requestSequence) return;
          this.requestController = null;
          if (reason instanceof Error && reason.name === 'AbortError') return;
          this.publish({ kind: 'error', options: this.state.options });
        });
    }, FILTER_OPTION_DEBOUNCE_MS);
  }

  cancel(): void {
    this.requestSequence += 1;
    this.cancelTimer?.();
    this.cancelTimer = null;
    this.requestController?.abort();
    this.requestController = null;
  }

  dispose(): void {
    this.cancel();
  }

  private publish(state: FilterOptionSearchState): void {
    this.state = state;
    this.onStateChange(state);
  }
}
