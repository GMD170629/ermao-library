import assert from 'node:assert/strict';
import test from 'node:test';
import type { Locator, Publication } from '@readium/shared';
import { createLocalPublication } from '../original-publication/local-publication';
import {
  parseEpub2NcxNavigation,
  parseEpub3Navigation,
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

test('Readium external navigation only allows explicit safe schemes', () => {
  for (const href of ['https://example.com', 'http://example.com', 'mailto:test@example.com', 'tel:+86123']) {
    assert.equal(isAllowedReadiumExternalHref(href), true, href);
  }
  for (const href of ['javascript:alert(1)', 'data:text/html,unsafe', '//example.com', 'chapter.xhtml']) {
    assert.equal(isAllowedReadiumExternalHref(href), false, href);
  }
});

test('Readium TOC conversion preserves nesting and exposes zero-based reading-order indexes', () => {
  const publication = {
    readingOrder: { items: [{ href: 'text/one.xhtml' }, { href: 'text/two.xhtml' }] },
    toc: {
      items: [{
        href: 'text/one.xhtml#start',
        title: 'Part I',
        children: { items: [{ href: 'text/two.xhtml#section', title: 'Chapter 2' }] }
      }]
    }
  } as Publication;

  assert.deepEqual(readiumNavigationEntries(publication), [{
    id: 'readium-toc:0:text/one.xhtml#start',
    navigationKey: 'readium-toc:0:text/one.xhtml#start',
    label: 'Part I',
    href: 'text/one.xhtml#start',
    index: 0,
    level: 0,
    children: [{
      id: 'readium-toc:0.0:text/two.xhtml#section',
      navigationKey: 'readium-toc:0.0:text/two.xhtml#section',
      label: 'Chapter 2',
      href: 'text/two.xhtml#section',
      index: 1,
      level: 1
    }]
  }]);
});

test('Readium navigation flattening keeps authored order and depth for the reader list', () => {
  const entries = [{
    id: 'root',
    label: 'Part I',
    level: 0,
    children: [{
      id: 'chapter',
      label: 'Chapter 1',
      href: 'text/one.xhtml',
      level: 1,
      children: [{ id: 'section', label: 'Section 1.1', level: 2 }]
    }]
  }];

  assert.deepEqual(flattenReadiumNavigationEntries(entries), [
    { id: 'root', label: 'Part I', level: 0, index: 0 },
    { id: 'chapter', label: 'Chapter 1', href: 'text/one.xhtml', level: 1, index: 1 },
    { id: 'section', label: 'Section 1.1', level: 2, index: 2 }
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
      href: 'text/chapter.xhtml',
      title: 'Part I',
      children: [{
        href: 'text/chapter.xhtml#section',
        title: 'Section 1',
        children: [{ href: 'text/chapter.xhtml#subsection', title: 'Section 1.1' }]
      }]
    }]
  });

  assert.deepEqual(publication.publication.toc?.serialize(), [{
    href: 'text/chapter.xhtml',
    title: 'Part I',
    type: 'application/xhtml+xml',
    children: [{
      href: 'text/chapter.xhtml#section',
      title: 'Section 1',
      type: 'application/xhtml+xml',
      children: [{
        href: 'text/chapter.xhtml#subsection',
        title: 'Section 1.1',
        type: 'application/xhtml+xml'
      }]
    }]
  }]);
  publication.close();
});

test('local publication falls back to reading order when an explicit TOC is empty', () => {
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

  assert.deepEqual(publication.publication.toc?.serialize(), [{
    href: 'text/chapter.xhtml',
    title: 'Chapter',
    type: 'application/xhtml+xml'
  }]);
  publication.close();
});

test('EPUB navigation precedence uses EPUB3, then NCX, then reading order', () => {
  const epub3 = [{ href: 'text/epub3.xhtml', title: 'EPUB3' }];
  const ncx = [{ href: 'text/ncx.xhtml', title: 'NCX' }];
  const readingOrder = [{ href: 'text/reading-order.xhtml', title: 'Reading order' }];

  assert.deepEqual(resolveEpubNavigation(epub3, ncx, readingOrder), epub3);
  assert.deepEqual(resolveEpubNavigation([], ncx, readingOrder), ncx);
  assert.deepEqual(resolveEpubNavigation([], [], readingOrder), readingOrder);
});

