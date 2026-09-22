import { useEffect, useState } from 'react';
import { fetchBookContents } from '../api/client';
import type { BookContentEntry } from '../model/book-contents';

type ContentsState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; entries: readonly BookContentEntry[]; resourceId: string | null };

/** Each expanded directory owns its paginated query and cancels it on collapse. */
export function useBookDownloadContents(bookId: string, sourceNodeId: string | null) {
  const [state, setState] = useState<ContentsState>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState({ status: 'loading' });
    async function load() {
      const first = await fetchBookContents(bookId, sourceNodeId, 'name-asc', 1, controller.signal);
      const entries = [...first.entries];
      for (let page = 2; page <= first.totalPages; page++) {
        const next = await fetchBookContents(bookId, sourceNodeId, 'name-asc', page, controller.signal);
        entries.push(...next.entries);
      }
      if (!controller.signal.aborted) setState({ status: 'ready', entries, resourceId: first.currentResourceId });
    }
    load().catch(() => {
      if (!controller.signal.aborted) setState({ status: 'error' });
    });
    return () => controller.abort();
  }, [bookId, sourceNodeId, attempt]);
  return { state, retry: () => setAttempt((value) => value + 1) };
}
