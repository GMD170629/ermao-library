import { renderRouter } from 'expo-router/testing-library';

import { routes } from './app-flow-router-fixture';

test('profile load failure still keeps connection settings reachable from sign in', async () => {
  const result = renderRouter(
    routes({
      phase: 'signed-out',
      profile: null,
      serverAddress: '',
      email: '',
      access: 'ready',
      reason: 'no-session',
      profileWarnings: [],
      warning: {
        area: 'profile',
        operation: 'load-profile',
        reason: 'corrupt-local-data',
      },
    }),
    { initialUrl: '/address' },
  );

  await Promise.resolve();
  await Promise.resolve();
  expect(result.getPathname()).toBe('/address');
});
