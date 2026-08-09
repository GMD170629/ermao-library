import { renderRouter } from 'expo-router/testing-library';

import { routes } from './app-flow-router-fixture';

test('connection-required flow anchors at connect', async () => {
  const result = renderRouter(
    routes({ phase: 'connection-required', profileWarnings: [] }),
  );

  await Promise.resolve();
  await Promise.resolve();
  expect(result.getPathname()).toBe('/connect');
});
