import assert from 'node:assert/strict';
import test from 'node:test';
import type { LibraryFilterOptionPage } from './filter-schema';
import {
  FILTER_OPTION_DEBOUNCE_MS,
  FilterOptionSearchController,
  type FilterOptionSearchState
} from './filter-option-search';

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

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function optionPage(query: string, value: string): LibraryFilterOptionPage {
  return {
    source: 'authors',
    query,
    options: [{ value, label: value, count: 1 }],
    hasMore: false,
    indexReady: true
  };
}

test('debounces changed non-blank input for exactly 250 ms', () => {
  const timer = fakeScheduler();
  const queries: string[] = [];
  const controller = new FilterOptionSearchController(
    'authors',
    (_source, query) => {
      queries.push(query);
      return Promise.resolve(optionPage(query, query));
    },
    () => undefined,
    timer.schedule
  );

  controller.inputChanged('   ');
  controller.inputChanged('林');
  timer.advance(FILTER_OPTION_DEBOUNCE_MS - 1);
  assert.deepEqual(queries, []);
  timer.advance(1);
  assert.deepEqual(queries, ['林']);
});

test('can explicitly load the default option page for an empty query', () => {
  const timer = fakeScheduler();
  const queries: string[] = [];
  const controller = new FilterOptionSearchController(
    'tags',
    (_source, query) => {
      queries.push(query);
      return Promise.resolve({ ...optionPage(query, '科幻'), source: 'tags' });
    },
    () => undefined,
    timer.schedule
  );

  controller.search('');
  timer.advance(FILTER_OPTION_DEBOUNCE_MS);
  assert.deepEqual(queries, ['']);
});

test('reuses a completed query without returning to loading state', async () => {
  const timer = fakeScheduler();
  const queries: string[] = [];
  const states: FilterOptionSearchState[] = [];
  const controller = new FilterOptionSearchController(
    'tags',
    (_source, query) => {
      queries.push(query);
      return Promise.resolve({ ...optionPage(query, '科幻'), source: 'tags' });
    },
    (state) => states.push(state),
    timer.schedule
  );

  controller.search('');
  timer.advance(FILTER_OPTION_DEBOUNCE_MS);
  await Promise.resolve();
  assert.equal(states.at(-1)?.kind, 'ready');

  controller.search('');
  assert.deepEqual(queries, ['']);
  assert.equal(states.at(-1)?.kind, 'ready');
  assert.equal(states.filter((state) => state.kind === 'loading').length, 1);
});

test('reset cancels an active query and restores cached default suggestions', async () => {
  const timer = fakeScheduler();
  const states: FilterOptionSearchState[] = [];
  const pending = deferred<LibraryFilterOptionPage>();
  const controller = new FilterOptionSearchController(
    'tags',
    (_source, query) => query
      ? pending.promise
      : Promise.resolve({ ...optionPage(query, '科幻'), source: 'tags' }),
    (state) => states.push(state),
    timer.schedule
  );

  controller.search('');
  timer.advance(FILTER_OPTION_DEBOUNCE_MS);
  await Promise.resolve();
  controller.search('历史');
  timer.advance(FILTER_OPTION_DEBOUNCE_MS);
  assert.equal(states.at(-1)?.kind, 'loading');

  controller.reset();
  assert.equal(states.at(-1)?.kind, 'ready');
  assert.deepEqual(states.at(-1)?.options.map((option) => option.value), ['科幻']);
});

test('aborts the previous request and ignores its stale response', async () => {
  const timer = fakeScheduler();
  const first = deferred<LibraryFilterOptionPage>();
  const second = deferred<LibraryFilterOptionPage>();
  const signals: AbortSignal[] = [];
  const states: FilterOptionSearchState[] = [];
  const controller = new FilterOptionSearchController(
    'authors',
    (_source, query, signal) => {
      signals.push(signal);
      return query === '旧' ? first.promise : second.promise;
    },
    (state) => states.push(state),
    timer.schedule
  );

  controller.inputChanged('旧');
  timer.advance(FILTER_OPTION_DEBOUNCE_MS);
  controller.inputChanged('新');
  assert.equal(signals[0]?.aborted, true);
  timer.advance(FILTER_OPTION_DEBOUNCE_MS);

  first.resolve(optionPage('旧', '过期作者'));
  await Promise.resolve();
  assert.equal(states.some((state) => state.options[0]?.value === '过期作者'), false);

  second.resolve(optionPage('新', '新作者'));
  await Promise.resolve();
  assert.equal(states.at(-1)?.kind, 'ready');
  assert.equal(states.at(-1)?.options[0]?.value, '新作者');
});

test('reports indexing and non-blocking error states without throwing', async () => {
  const timer = fakeScheduler();
  const states: FilterOptionSearchState[] = [];
  let shouldFail = false;
  const controller = new FilterOptionSearchController(
    'tags',
    (_source, query) => shouldFail
      ? Promise.reject(new Error('unavailable'))
      : Promise.resolve({
          source: 'tags',
          query,
          options: [],
          hasMore: false,
          indexReady: false
        }),
    (state) => states.push(state),
    timer.schedule
  );

  controller.inputChanged('科幻');
  timer.advance(FILTER_OPTION_DEBOUNCE_MS);
  await Promise.resolve();
  assert.equal(states.at(-1)?.kind, 'indexing');

  shouldFail = true;
  controller.inputChanged('历史');
  timer.advance(FILTER_OPTION_DEBOUNCE_MS);
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(states.at(-1)?.kind, 'error');
});
