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
    (reason: unknown) => reason instanceof ReaderSafetyPolicyError
      && reason.code === 'PUBLICATION_PARSER_LIMIT'
      && reason.ruleId === READER_SAFETY_RULE_IDS.FB2_STRUCTURE_BUDGET
  );
});
