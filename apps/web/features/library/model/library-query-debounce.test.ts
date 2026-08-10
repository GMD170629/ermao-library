import assert from 'node:assert/strict';
import test from 'node:test';
import {
  LIBRARY_QUERY_DEBOUNCE_MS,
  LibraryQueryDebouncer,
  libraryQueryDraftIsSettled,
  type LibraryQueryDraft
} from './library-query-debounce';

type ScheduledTask = { at: number; callback: () => void; cancelled: boolean };

function fakeScheduler() {
  let now = 0;
  const tasks: ScheduledTask[] = [];
  return {
    schedule(callback: () => void, delayMs: number) {
      const task = { at: now + delayMs, callback, cancelled: false };
      tasks.push(task);
      return () => { task.cancelled = true; };
    },
    advance(delayMs: number) {
      now += delayMs;
      for (const task of tasks.filter((candidate) => !candidate.cancelled && candidate.at <= now)) {
        task.cancelled = true;
        task.callback();
      }
    }
  };
}

function draft(search: string, smartFilterQuery: string): LibraryQueryDraft {
  return { search, smartFilterQuery };
}

test('settles only the latest rapid library query draft after 250 ms', () => {
  const timer = fakeScheduler();
  const settled: LibraryQueryDraft[] = [];
  const debouncer = new LibraryQueryDebouncer(
    (query) => settled.push(query),
    timer.schedule
  );

  debouncer.update(draft('', '作'));
  timer.advance(100);
  debouncer.update(draft('', '作者'));
  timer.advance(100);
  debouncer.update(draft('', '作者名'));
  timer.advance(LIBRARY_QUERY_DEBOUNCE_MS - 1);
  assert.deepEqual(settled, []);

  timer.advance(1);
  assert.deepEqual(settled, [draft('', '作者名')]);
});

test('cancels a pending library query when disposed', () => {
  const timer = fakeScheduler();
  const settled: LibraryQueryDraft[] = [];
  const debouncer = new LibraryQueryDebouncer(
    (query) => settled.push(query),
    timer.schedule
  );

  debouncer.update(draft('检索词', ''));
  debouncer.dispose();
  timer.advance(LIBRARY_QUERY_DEBOUNCE_MS);

  assert.deepEqual(settled, []);
});

test('marks a changed search or smart-filter draft as unsettled', () => {
  const settled = draft('书名', '作者=甲');

  assert.equal(libraryQueryDraftIsSettled(draft('书名', '作者=甲'), settled), true);
  assert.equal(libraryQueryDraftIsSettled(draft('新书名', '作者=甲'), settled), false);
  assert.equal(libraryQueryDraftIsSettled(draft('书名', '作者=乙'), settled), false);
});
