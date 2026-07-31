import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import path from 'node:path';
import test from 'node:test';

const require = createRequire(import.meta.url);
const configPath = require.resolve('../next.config.js');

type NextConfigContract = {
  allowedDevOrigins?: string[];
  basePath?: string;
  devIndicators?: false | { position?: string };
  experimental?: Record<string, unknown>;
  output?: string;
  outputFileTracingRoot?: string;
  webpack?: unknown;
};

function loadConfig(configuredBasePath?: string): NextConfigContract {
  const previousBasePath = process.env.NEXT_PUBLIC_BASE_PATH;
  const previousSkipRootEnv = process.env.SHUKU_SKIP_ROOT_ENV_LOAD;
  process.env.SHUKU_SKIP_ROOT_ENV_LOAD = 'true';
  if (configuredBasePath === undefined) {
    delete process.env.NEXT_PUBLIC_BASE_PATH;
  } else {
    process.env.NEXT_PUBLIC_BASE_PATH = configuredBasePath;
  }
  delete require.cache[configPath];

  try {
    return require(configPath) as NextConfigContract;
  } finally {
    delete require.cache[configPath];
    if (previousBasePath === undefined) {
      delete process.env.NEXT_PUBLIC_BASE_PATH;
    } else {
      process.env.NEXT_PUBLIC_BASE_PATH = previousBasePath;
    }
    if (previousSkipRootEnv === undefined) {
      delete process.env.SHUKU_SKIP_ROOT_ENV_LOAD;
    } else {
      process.env.SHUKU_SKIP_ROOT_ENV_LOAD = previousSkipRootEnv;
    }
  }
}

test('Next 16 standalone tracing starts at the workspace root', () => {
  const config = loadConfig();

  assert.equal(config.output, 'standalone');
  assert.equal(
    path.resolve(config.outputFileTracingRoot ?? ''),
    path.resolve('../..')
  );
  assert.equal(
    config.experimental?.outputFileTracingRoot,
    undefined,
    'Next 16 requires outputFileTracingRoot at the top level'
  );
});

test('basePath remains normalized for sub-path deployments', () => {
  assert.equal(loadConfig().basePath, '');
  assert.equal(loadConfig('/').basePath, '');
  assert.equal(loadConfig(' /books/ ').basePath, '/books');
  assert.equal(loadConfig('///nas/library///').basePath, '/nas/library');
});

test('the default Turbopack build is not shadowed by a webpack override', () => {
  const config = loadConfig();

  assert.equal(
    config.webpack,
    undefined,
    'a webpack override needs an explicit Turbopack migration and production regression coverage'
  );
});

test('Playwright loopback traffic is allowed by the Next 16 development server', () => {
  const config = loadConfig();

  assert.deepEqual(config.allowedDevOrigins, ['127.0.0.1']);
  assert.equal(config.devIndicators, false);
});
