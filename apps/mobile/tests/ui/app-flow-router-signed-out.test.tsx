import { renderRouter } from 'expo-router/testing-library';

import { profile, routes } from './app-flow-router-fixture';

test('signed-out flow cannot enter main and anchors at login', async () => {
  const result = renderRouter(
    routes({
      phase: 'signed-out',
      profile: profile(),
      serverAddress: 'https://books.example.com',
      email: '',
      access: 'ready',
      reason: 'no-session',
      profileWarnings: [],
    }),
    { initialUrl: '/library' },
  );

  await Promise.resolve();
  await Promise.resolve();
  expect(result.getPathname()).toBe('/login');
});

test('a device without saved servers anchors at the unified sign-in screen', async () => {
  const result = renderRouter(
    routes({
      phase: 'signed-out',
      profile: null,
      serverAddress: '',
      email: '',
      access: 'ready',
      reason: 'no-session',
      profileWarnings: [],
    }),
  );

  await Promise.resolve();
  await Promise.resolve();
  expect(result.getPathname()).toBe('/login');
});

test('confirmed logout for connection management anchors at saved connections', async () => {
  const result = renderRouter(
    routes({
      phase: 'signed-out',
      profile: profile(),
      serverAddress: 'https://books.example.com',
      email: '',
      access: 'ready',
      reason: 'connection-management-requested',
      profileWarnings: [],
    }),
    { initialUrl: '/me' },
  );

  await Promise.resolve();
  await Promise.resolve();
  expect(result.getPathname()).toBe('/connections');
});
