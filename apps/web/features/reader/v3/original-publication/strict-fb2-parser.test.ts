import assert from 'node:assert/strict';
import test from 'node:test';
import { parseStrictFb2 } from './strict-fb2-parser';

test('strict FB2 parsing preserves metadata, sections and text', () => {
  const parsed = parseStrictFb2(`<?xml version="1.0"?><FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="urn:local"><description><title-info><book-title>Book</book-title><lang>en</lang></title-info></description><body l:id="main"><section><title><p>One</p></title><p>Hello &amp; world</p></section><section><title><p>Two</p></title><p>Next</p></section></body></FictionBook>`);
  assert.equal(parsed.title, 'Book');
  assert.equal(parsed.language, 'en');
  assert.deepEqual(parsed.chapters.map((chapter) => chapter.title), ['One', 'Two']);
  assert.match(parsed.chapters[0]?.text ?? '', /Hello & world/);
});

test('strict FB2 parsing fails closed for malformed, entity and parser-budget inputs', () => {
  for (const source of [
    '<FictionBook><body><section></body></FictionBook>',
    '<!DOCTYPE FictionBook [<!ENTITY x "boom">]><FictionBook><body><p>&x;</p></body></FictionBook>',
    '<FictionBook><body><p>&broken</p></body></FictionBook>',
    '<bad:FictionBook><body><p>text</p></body></bad:FictionBook>',
    '<FictionBook><body bad:attr="x"><p>text</p></body></FictionBook>',
    '<FictionBook xmlns:xml="urn:not-xml"><body><p>text</p></body></FictionBook>',
    '<FictionBook xmlns:a="urn:same" xmlns:b="urn:same"><body a:id="one" b:id="two"><p>text</p></body></FictionBook>'
  ]) assert.throws(() => parseStrictFb2(source), /PUBLICATION_(?:MARKUP_INVALID|SECURITY_REJECTED)/);
  assert.throws(
    () => parseStrictFb2('<FictionBook><body><section><p>x</p></section></body></FictionBook>', { maxDepth: 2, maxNodes: 100, maxTextChars: 100 }),
    /PUBLICATION_PARSER_LIMIT/
  );
  assert.throws(
    () => parseStrictFb2('<FictionBook><body><p>excess</p></body></FictionBook>', { maxDepth: 20, maxNodes: 100, maxTextChars: 3 }),
    /PUBLICATION_PARSER_MEMORY/
  );
});