test('EPUB2 NCX lookup follows a valid spine toc association and falls back to a legal NCX', () => {
  const items = new Map([
    ['alternate-ncx', { path: 'OPS/alternate.ncx', type: 'APPLICATION/X-DTBNcx+XML', properties: '' }],
    ['ncx', { path: 'OPS/toc.ncx', type: 'application/x-dtbncx+xml', properties: '' }],
    ['nav', { path: 'OPS/nav.xhtml', type: 'application/xhtml+xml', properties: 'nav' }]
  ]);

  assert.deepEqual(resolveEpub2NcxManifestItem(items, 'ncx'), items.get('ncx'));
  assert.deepEqual(resolveEpub2NcxManifestItem(items, 'nav'), items.get('alternate-ncx'));
  assert.deepEqual(resolveEpub2NcxManifestItem(items, null), items.get('alternate-ncx'));
});

type FakeElement = {
  localName: string;
  tagName: string;
  children: FakeElement[];
  textContent: string;
  getAttribute: (name: string) => string | null;
  getAttributeNS: (_namespace: string, name: string) => string | null;
  hasAttribute: (name: string) => boolean;
  querySelector: (selector: string) => FakeElement | null;
};

function fakeElement(
  name: string,
  attributes: Record<string, string> = {},
  children: FakeElement[] = [],
  textContent = ''
): FakeElement {
  const findAnchor = (items: readonly FakeElement[]): FakeElement | null => {
    for (const item of items) {
      if (item.localName === 'a' && item.hasAttribute('href')) return item;
      const nested = findAnchor(item.children);
      if (nested) return nested;
    }
    return null;
  };
  return {
    localName: name,
    tagName: name,
    children,
    textContent,
    getAttribute: (attribute) => attributes[attribute] ?? null,
    getAttributeNS: (_namespace, attribute) => attributes[`epub:${attribute}`] ?? null,
    hasAttribute: (attribute) => Object.prototype.hasOwnProperty.call(attributes, attribute),
    querySelector: (selector) => selector === 'a[href]' ? findAnchor(children) : null
  };
}

test('EPUB3 navigation parser preserves nested entries, fragments, and skips unknown targets', () => {
  const anchor = fakeElement('a', { href: 'chapter.xhtml#start' }, [], 'Chapter');
  const nestedAnchor = fakeElement('a', { href: 'chapter.xhtml#section' }, [], 'Section');
  const invalidAnchor = fakeElement('a', { href: 'missing.xhtml' }, [], 'Missing');
  const nav = fakeElement('nav', { 'epub:type': 'toc' }, [fakeElement('ol', {}, [
    fakeElement('li', {}, [anchor, fakeElement('ol', {}, [fakeElement('li', {}, [nestedAnchor])])]),
    fakeElement('li', {}, [invalidAnchor])
  ])]);
  const document = {
    querySelectorAll: (selector: string) => selector === 'nav' ? [nav] : []
  } as unknown as XMLDocument;

  assert.deepEqual(parseEpub3Navigation(document, 'OPS/nav.xhtml', new Set(['OPS/chapter.xhtml'])), [{
    href: 'OPS/chapter.xhtml#start',
    title: 'Chapter',
    children: [{ href: 'OPS/chapter.xhtml#section', title: 'Section' }]
  }]);
});

test('EPUB3 navigation parser ignores non-TOC navs so NCX fallback remains available', () => {
  const nav = fakeElement('nav', { 'epub:type': 'landmarks' }, [fakeElement('ol', {}, [
    fakeElement('li', {}, [fakeElement('a', { href: 'chapter.xhtml' }, [], 'Landmark')])
  ])]);
  const document = {
    querySelectorAll: (selector: string) => selector === 'nav' ? [nav] : []
  } as unknown as XMLDocument;

  assert.deepEqual(parseEpub3Navigation(document, 'OPS/nav.xhtml', new Set(['OPS/chapter.xhtml'])), []);
});

test('EPUB2 NCX parser resolves navPoints relative to the NCX and keeps nesting', () => {
  const chapter = fakeElement('content', { src: '../Text/chapter.xhtml#one' });
  const section = fakeElement('content', { src: '../Text/chapter.xhtml#two' });
  const navPoint = fakeElement('navPoint', {}, [
    fakeElement('navLabel', {}, [fakeElement('text', {}, [], 'Chapter')]),
    chapter,
    fakeElement('navPoint', {}, [
      fakeElement('navLabel', {}, [fakeElement('text', {}, [], 'Section')]),
      section
    ])
  ]);
  const root = fakeElement('ncx', {}, [fakeElement('navMap', {}, [navPoint])]);
  const document = { documentElement: root } as unknown as XMLDocument;

  assert.deepEqual(parseEpub2NcxNavigation(document, 'OPS/toc.ncx', new Set(['Text/chapter.xhtml'])), [{
    href: 'Text/chapter.xhtml#one',
    title: 'Chapter',
    children: [{ href: 'Text/chapter.xhtml#two', title: 'Section' }]
  }]);
});
