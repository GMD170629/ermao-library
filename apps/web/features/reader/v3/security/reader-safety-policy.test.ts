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

test('safe XHTML 1.1 declaration is accepted while its external DTD surface is removed', () => {
  const source = `${XHTML_11}<html xmlns="http://www.w3.org/1999/xhtml"><body>text&nbsp;&copy;</body></html>`;
  const preflight = preflightReflowableXml(source, READER_SAFETY_RULE_IDS.REFLOWABLE_REJECT_XML_ENTITY);
  assert.doesNotMatch(preflight, /doctype/i);
  assert.match(preflight, /<body>text&#160;&#169;<\/body>/);
});

test('internal subsets, entities, custom doctypes and duplicate doctypes fail with a generated rule id', () => {
  for (const source of [
    '<!DOCTYPE html [<!ENTITY x "boom">]><html/>',
    '<!DOCTYPE html><html/>',
    '<!DOCTYPE html SYSTEM "https://attacker.test/evil.dtd"><html/>',
    `${XHTML_11}<html><body>&custom;</body></html>`,
    `${XHTML_11}${XHTML_11}<html/>`
  ]) {
    assert.throws(
      () => preflightReflowableXml(source, READER_SAFETY_RULE_IDS.REFLOWABLE_REJECT_XML_ENTITY),
      (reason: unknown) => reason instanceof ReaderSafetyPolicyError
        && reason.ruleId === READER_SAFETY_RULE_IDS.REFLOWABLE_REJECT_XML_ENTITY
        && reason.message === 'PUBLICATION_SECURITY_REJECTED'
    );
  }
});

test('generated URI policy keeps local/user navigation and removes authored active or remote subresources', () => {
  assert.equal(authoredUriDisposition('../images/cover.jpg', 'subresource'), 'internal');
  assert.equal(authoredUriDisposition('https://example.test/', 'navigation'), 'user-navigation');
  assert.equal(authoredUriDisposition('mailto:reader@example.test', 'navigation'), 'user-navigation');
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
