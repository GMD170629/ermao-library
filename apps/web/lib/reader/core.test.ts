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

test('normalizes a complete V4 preference snapshot from legacy and invalid input', () => {
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
    schemaVersion: 4,
    appearance: { theme: 'warm', themeMode: 'manual' },
    display: { progressStyle: 'auto', showClock: false },
    interaction: {
      tapZones: 'standard',
      swipePageTurn: true,
      keyboardPageTurn: true,
      volumeKeyPageTurn: false,
      keepScreenAwake: false
    },
    epub: {
      fontSize: 30,
      lineHeight: 1.9,
      pageWidth: 1350,
      fontFamily: 'pingfang',
      fontWeight: 400,
      letterSpacing: 0,
      pageMargin: 'standard',
      spreadMode: 'single',
      pageTurnAnimation: 'off',
      flow: 'paginated',
      typography: {
        paragraphIndent: 2,
        paragraphSpacing: 0,
        textAlign: 'publisher',
        preservePublisherStyles: false,
        allowPublisherColors: false,
        allowPublisherFonts: false
      },
      optimization: {
        enabled: true,
        deduplicateIndent: true,
        indentUnindented: true
      }
    },
    comic: {
      direction: 'rtl',
      mode: 'double',
      pageTurnAnimation: 'slide',
      imageFit: 'contain',
      imageVariant: 'data-saver',
      zoom: 1.6,
      pageWidth: 1350,
      flow: 'paged',
      coverSingle: false,
      pageGap: 0
    },
    pdf: { zoom: 1.6, pageWidth: 1350, fit: 'page', flow: 'paged', rotation: 0, cropMargins: 'off' }
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

test('migrates V2 kindle animation and missing paging fields to V4 defaults', () => {
  const preferences = normalizeReaderPreferences({
    schemaVersion: 2,
    epub: {
      pageTurnAnimation: 'kindle'
    },
    comic: {
      mode: 'double'
    }
  });

  assert.equal(preferences.schemaVersion, 4);
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

test('normalizes V4 display, theme, EPUB, comic, and PDF settings', () => {
  const preferences = normalizeReaderPreferences({
    schemaVersion: 4,
    appearance: { theme: 'green', themeMode: 'system' },
    display: { progressStyle: 'remaining', showClock: true },
    interaction: { keepScreenAwake: true },
    epub: { fontWeight: 700, letterSpacing: 0.08, pageMargin: 'wide', spreadMode: 'auto' },
    comic: { flow: 'vertical', coverSingle: true, pageGap: 16 },
    pdf: { flow: 'continuous', rotation: 270, cropMargins: 'auto' }
  });

  assert.equal(preferences.appearance.theme, 'green');
  assert.equal(preferences.appearance.themeMode, 'system');
  assert.deepEqual(preferences.display, { progressStyle: 'remaining', showClock: true });
  assert.equal(preferences.interaction.keepScreenAwake, true);
  assert.deepEqual(
    { fontWeight: preferences.epub.fontWeight, letterSpacing: preferences.epub.letterSpacing, pageMargin: preferences.epub.pageMargin, spreadMode: preferences.epub.spreadMode },
    { fontWeight: 700, letterSpacing: 0.08, pageMargin: 'wide', spreadMode: 'auto' }
  );
  assert.deepEqual(
    { flow: preferences.comic.flow, coverSingle: preferences.comic.coverSingle, pageGap: preferences.comic.pageGap },
    { flow: 'vertical', coverSingle: true, pageGap: 16 }
  );
  assert.deepEqual(
    { flow: preferences.pdf.flow, rotation: preferences.pdf.rotation, cropMargins: preferences.pdf.cropMargins },
    { flow: 'paged', rotation: 270, cropMargins: 'auto' }
  );
});

test('normalizes interaction and smart typography preferences without weakening safe defaults', () => {
  const preferences = normalizeReaderPreferences({
    interaction: {
      tapZones: 'reversed',
      swipePageTurn: false,
      keyboardPageTurn: false,
      volumeKeyPageTurn: true
    },
    epub: {
      typography: {
        paragraphIndent: 8,
        paragraphSpacing: 0.76,
        textAlign: 'justify',
        preservePublisherStyles: true,
        allowPublisherColors: true,
        allowPublisherFonts: true
      },
      optimization: {
        enabled: false,
        deduplicateIndent: false,
        indentUnindented: false
      }
    }
  });

  assert.deepEqual(preferences.interaction, {
    tapZones: 'reversed',
    swipePageTurn: false,
    keyboardPageTurn: false,
    volumeKeyPageTurn: true,
    keepScreenAwake: false
  });
  assert.deepEqual(preferences.epub.typography, {
    paragraphIndent: 4,
    paragraphSpacing: 0.8,
    textAlign: 'justify',
    preservePublisherStyles: true,
    allowPublisherColors: true,
    allowPublisherFonts: true
  });
  assert.deepEqual(preferences.epub.optimization, {
    enabled: false,
    deduplicateIndent: false,
    indentUnindented: false
  });
});

test('session reducer rejects stale operations and events from another session', () => {
  let state = createReaderSessionState('session-current', normalizeReaderPreferences(null), 'reflowable');
  const bootstrap = nextOperationToken(state, 'bootstrap');
  state = readerSessionReducer(state, { type: 'operation/begin', operation: bootstrap });
  state = readerSessionReducer(state, {
    type: 'adapter/event',
    event: {
      type: 'phase-changed',
      sessionId: state.sessionId,
      operation: bootstrap,
      occurredAt: 1,
      phase: 'downloading-content'
    }
  });
  state = readerSessionReducer(state, {
    type: 'adapter/event',
    event: {
      type: 'download-progress',
      sessionId: state.sessionId,
      operation: bootstrap,
      occurredAt: 1,
      loadedBytes: 512,
      totalBytes: 1024,
      percent: 50
    }
  });
  assert.deepEqual(state.downloadProgress, { loadedBytes: 512, totalBytes: 1024, percent: 50 });
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
  assert.equal(state.downloadProgress, null);
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
  state = readerSessionReducer(state, {
    type: 'adapter/event',
    event: {
      type: 'navigation-changed',
      sessionId: state.sessionId,
      operation: bootstrap,
      occurredAt: 1,
      items: [{ id: 'chapter-1', label: 'Chapter 1', href: 'chapter-1.xhtml' }]
    }
  });
  assert.deepEqual(state.navigationItems, [{ id: 'chapter-1', label: 'Chapter 1', href: 'chapter-1.xhtml' }]);

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
