import assert from 'node:assert/strict';
import test from 'node:test';
import type { Locator, Publication } from '@readium/shared';
import {
  closestReadiumPosition,
  findReadiumPublicationResource,
  isAllowedReadiumExternalHref,
  readiumTotalProgression,
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
