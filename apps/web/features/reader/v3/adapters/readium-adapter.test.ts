import assert from 'node:assert/strict';
import test from 'node:test';
import type { Locator, Publication } from '@readium/shared';
import { createLocalPublication } from '../original-publication/local-publication';
import {
  resolveEpub2NcxManifestItem,
  resolveEpubNavigation
} from './readium-publication';
import {
  closestReadiumPosition,
  findReadiumPublicationResource,
  isAllowedReadiumExternalHref,
  resolveReadiumStartupTargets,
  readiumTotalProgression,
  flattenReadiumNavigationEntries,
  readiumNavigationEntries,
  resolveReadiumHref
} from './readium-navigation';

function locator(href: string, totalProgression?: number) {
  return {
    href,
    locations: { totalProgression }
  };
}

test('Readium progress jumps use the nearest declared total progression', () => {
  const positions = [
    locator('chapter-1.xhtml', 0),
    locator('chapter-2.xhtml', 0.31),
    locator('chapter-3.xhtml', 0.76),
    locator('chapter-4.xhtml', 1)
  ];

  assert.equal(closestReadiumPosition(positions, 0.7)?.href, 'chapter-3.xhtml');
  assert.equal(closestReadiumPosition(positions, -1)?.href, 'chapter-1.xhtml');
  assert.equal(closestReadiumPosition(positions, 2)?.href, 'chapter-4.xhtml');
  assert.equal(closestReadiumPosition([], 0.5), null);
});

test('Readium progress jumps retain deterministic array fallback without total progression', () => {
  const positions = [locator('a.xhtml'), locator('b.xhtml'), locator('c.xhtml')];
  assert.equal(closestReadiumPosition(positions, 0.55)?.href, 'b.xhtml');
});

test('Readium live progress interpolates within a resource instead of staying at its opening position', () => {
  const positions = [
    { href: 'chapter-1.xhtml', locations: { progression: 0, totalProgression: 0.1 } },
    { href: 'chapter-2.xhtml', locations: { progression: 0, totalProgression: 0.4 } },
    { href: 'chapter-3.xhtml', locations: { progression: 0, totalProgression: 0.8 } }
  ];

  assert.equal(readiumTotalProgression({
    href: 'chapter-1.xhtml',
    locations: { progression: 0.5, totalProgression: 0.1 }
  }, positions), 0.25);
  assert.equal(readiumTotalProgression({
    href: 'chapter-3.xhtml',
    locations: { progression: 0.5, totalProgression: 0.8 }
  }, positions), 0.9);
});

test('Readium presentation uses publication positions when the native locator total is stale', () => {
  const positions = [
    { href: 'chapter-1.xhtml', locations: { progression: 0, totalProgression: 0.25 } },
    { href: 'chapter-1.xhtml', locations: { progression: 1, totalProgression: 0.99 } }
  ];

  assert.equal(readiumTotalProgression({
    href: 'chapter-1.xhtml',
    locations: { progression: 1, totalProgression: 0.25 }
  }, positions), 0.99);
});

test('Readium href resolver keeps fragments and publication-relative paths', () => {
  assert.equal(resolveReadiumHref('#note', 'text/chapter.xhtml'), 'text/chapter.xhtml#note');
  assert.equal(resolveReadiumHref('../notes.xhtml#n1', 'text/chapter.xhtml'), 'notes.xhtml#n1');
  assert.equal(resolveReadiumHref('/notes.xhtml#n1', '/books/text/chapter.xhtml'), '/notes.xhtml#n1');
  assert.equal(
    resolveReadiumHref('../notes.xhtml#n1', 'https://reader.example/books/text/chapter.xhtml'),
    'https://reader.example/books/notes.xhtml#n1'
  );
});

test('Readium TOC jumps match a publication-root href before a misleading current-resource resolution', () => {
  const items = [
    { href: 'text/part0009.html' },
    { href: 'text/part0010.html' }
  ];
  const candidate = 'text/part0009.html#chapter';
  const resolved = resolveReadiumHref(candidate, 'text/part0010.html');

  assert.equal(resolved, 'text/text/part0009.html#chapter');
  assert.equal(findReadiumPublicationResource(items, [candidate, resolved])?.href, 'text/part0009.html');
});

