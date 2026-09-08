import assert from 'node:assert/strict';
import test from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { AccountAvatar } from './account-avatar';

test('default display URL renders even when no custom avatar exists', () => {
  const markup = renderToStaticMarkup(createElement(AccountAvatar, {
    account: { avatarUrl: null, avatarImageUrl: '/api/auth/avatar' },
    alt: 'Account avatar', size: 64
  }));
  assert.match(markup, /src="[^"]*\/api\/auth\/avatar"/);
  assert.doesNotMatch(markup, /\/icons\//);
});

test('missing server image never invents a default image', () => {
  const markup = renderToStaticMarkup(createElement(AccountAvatar, {
    account: { avatarUrl: null }, alt: 'Account avatar', size: 64
  }));
  assert.doesNotMatch(markup, /<img/);
  assert.match(markup, /aria-label="Account avatar"/);
});
