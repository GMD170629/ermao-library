import assert from 'node:assert/strict';
import test from 'node:test';
import { READER_SAFETY_RULE_IDS } from '@shuku/reader-core';
import { ReaderSafetyPolicyError } from '../security/reader-safety-policy';
import { parseStrictFb2 } from './strict-fb2-parser';

test('strict FB2 parsing preserves metadata, sections and text', () => {
  const parsed = parseStrictFb2(`<?xml version="1.0"?><FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="urn:local"><description><title-info><book-title>Book</book-title><lang>en</lang></title-info></description><body l:id="main"><section><title><p>One</p></title><p>Hello &amp; world</p></section><section><title><p>Two</p></title><p>Next</p></section></body></FictionBook>`);
  assert.equal(parsed.title, 'Book');
  assert.equal(parsed.language, 'en');
  assert.deepEqual(parsed.chapters.map((chapter) => chapter.title), ['One', 'Two']);
  assert.match(parsed.chapters[0]?.text ?? '', /Hello & world/);
  assert.deepEqual(parsed.blockedResources, []);
});

test('strict FB2 parsing preserves loose body runs and emits canonical section targets', () => {
  const parsed = parseStrictFb2(
    '<FictionBook><body><p>Before</p><section><title><p>One</p></title><p>Inside</p>'
      + '<section><title><p>Nested</p></title><p>Child</p></section></section>'
      + '<p>After</p></body></FictionBook>'
  );

  assert.equal(parsed.sections.length, 1);
  assert.equal(parsed.bodyFragments.length, 2);
  assert.deepEqual(parsed.bodyFragments.map((fragment) => fragment.href), [
    'fb2/body-1-part-1.xhtml',
    'fb2/body-1-part-2.xhtml'
  ]);
  const sectionStarts = parsed.events.filter((event) => event.kind === 'start' && event.name === 'section');
  assert.deepEqual(sectionStarts.map((event) => event.targetHref), [
    'fb2/section-0001.xhtml#chapter-node-3',
    'fb2/section-0001.xhtml#chapter-node-7'
  ]);
  assert.equal(parsed.sections[0]?.events[0], sectionStarts[0]);
  assert.equal(parsed.sections[0]?.events.at(-1)?.kind, 'end');
  assert.equal(parsed.bodyFragments[0]?.events[0], parsed.events.find(
    (event) => event.kind === 'start' && event.name === 'p'
  ));
  assert.equal(parsed.sections[0]?.events.some(
    (event) => event.kind === 'start' && (event.name === 'book-title' || event.name === 'binary')
  ), false);
});

test('strict FB2 parsing blocks only an embedded image that exceeds generated budgets', () => {
  const parsed = parseStrictFb2(
    '<FictionBook><body><section><p>Readable text</p></section></body>'
      + '<binary id="large-cover" content-type="image/jpeg">QUJDRA==</binary></FictionBook>',
    { maxDepth: 20, maxNodes: 100, maxTextChars: 100 },
    { maxEncodedBytes: 4, maxDecodedBytes: 20, maxDecodedTotalBytes: 20 }
  );

  assert.equal(parsed.chapters[0]?.text, 'Readable text');
  assert.deepEqual(parsed.blockedResources, [{
    id: 'large-cover',
    ruleId: READER_SAFETY_RULE_IDS.FB2_IMAGE_BUDGET
  }]);
});

test('strict FB2 parsing preserves an unfamiliar image MIME for the decoder boundary', () => {
  const parsed = parseStrictFb2(
    '<FictionBook><body><section><p>Readable text</p></section></body>'
      + '<binary id="future-image" content-type="image/future-format">QUJD</binary></FictionBook>'
  );

  assert.equal(parsed.chapters[0]?.text, 'Readable text');
  assert.deepEqual(parsed.blockedResources, []);
});

test('strict FB2 parsing accepts bounded internal text entities and literalizes unresolved references', () => {
  const parsed = parseStrictFb2(
    '<!DOCTYPE FictionBook [<!ENTITY greeting "boom">]><FictionBook><body><p>&greeting; &external;</p></body></FictionBook>'
  );
  assert.equal(parsed.chapters[0]?.text, 'boom &external;');
});

test('strict FB2 parsing fails closed for malformed and parser-budget inputs', () => {
  for (const source of [
    '<FictionBook><body><section></body></FictionBook>',
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
    (reason: unknown) => reason instanceof ReaderSafetyPolicyError
      && reason.code === 'PUBLICATION_PARSER_LIMIT'
      && reason.ruleId === READER_SAFETY_RULE_IDS.FB2_STRUCTURE_BUDGET
  );
});
