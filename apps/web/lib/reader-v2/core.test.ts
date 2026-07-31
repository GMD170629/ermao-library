import assert from 'node:assert/strict';
import test from 'node:test';
import {
  DEFAULT_READER_PREFERENCES,
  createReaderSessionState,
  nextOperationToken,
  normalizeReaderPreferences,
  readerSessionReducer,
  type ReaderAdapterEvent,
  type ReaderCapabilities
} from '@shuku/reader-core';

const capabilities: ReaderCapabilities = {
  readingDirection: 'ltr',
  canGoNext: true,
  canGoPrevious: true,
  canJumpToProgress: true,
  canJumpToHref: true,
  canJumpToIndex: true,
  canZoom: false,
  canSelectText: true,
  supportsPagination: true,
  supportsScrolling: false,
  supportsSpreads: false
};

test('normalizes a complete V3 preference snapshot from legacy and invalid input', () => {
  const preferences = normalizeReaderPreferences({
    theme: 'warm',
    fontSize: 80,
    lineHeight: 1.87,
    pageWidth: 2000,
    fontFamily: 'not-a-font',
    ebookPageTurnAnimation: 'off',
    comicDirection: 'rtl',
    comicMode: 'double',
    imageFit: 'contain',
    imageVariant: 'data-saver',
    zoom: 1.63
  });

  assert.deepEqual(preferences, {
    schemaVersion: 3,
    appearance: { theme: 'warm' },
    epub: {
      fontSize: 30,
      lineHeight: 1.9,
      pageWidth: 1350,
      fontFamily: 'pingfang',
      spreadMode: 'single',
      pageTurnAnimation: 'off',
      flow: 'paginated'
    },
    comic: {
      direction: 'rtl',
      mode: 'double',
      pageTurnAnimation: 'slide',
      imageFit: 'contain',
      imageVariant: 'data-saver',
      zoom: 1.6
    },
    pdf: { zoom: 1.6, fit: 'page' }
  });
  assert.equal(DEFAULT_READER_PREFERENCES.appearance.theme, 'warm');
  assert.equal(DEFAULT_READER_PREFERENCES.pdf.fit, 'page');
});

test('preserves an explicitly saved PDF width fit preference', () => {
  const preferences = normalizeReaderPreferences({
    pdf: { fit: 'width' }
  });

  assert.equal(preferences.pdf.fit, 'width');
});

test('migrates V2 kindle animation and missing paging fields to V3 defaults', () => {
  const preferences = normalizeReaderPreferences({
    schemaVersion: 2,
    epub: {
      pageTurnAnimation: 'kindle'
    },
    comic: {
      mode: 'double'
    }
  });

  assert.equal(preferences.schemaVersion, 3);
  assert.equal(preferences.epub.spreadMode, 'single');
  assert.equal(preferences.epub.pageTurnAnimation, 'slide');
  assert.equal(preferences.comic.mode, 'double');
  assert.equal(preferences.comic.pageTurnAnimation, 'slide');
});

test('preserves valid V3 spread and animation preferences', () => {
  const preferences = normalizeReaderPreferences({
    schemaVersion: 3,
    epub: {
      spreadMode: 'double',
      pageTurnAnimation: 'slide'
    },
    comic: {
      pageTurnAnimation: 'off'
    }
  });

  assert.equal(preferences.epub.spreadMode, 'double');
  assert.equal(preferences.epub.pageTurnAnimation, 'slide');
  assert.equal(preferences.comic.pageTurnAnimation, 'off');
});

test('session reducer rejects stale operations and events from another session', () => {
  let state = createReaderSessionState('session-current', normalizeReaderPreferences(null), 'epub');
  const bootstrap = nextOperationToken(state, 'bootstrap');
  state = readerSessionReducer(state, { type: 'operation/begin', operation: bootstrap });
  state = readerSessionReducer(state, {
    type: 'adapter/event',
    event: {
      type: 'phase-changed',
      sessionId: state.sessionId,
      operation: bootstrap,
      occurredAt: 1,
      phase: 'generating-pagination'
    }
  });
  state = readerSessionReducer(state, {
    type: 'adapter/event',
    event: {
      type: 'pagination-progress',
      sessionId: state.sessionId,
      operation: bootstrap,
      occurredAt: 1,
      completed: 12,
      total: 20,
      percent: 60
    }
  });
  assert.deepEqual(state.paginationProgress, { completed: 12, total: 20, percent: 60 });
  const ready: ReaderAdapterEvent = {
    type: 'ready',
    sessionId: state.sessionId,
    operation: bootstrap,
    occurredAt: 1,
    capabilities,
    location: { kind: 'epub', cfi: 'epubcfi(/6/2)' }
  };
  state = readerSessionReducer(state, { type: 'adapter/event', event: ready });
  assert.equal(state.lifecycle, 'ready');
  assert.equal(state.paginationProgress, null);
  state = readerSessionReducer(state, {
    type: 'adapter/event',
    event: { type: 'metadata-changed', sessionId: state.sessionId, operation: bootstrap, occurredAt: 1, totalPages: 321 }
  });
  assert.equal(state.totalPages, 321);

  const firstNavigation = nextOperationToken(state, 'navigation');
  state = readerSessionReducer(state, { type: 'operation/begin', operation: firstNavigation });
  const currentNavigation = nextOperationToken(state, 'navigation');
  state = readerSessionReducer(state, { type: 'operation/begin', operation: currentNavigation });

  const beforeStale = state;
  state = readerSessionReducer(state, {
    type: 'adapter/event',
    event: {
      type: 'location-changed',
      sessionId: state.sessionId,
      operation: firstNavigation,
      occurredAt: 2,
      location: { kind: 'epub', cfi: 'epubcfi(/6/4)' },
      percent: 20
    }
  });
  assert.strictEqual(state, beforeStale);

  state = readerSessionReducer(state, {
    type: 'adapter/event',
    event: {
      type: 'location-changed',
      sessionId: state.sessionId,
      operation: currentNavigation,
      occurredAt: 3,
      location: { kind: 'epub', cfi: 'epubcfi(/6/8)' },
      percent: 150
    }
  });
  assert.deepEqual(state.location, { kind: 'epub', cfi: 'epubcfi(/6/8)' });
  assert.equal(state.percent, 100);

  const beforeForeign = state;
  state = readerSessionReducer(state, {
    type: 'adapter/event',
    event: { ...ready, sessionId: 'session-old' }
  });
  assert.strictEqual(state, beforeForeign);
});

test('disposed sessions are immutable', () => {
  const initial = createReaderSessionState('session', normalizeReaderPreferences(null), 'pdf');
  const disposed = readerSessionReducer(initial, { type: 'session/dispose' });
  const operation = nextOperationToken(disposed, 'render');
  assert.strictEqual(readerSessionReducer(disposed, { type: 'operation/begin', operation }), disposed);
});
