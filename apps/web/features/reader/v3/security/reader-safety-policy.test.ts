import assert from 'node:assert/strict';
import test from 'node:test';
import {
  READER_SAFETY_RULE_IDS,
  readerSafetyRule
} from '@shuku/reader-core';
import {
  ReaderSafetyPolicyError,
  authoredUriDisposition,
  preflightReflowableXml,
  rejectReaderSafety,
  sanitizeAuthoredCss
} from './reader-safety-policy';

const XHTML_11 = '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"\n  "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">';

test('any well-formed declaration is accepted while its external DTD surface is removed', () => {
  const source = `${XHTML_11}<html xmlns="http://www.w3.org/1999/xhtml"><body>text&nbsp;&copy;</body></html>`;
  const preflight = preflightReflowableXml(source);
  assert.doesNotMatch(preflight, /doctype/i);
  assert.match(preflight, /<body>text&#160;&#169;<\/body>/);
});

test('custom roots, internal text entities, external entities and unknown references remain parser-safe literals', () => {
  const source = '<!DOCTYPE custom SYSTEM "https://attacker.test/evil.dtd"><custom>&external;&unknown;</custom>';
  const preflight = preflightReflowableXml(source);
  assert.doesNotMatch(preflight, /doctype/i);
  assert.match(preflight, /&amp;external;&amp;unknown;/);

  const internal = preflightReflowableXml(
    '<!DOCTYPE html [<!ENTITY greeting "Hello"><!ENTITY nested "&greeting;, world">]><html><body>&nested;</body></html>'
  );
  assert.match(internal, /<body>Hello, world<\/body>/);

  const recursive = preflightReflowableXml(
    '<!DOCTYPE html [<!ENTITY cycle "&cycle;">]><html><body>&cycle;</body></html>'
  );
  assert.match(recursive, /&amp;cycle;/);
});

test('DTD comments and processing instructions cannot smuggle entity declarations', () => {
  const source = '<!DOCTYPE html [<!-- <!ENTITY masked "bad"> --><?ignored <!ENTITY alsoMasked "bad"> ?><!ENTITY real "ok">]><html><body>&real;&masked;&alsoMasked;</body></html>';
  const preflight = preflightReflowableXml(source);
  assert.match(preflight, /<body>ok&amp;masked;&amp;alsoMasked;<\/body>/);
});

test('quoted DOCTYPE identifiers are scanned as quoted text even when they contain comment syntax', () => {
  const source = '<!DOCTYPE r SYSTEM "https://example.test/<!--quoted"><r>ok</r>';
  const preflight = preflightReflowableXml(source);
  assert.doesNotMatch(preflight, /doctype/i);
  assert.equal(preflight, '<r>ok</r>');
});

test('quoted non-entity DTD declarations cannot mask or create entity declarations', () => {
  const source = '<!DOCTYPE r [<!ATTLIST r marker "<!-- <!ENTITY masked \'bad\'> -->"><!ENTITY real "ok">]><r>&real;&masked;</r>';
  const preflight = preflightReflowableXml(source);
  assert.match(preflight, /<r>ok&amp;masked;<\/r>/);
});

test('large DTD text is scanned with bounded prefix checks', () => {
  const source = `<!DOCTYPE r [${'x'.repeat(50_000)}]><r>ok</r>`;
  assert.equal(preflightReflowableXml(source), '<r>ok</r>');
});

test('a long malformed ampersand suffix is copied in one bounded scan', () => {
  const source = `<r>${'&'.repeat(50_000)}</r>`;
  assert.equal(preflightReflowableXml(source), source);
});

test('an expansion beyond the role budget is literalized without truncating the document', () => {
  const source = '<!DOCTYPE r [<!ENTITY huge "12345678901234567890">]><r>&huge;</r>';
  const preflight = preflightReflowableXml(source, 17);
  assert.equal(preflight, '<r>&amp;huge;</r>');
});

test('repeated entity references share the role budget instead of accumulating unbounded expansions', () => {
  const source = '<!DOCTYPE r [<!ENTITY chunk "12345678901234567890">]><r>&chunk;&chunk;</r>';
  const preflight = preflightReflowableXml(source, 40);
  assert.equal(preflight, '<r>12345678901234567890&amp;chunk;</r>');
});

test('control-document expansion uses the generated control-document budget rule', () => {
  assert.throws(
    () => preflightReflowableXml('<container>oversized</container>', 10, READER_SAFETY_RULE_IDS.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES),
    (reason: unknown) => reason instanceof ReaderSafetyPolicyError
      && reason.ruleId === READER_SAFETY_RULE_IDS.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES
  );
});

test('generated URI policy keeps local/user navigation and removes authored active or remote subresources', () => {
  assert.equal(authoredUriDisposition('../images/cover.jpg', 'subresource'), 'internal');
  assert.equal(authoredUriDisposition('https://example.test/', 'navigation'), 'user-navigation');
  assert.equal(authoredUriDisposition('mailto:reader@example.test', 'navigation'), 'user-navigation');
  assert.equal(authoredUriDisposition('future-scheme:value', 'navigation'), 'user-navigation');
  assert.equal(authoredUriDisposition('future-scheme:value', 'subresource'), 'preserve');
  for (const uri of ['javascript:alert(1)', 'data:text/html,x', 'blob:https://example.test/x', '//example.test/a', 'https://example.test/a']) {
    assert.equal(authoredUriDisposition(uri, 'subresource'), 'remove');
  }
});

test('CSS policy preserves local resources, drops remote imports and removes active declarations', async () => {
  const sanitized = await sanitizeAuthoredCss(
    '@import "theme.css"; @import "https://example.test/a.css"; body{background:url(images/a.png)}',
    async (value) => `blob:runtime/${value}`
  );
  assert.match(sanitized, /blob:runtime\/theme\.css/);
  assert.match(sanitized, /blob:runtime\/images\/a\.png/);
  assert.doesNotMatch(sanitized, /example\.test/);
  assert.equal(await sanitizeAuthoredCss('p{width:expression(alert(1))}', async () => null), '');
  assert.equal(
    await sanitizeAuthoredCss(
      '@import url(https://example.com/x.css);p{behavior:url(x);color:red}',
      async () => null
    ),
    'p{color:red}'
  );
});

test('reject helper derives action and public code from the generated decision table', () => {
  const ruleId = READER_SAFETY_RULE_IDS.EPUB_ARCHIVE_STRUCTURE;
  const rule = readerSafetyRule(ruleId);
  assert.throws(
    () => rejectReaderSafety(ruleId),
    (reason: unknown) => reason instanceof ReaderSafetyPolicyError
      && reason.ruleId === ruleId
      && reason.action === rule.action
      && reason.code === rule.errorCode
  );
});
