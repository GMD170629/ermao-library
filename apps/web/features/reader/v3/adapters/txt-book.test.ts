import assert from 'node:assert/strict';
import test from 'node:test';
import { TxtEncodingError, decodeTxt, makeTxtBook, splitTxtSections } from './txt-book';

test('decodeTxt accepts UTF-8 BOM, UTF-16 BOM and strict GB18030 fallback', () => {
  assert.equal(decodeTxt(new Uint8Array([0xef, 0xbb, 0xbf, 0x41])), 'A');
  assert.equal(decodeTxt(new Uint8Array([0xff, 0xfe, 0x41, 0x00])), 'A');
  assert.equal(decodeTxt(new Uint8Array([0xd6, 0xd0, 0xce, 0xc4])), '中文');
});

test('decodeTxt rejects empty and suspicious NUL-padded inputs', () => {
  assert.throws(() => decodeTxt(new Uint8Array()), TxtEncodingError);
  assert.throws(() => decodeTxt(new Uint8Array([0x41, 0, 0x42, 0])), TxtEncodingError);
});

test('splitTxtSections creates deterministic Chinese and English chapters', () => {
  const sections = splitTxtSections(`序言\n第一段\n\n第一章 开始\n章节正文\n\nChapter 2 End\nLast page`);
  assert.deepEqual(sections.map((section) => section.title), ['序言', '第一章 开始', 'Chapter 2 End']);
  assert.equal(sections[1]?.text, '章节正文');
});

test('makeTxtBook exposes the official book interface navigation surface', () => {
  const book = makeTxtBook('第一章 开始\n正文', '示例');
  assert.equal(book.sections.length, 1);
  assert.deepEqual(book.toc, [{ label: '第一章 开始', href: 'txt-section:0' }]);
  assert.equal(book.resolveHref('txt-section:0')?.index, 0);
  assert.equal(book.resolveHref('txt-section:9'), null);
  assert.ok((book.sections[0]?.size ?? 0) > 0);
});
