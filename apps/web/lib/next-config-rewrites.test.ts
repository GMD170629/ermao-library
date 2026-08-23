import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const configPath = require.resolve('../next.config.js');

async function loadRewrites(pythonApiOrigin?: string) {
  const previousSkipRootEnv = process.env.SHUKU_SKIP_ROOT_ENV_LOAD;
  const previousPythonApiOrigin = process.env.PYTHON_API_ORIGIN;
  process.env.SHUKU_SKIP_ROOT_ENV_LOAD = 'true';
  if (pythonApiOrigin === undefined) delete process.env.PYTHON_API_ORIGIN;
  else process.env.PYTHON_API_ORIGIN = pythonApiOrigin;
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
    if (previousPythonApiOrigin === undefined) delete process.env.PYTHON_API_ORIGIN;
    else process.env.PYTHON_API_ORIGIN = previousPythonApiOrigin;
  }
}

test('always rewrites API and OPDS requests to the local Python backend', async () => {
  assert.deepEqual(await loadRewrites(), {
    beforeFiles: [
      {
        source: '/api/:path*',
        destination: 'http://127.0.0.1:8000/api/:path*'
      },
      {
        source: '/opds/:path*',
        destination: 'http://127.0.0.1:8000/opds/:path*'
      }
    ]
  });
});

test('allows an isolated loopback Python backend for full-stack tests', async () => {
  const rewrites = await loadRewrites('http://127.0.0.1:18000');
  assert.deepEqual(rewrites, {
    beforeFiles: [
      { source: '/api/:path*', destination: 'http://127.0.0.1:18000/api/:path*' },
      { source: '/opds/:path*', destination: 'http://127.0.0.1:18000/opds/:path*' }
    ]
  });
});

test('rejects a non-loopback Python backend', async () => {
  await assert.rejects(() => loadRewrites('https://example.com'), /loopback host/);
});
