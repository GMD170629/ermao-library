import assert from 'node:assert/strict';
import test from 'node:test';

import type {
  ApiRequest,
  ApiTransport,
  ApiTransportResult,
} from '../../../shared/api/public';
import { parseServerAddress } from '../../server-connection/public';
import { IdentitySession } from '../application/identity-session';
import { CookieSessionClient } from './cookie-session-client';

const sessionEnvelope = {
  ok: true,
  data: {
    user: {
      id: 'user-1',
      email: 'reader@example.com',
      name: 'Reader',
      role: 'member',
      status: 'active',
      canManageSystem: false,
      canViewManualImports: false,
      authzVersion: 2,
      avatarUrl: null,
      locale: 'en-US',
    },
    authorization: {
      isAdmin: false,
      canManageSystem: false,
      allLibraryScopes: false,
      monitorFolderIds: ['folder-1'],
      canViewManualImports: false,
      authzVersion: 2,
    },
    preferences: {
      locale: 'en-US',
      'library.view': 'grid',
      'library.sort': 'recent_read',
      'library.sortDirection': 'desc',
      'audio.playbackRate': 1.25,
    },
  },
} as const;

const responseHeaders = {
  contentType: 'application/json',
  etag: null,
  lastModified: null,
} as const;

class StubTransport implements ApiTransport {
  readonly requests: ApiRequest[] = [];
  private resultIndex = 0;

  constructor(private readonly results: readonly ApiTransportResult[]) {}

  async request(request: ApiRequest): Promise<ApiTransportResult> {
    this.requests.push(request);
    const result = this.results[this.resultIndex];
    this.resultIndex += 1;
    if (result === undefined) {
      throw new Error('Missing stub transport result');
    }
    return result;
  }
}

function baseUrl() {
  const parsed = parseServerAddress('https://books.example.com/shuku');
  assert.equal(parsed.ok, true);
  if (!parsed.ok) {
    assert.fail('Expected test server URL to be valid');
  }
  return parsed.baseUrl;
}

test('logs in with the current cookie session contract and reverse-proxy path', async () => {
  const transport = new StubTransport([
    {
      ok: true,
      responseType: 'json',
      status: 200,
      headers: responseHeaders,
      body: sessionEnvelope,
    },
  ]);
  const identity = new IdentitySession(new CookieSessionClient(transport));

  const result = await identity.login(baseUrl(), {
    email: ' Reader@Example.com ',
    password: 'password',
  });

  assert.equal(result.outcome, 'authenticated');
  if (result.outcome !== 'authenticated') {
    assert.fail('Expected current session response to authenticate');
  }
  assert.equal(result.session.user.id, 'user-1');
  assert.deepEqual(transport.requests[0], {
    body: {
      kind: 'json',
      value: { email: 'reader@example.com', password: 'password' },
    },
    maximumResponseBytes: 128 * 1024,
    method: 'POST',
    responseType: 'json',
    signal: transport.requests[0]?.signal,
    timeoutMs: 12_000,
    url: 'https://books.example.com/shuku/api/auth/login',
  });
});

test('maps the current setup-required and unauthenticated responses', async () => {
  const transport = new StubTransport([
    {
      ok: true,
      responseType: 'json',
      status: 409,
      headers: responseHeaders,
      body: {
        ok: false,
        error: {
          message: '系统尚未初始化',
          details: { code: 'SETUP_REQUIRED' },
        },
      },
    },
    {
      ok: true,
      responseType: 'json',
      status: 401,
      headers: responseHeaders,
      body: { ok: false, error: { message: 'UNAUTHORIZED' } },
    },
  ]);
  const client = new CookieSessionClient(transport);

  assert.deepEqual(
    await client.login(baseUrl(), {
      email: 'reader@example.com',
      password: 'password',
    }),
    { outcome: 'rejected', reason: 'setup-required' },
  );
  assert.deepEqual(await client.restoreSession(baseUrl()), {
    outcome: 'unauthenticated',
  });
});

test('validates setup status and logout envelopes', async () => {
  const client = new CookieSessionClient(
    new StubTransport([
      {
        ok: true,
        responseType: 'json',
        status: 200,
        headers: responseHeaders,
        body: { ok: true, data: { initialized: true } },
      },
      {
        ok: true,
        responseType: 'json',
        status: 200,
        headers: responseHeaders,
        body: { ok: true, data: { loggedOut: true } },
      },
    ]),
  );

  assert.deepEqual(await client.loadSetupStatus(baseUrl()), {
    outcome: 'loaded',
    initialized: true,
  });
  assert.deepEqual(await client.logout(baseUrl()), {
    outcome: 'logged-out',
  });
});