test('Readium startup gives an explicit chapter target priority over the publication start', () => {
  const readingOrder = [
    { href: 'text/preface.xhtml' },
    { href: 'text/part0009.html' }
  ];
  const positions = [
    locator('text/preface.xhtml', 0),
    locator('text/part0009.html', 0.72)
  ];

  assert.deepEqual(resolveReadiumStartupTargets(
    readingOrder,
    positions,
    'text/preface.xhtml',
    'text/part0009.html#chapter-six'
  ), {
    start: { position: positions[0], fragment: '' },
    initial: { position: positions[1], fragment: 'chapter-six' }
  });
});

test('Readium external navigation shares the authored URI blacklist and preserves unfamiliar schemes', () => {
  for (const href of ['https://example.com', 'http://example.com', 'mailto:test@example.com', 'tel:+86123', 'future-reader:chapter', '//example.com']) {
    assert.equal(isAllowedReadiumExternalHref(href), true, href);
  }
  for (const href of ['javascript:alert(1)', 'data:text/html,unsafe', 'file:///private', 'chapter.xhtml']) {
    assert.equal(isAllowedReadiumExternalHref(href), false, href);
  }
});

test('Readium TOC conversion preserves core nesting and preorder indexes', () => {
  const publication = {
    readingOrder: { items: [{ href: 'text/one.xhtml' }, { href: 'text/two.xhtml' }] },
    toc: {
      items: [{
        href: 'text/one.xhtml#start',
        title: 'Part I',
        properties: { otherProperties: { 'shuku:navigationKey': 'chapter-0' } },
        children: { items: [{
          href: 'text/two.xhtml#section',
          title: 'Chapter 2',
          properties: { otherProperties: { 'shuku:navigationKey': 'chapter-1' } }
        }] }
      }]
    }
  } as unknown as Publication;

  assert.deepEqual(readiumNavigationEntries(publication), [{
    id: 'chapter-0',
    navigationKey: 'chapter-0',
    label: 'Part I',
    href: 'text/one.xhtml#start',
    index: 0,
    level: 0,
    children: [{
      id: 'chapter-1',
      navigationKey: 'chapter-1',
      label: 'Chapter 2',
      href: 'text/two.xhtml#section',
      index: 1,
      level: 1
    }]
  }]);
});

test('Readium TOC conversion rejects links without a chapter-core key', () => {
  const publication = {
    readingOrder: { items: [{ href: 'text/one.xhtml' }] },
    toc: { items: [{ href: 'text/one.xhtml', title: 'Chapter 1' }] }
  } as Publication;
  assert.throws(() => readiumNavigationEntries(publication), /READER_NAVIGATION_KEY_MISSING/);
});

test('Readium TOC conversion keeps a named non-clickable group', () => {
  const publication = {
    readingOrder: { items: [{ href: 'text/one.xhtml' }] },
    toc: {
      items: [{
        href: '',
        title: 'Volume',
        properties: { otherProperties: { 'shuku:navigationKey': 'chapter-0' } },
        children: { items: [{
          href: 'text/one.xhtml#chapter',
          title: 'Chapter 1',
          properties: { otherProperties: { 'shuku:navigationKey': 'chapter-1' } }
        }] }
      }]
    }
  } as unknown as Publication;
  assert.deepEqual(readiumNavigationEntries(publication)[0], {
    id: 'chapter-0',
    navigationKey: 'chapter-0',
    label: 'Volume',
    index: 0,
    level: 0,
    children: [{
      id: 'chapter-1',
      navigationKey: 'chapter-1',
      label: 'Chapter 1',
      href: 'text/one.xhtml#chapter',
      index: 1,
      level: 1
    }]
  });
});

test('Readium TOC conversion keeps chapter-core keys and preorder indexes for groups', () => {
  const publication = {
    readingOrder: { items: [{ href: 'text/chapter-0001.xhtml' }] },
    toc: {
      items: [{
        href: '',
        title: 'Part I',
        properties: { otherProperties: { 'shuku:navigationKey': 'chapter-7' } },
        children: { items: [{
          href: 'text/chapter-0001.xhtml#heading-000001',
          title: 'Chapter 1',
          properties: { otherProperties: { 'shuku:navigationKey': 'chapter-8' } }
        }] }
      }]
    }
  } as unknown as Publication;

  assert.deepEqual(readiumNavigationEntries(publication), [{
    id: 'chapter-7',
    navigationKey: 'chapter-7',
    label: 'Part I',
    index: 7,
    level: 0,
    children: [{
      id: 'chapter-8',
      navigationKey: 'chapter-8',
      label: 'Chapter 1',
      href: 'text/chapter-0001.xhtml#heading-000001',
      index: 8,
      level: 1
    }]
  }]);
});

