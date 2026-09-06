import assert from 'node:assert/strict';
import test from 'node:test';
import {
  materializeFb2Chapter,
  materializeTextChapter
} from './text-publication.worker';
import { parseStrictFb2 } from './strict-fb2-parser';

function markup(bytes: ArrayBuffer): string {
  return new TextDecoder().decode(bytes);
}

test('TXT chapter materialization places the core heading target in the body', () => {
  const chapter = materializeTextChapter(
    'text/chapter-0001.xhtml#heading-000001',
    '第一章',
    '正文内容',
    'heading-000001'
  );
  const body = markup(chapter.bytes).split('<body>', 2)[1]?.split('</body>', 1)[0] ?? '';
  assert.equal(body, '<h1 id="heading-000001">第一章</h1><p>正文内容</p>');
  assert.equal((body.match(/第一章/gu) ?? []).length, 1);
});

test('FB2 section materialization places top-level and nested core targets around source content', () => {
  const parsed = parseStrictFb2(
    '<FictionBook><body><section><title><p>One <em>inline</em></p></title><p>Inside</p>'
      + 'before-nested <section><title><p>Nested</p></title><p>Child</p></section>'
      + ' after-nested <p>After</p><p></p></section></body></FictionBook>'
  );
  const sectionStarts = parsed.events.filter((event) => event.kind === 'start' && event.name === 'section');
  const source = parsed.sections[0];
  assert.ok(source);
  const chapter = materializeFb2Chapter(source, source.title ?? 'Book');
  const body = markup(chapter.bytes).split('<body>', 2)[1]?.split('</body>', 1)[0] ?? '';
  const topAnchor = sectionStarts[0]?.targetHref?.split('#')[1];
  const nestedAnchor = sectionStarts[1]?.targetHref?.split('#')[1];
  assert.ok(topAnchor);
  assert.ok(nestedAnchor);
  assert.match(body, new RegExp(`<section id="${topAnchor}">`));
  assert.match(body, new RegExp(`<section id="${nestedAnchor}">`));
  assert.match(body, /<h1>One inline<\/h1>/);
  assert.match(body, /<h2>Nested<\/h2>/);
  assert.equal((body.match(/<h[12]>/gu) ?? []).length, 2);
  assert.match(body, /<p><\/p>/);
  assert.ok(body.indexOf(`<section id="${nestedAnchor}">`) < body.indexOf('<p>Child</p>'));
  assert.ok(body.indexOf('<p>Inside</p>') < body.indexOf(`<section id="${nestedAnchor}">`));
  assert.ok(body.indexOf('before-nested') < body.indexOf(`<section id="${nestedAnchor}">`));
  assert.ok(body.indexOf(`<section id="${nestedAnchor}">`) < body.indexOf('after-nested'));
});

test('FB2 loose body materialization keeps direct text around paragraphs', () => {
  const parsed = parseStrictFb2(
    '<FictionBook><body>before <p>paragraph</p> after'
      + '<section><title><p>Chapter</p></title><p>body</p></section></body></FictionBook>'
  );
  const fragment = parsed.bodyFragments[0];
  assert.ok(fragment);
  const chapter = materializeFb2Chapter(fragment, 'Book');
  const body = markup(chapter.bytes).split('<body>', 2)[1]?.split('</body>', 1)[0] ?? '';
  assert.ok(body.indexOf('before ') < body.indexOf('<p>paragraph</p>'));
  assert.ok(body.indexOf('<p>paragraph</p>') < body.indexOf(' after'));
});
