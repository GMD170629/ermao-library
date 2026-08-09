import { renderRouter } from 'expo-router/testing-library';

import { profile, routes, session } from './app-flow-router-fixture';

test('authenticated flow cannot enter connection management', async () => {
  const result = renderRouter(
    routes({
      phase: 'authenticated',
      profile: profile(),
      session: session(),
      freshness: 'fresh',
      profileWarnings: [],
    }),
    { initialUrl: '/connections' },
  );

  await Promise.resolve();
  await Promise.resolve();
  expect(result.getPathname()).toBe('/home');
});