test('Readium navigation flattening keeps authored order and depth for the reader list', () => {
  const entries = [{
    id: 'chapter-0',
    navigationKey: 'chapter-0',
    index: 0,
    label: 'Part I',
    level: 0,
    children: [{
      id: 'chapter-1',
      navigationKey: 'chapter-1',
      index: 1,
      label: 'Chapter 1',
      href: 'text/one.xhtml',
      level: 1,
      children: [{ id: 'chapter-2', navigationKey: 'chapter-2', index: 2, label: 'Section 1.1', level: 2 }]
    }]
  }];

  assert.deepEqual(flattenReadiumNavigationEntries(entries), [
    { id: 'chapter-0', navigationKey: 'chapter-0', label: 'Part I', level: 0, index: 0 },
    { id: 'chapter-1', navigationKey: 'chapter-1', label: 'Chapter 1', href: 'text/one.xhtml', level: 1, index: 1 },
    { id: 'chapter-2', navigationKey: 'chapter-2', label: 'Section 1.1', level: 2, index: 2 }
  ]);
});

test('local publication manifests preserve recursive TOC links', () => {
  const publication = createLocalPublication({
    title: 'Nested contents',
    readingProgression: 'ltr',
    writingMode: 'horizontal',
    readingOrder: [{
      href: 'text/chapter.xhtml',
      type: 'application/xhtml+xml',
      title: 'Chapter',
      positionLength: 1,
      read: async () => new Uint8Array()
    }],
    toc: [{
      href: null,
      title: 'Part I',
      navigationKey: 'chapter-0',
      children: [{
        href: 'text/chapter.xhtml#section',
        title: 'Section 1',
        navigationKey: 'chapter-1',
        children: [{
          href: 'text/chapter.xhtml#subsection',
          title: 'Section 1.1',
          navigationKey: 'chapter-2'
        }]
      }]
    }]
  });

  assert.deepEqual(publication.publication.toc?.serialize(), [{
    href: '',
    title: 'Part I',
    type: 'application/xhtml+xml',
    properties: { 'shuku:navigationKey': 'chapter-0' },
    children: [{
      href: 'text/chapter.xhtml#section',
      title: 'Section 1',
      type: 'application/xhtml+xml',
      properties: { 'shuku:navigationKey': 'chapter-1' },
      children: [{
        href: 'text/chapter.xhtml#subsection',
        title: 'Section 1.1',
        type: 'application/xhtml+xml',
        properties: { 'shuku:navigationKey': 'chapter-2' }
      }]
    }]
  }]);
  publication.close();
});

test('local publication keeps an explicit empty TOC empty', () => {
  const publication = createLocalPublication({
    title: 'Reading order fallback',
    readingProgression: 'ltr',
    writingMode: 'horizontal',
    readingOrder: [{
      href: 'text/chapter.xhtml',
      type: 'application/xhtml+xml',
      title: 'Chapter',
      positionLength: 1,
      read: async () => new Uint8Array()
    }],
    toc: []
  });

  assert.deepEqual(publication.publication.toc?.serialize(), []);
  publication.close();
});

test('EPUB navigation precedence uses EPUB3, then NCX, with no synthetic reading-order TOC', () => {
  const epub3 = [{ href: 'text/epub3.xhtml', title: 'EPUB3' }];
  const ncx = [{ href: 'text/ncx.xhtml', title: 'NCX' }];

  assert.deepEqual(resolveEpubNavigation(epub3, ncx), epub3);
  assert.deepEqual(resolveEpubNavigation([], ncx), ncx);
  assert.deepEqual(resolveEpubNavigation([], []), []);
});

test('EPUB2 NCX lookup follows the declared resource even with unfamiliar MIME metadata', () => {
  const items = new Map([
    ['alternate-ncx', { path: 'OPS/alternate.ncx', type: 'APPLICATION/X-DTBNcx+XML', properties: '' }],
    ['ncx', { path: 'OPS/toc.ncx', type: 'application/x-dtbncx+xml', properties: '' }],
    ['future', { path: 'OPS/navigation.future', type: 'application/future-navigation', properties: '' }]
  ]);

  assert.deepEqual(resolveEpub2NcxManifestItem(items, 'ncx'), items.get('ncx'));
  assert.deepEqual(resolveEpub2NcxManifestItem(items, 'future'), items.get('future'));
  assert.deepEqual(resolveEpub2NcxManifestItem(items, null), items.get('alternate-ncx'));
});
