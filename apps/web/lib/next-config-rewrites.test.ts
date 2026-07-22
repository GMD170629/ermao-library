import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const configPath = require.resolve('../next.config.js');

async function loadRewrites() {
  const previousSkipRootEnv = process.env.SHUKU_SKIP_ROOT_ENV_LOAD;
  process.env.SHUKU_SKIP_ROOT_ENV_LOAD = 'true';
  delete require.cache[configPath];
  try {
    const config = require(configPath) as { rewrites?: () => Promise<unknown> };
    return await config.rewrites?.();
  } finally {
    delete require.cache[configPath];
    if (previousSkipRootEnv === undefined) {
      delete process.env.SHUKU_SKIP_ROOT_ENV_LOAD;
    } else {
      process.env.SHUKU_SKIP_ROOT_ENV_LOAD = previousSkipRootEnv;
    }
  }
}

test('always rewrites API requests to the local Python backend', async () => {
  assert.deepEqual(await loadRewrites(), {
    beforeFiles: [
      {
        source: '/api/:path*',
        destination: 'http://127.0.0.1:8000/api/:path*'
      }
    ]
  });
});
