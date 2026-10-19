import assert from 'node:assert/strict';
import test from 'node:test';
import { READER_SAFETY_BUDGETS, READER_SAFETY_RULE_IDS } from '@shuku/reader-core';
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

test('strict FB2 parsing keeps images beyond former encoded and decoded image limits', () => {
  const encoded = 'QUJD'.repeat(Math.floor(READER_SAFETY_BUDGETS.fb2EncodedImageMaxBytes / 4) + 1);
  const parsed = parseStrictFb2(
    '<FictionBook><body><section><p>Readable text</p></section></body>'
      + `<binary id="large-cover" content-type="image/jpeg">${encoded}</binary></FictionBook>`
  );
  assert.equal(parsed.chapters[0]?.text, 'Readable text');
  assert.deepEqual(parsed.blockedResources, []);
});

test('strict FB2 parsing isolates malformed image data as resource integrity', () => {
  const parsed = parseStrictFb2('<FictionBook><body><p>Readable</p></body><binary id="broken">%%%broken</binary></FictionBook>');
  assert.deepEqual(parsed.blockedResources, [{
    id: 'broken', ruleId: READER_SAFETY_RULE_IDS.REFLOWABLE_OPTIONAL_RESOURCE_FAILURE
  }]);
});

test('strict FB2 parsing accepts structures beyond the former nesting limit', () => {
  const depth = READER_SAFETY_BUDGETS.fb2MaxDepth + 1;
  const parsed = parseStrictFb2(`<FictionBook><body>${'<section>'.repeat(depth)}<p>Deep text</p>${'</section>'.repeat(depth)}</body></FictionBook>`);
  assert.equal(parsed.chapters[0]?.text, 'Deep text');
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

test('strict FB2 parsing fails closed for malformed inputs', () => {
  for (const source of [
    '<FictionBook><body><section></body></FictionBook>',
    '<FictionBook><body><p>&broken</p></body></FictionBook>',
    '<bad:FictionBook><body><p>text</p></body></bad:FictionBook>',
    '<FictionBook><body bad:attr="x"><p>text</p></body></FictionBook>',
    '<FictionBook xmlns:xml="urn:not-xml"><body><p>text</p></body></FictionBook>',
    '<FictionBook xmlns:a="urn:same" xmlns:b="urn:same"><body a:id="one" b:id="two"><p>text</p></body></FictionBook>'
  ]) assert.throws(() => parseStrictFb2(source), /PUBLICATION_(?:MARKUP_INVALID|SECURITY_REJECTED)/);
});


test('strict FB2 accepts long valid numeric character references', () => {
  const parsed = parseStrictFb2(`<FictionBook><body><p>&#${'0'.repeat(40)}65;</p></body></FictionBook>`);
  assert.equal(parsed.chapters[0]?.text, 'A');
});

test('strict FB2 parsing accepts more nodes than the former structure ceiling', () => {
  const count = READER_SAFETY_BUDGETS.fb2MaxNodes + 1;
  const parsed = parseStrictFb2(`<FictionBook>${'<empty/>'.repeat(count)}<body><p>Complete body</p></body></FictionBook>`);
  assert.equal(parsed.events.filter((event) => event.kind === 'start' && event.name === 'empty').length, count);
  assert.equal(parsed.chapters[0]?.text, 'Complete body');
});
