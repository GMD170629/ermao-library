import type {
  ApiJsonTransportResult,
  ApiTransport,
  ApiTransportResult,
} from '../../../shared/api/public';
import {
  serverApiUrl,
  type CancellationToken,
  type ServerBaseUrl,
} from '../../server-connection/public';
import type {
  IdentityGateway,
  IdentityTransportFailure,
  LoginResult,
  LogoutResult,
  RestoreSessionResult,
  SetupStatusResult,
} from '../application/ports';
import {
  decodeLoggedOutEnvelope,
  decodeSessionEnvelope,
  decodeSetupStatusEnvelope,
  errorCode,
} from './session-schema';

const AUTH_TIMEOUT_MS = 12_000;
const AUTH_MAXIMUM_RESPONSE_BYTES = 128 * 1024;

function transportFailure(
  result: Exclude<ApiTransportResult, Readonly<{ ok: true }>>,
): IdentityTransportFailure {
  if (result.reason === 'aborted') {
    return { outcome: 'failure', reason: 'cancelled' };
  }
  if (result.reason === 'network' || result.reason === 'timeout') {
    return { outcome: 'failure', reason: result.reason };
  }
  return {
    outcome: 'failure',
    reason: 'incompatible-response',
    status: 'status' in result ? result.status : 0,
  };
}

export class CookieSessionClient implements IdentityGateway {
  constructor(private readonly transport: ApiTransport) {}

  async loadSetupStatus(
    baseUrl: ServerBaseUrl,
    cancellation?: CancellationToken,
  ): Promise<SetupStatusResult> {
    const response = await this.request(
      baseUrl,
      '/api/auth/setup/status',
      'GET',
      cancellation,
    );
    if (!response.ok) {
      return transportFailure(response);
    }
    const decoded = decodeSetupStatusEnvelope(response.body);
    return response.status === 200 && decoded.ok
      ? { outcome: 'loaded', initialized: decoded.value.initialized }
      : {
          outcome: 'failure',
          reason: 'incompatible-response',
          status: response.status,
        };
  }

  async login(
    baseUrl: ServerBaseUrl,
    credentials: Readonly<{ email: string; password: string }>,
    cancellation?: CancellationToken,
  ): Promise<LoginResult> {
    const response = await this.request(
      baseUrl,
      '/api/auth/login',
      'POST',
      cancellation,
      credentials,
    );
    if (!response.ok) {
      return transportFailure(response);
    }
    if (response.status === 401) {
      return { outcome: 'rejected', reason: 'invalid-credentials' };
    }
    const code = errorCode(response.body);
    if (response.status === 409 && code === 'SETUP_REQUIRED') {
      return { outcome: 'rejected', reason: 'setup-required' };
    }
    if (response.status === 403 && code === 'ACCOUNT_DISABLED') {
      return { outcome: 'rejected', reason: 'account-disabled' };
    }
    const decoded = decodeSessionEnvelope(response.body);
    return response.status === 200 && decoded.ok
      ? { outcome: 'authenticated', session: decoded.value }
      : {
          outcome: 'failure',
          reason: 'incompatible-response',
          status: response.status,
        };
  }

  async logout(
    baseUrl: ServerBaseUrl,
    cancellation?: CancellationToken,
  ): Promise<LogoutResult> {
    const response = await this.request(
      baseUrl,
      '/api/auth/logout',
      'POST',
      cancellation,
    );
    if (!response.ok) {
      return transportFailure(response);
    }
    return response.status === 200 && decodeLoggedOutEnvelope(response.body)
      ? { outcome: 'logged-out' }
      : {
          outcome: 'failure',
          reason: 'incompatible-response',
          status: response.status,
        };
  }

  async restoreSession(
    baseUrl: ServerBaseUrl,
    cancellation?: CancellationToken,
  ): Promise<RestoreSessionResult> {
    const response = await this.request(
      baseUrl,
      '/api/auth/me',
      'GET',
      cancellation,
    );
    if (!response.ok) {
      return transportFailure(response);
    }
    if (response.status === 401) {
      return { outcome: 'unauthenticated' };
    }
    const decoded = decodeSessionEnvelope(response.body);
    return response.status === 200 && decoded.ok
      ? { outcome: 'authenticated', session: decoded.value }
      : {
          outcome: 'failure',
          reason: 'incompatible-response',
          status: response.status,
        };
  }

  private async request(
    baseUrl: ServerBaseUrl,
    path: `/api/${string}`,
    method: 'GET' | 'POST',
    cancellation?: CancellationToken,
    body?: unknown,
  ): Promise<ApiJsonTransportResult> {
    const controller = new AbortController();
    const unsubscribe = cancellation?.subscribe(() => controller.abort());
    if (cancellation?.isCancellationRequested()) {
      controller.abort();
    }
    try {
      const result = await this.transport.request({
        ...(body === undefined
          ? {}
          : { body: { kind: 'json' as const, value: body } }),
        maximumResponseBytes: AUTH_MAXIMUM_RESPONSE_BYTES,
        method,
        responseType: 'json',
        signal: controller.signal,
        timeoutMs: AUTH_TIMEOUT_MS,
        url: serverApiUrl(baseUrl, path),
      });
      return result.ok && result.responseType !== 'json'
        ? {
            ok: false,
            reason: 'invalid-json',
            status: result.status,
          }
        : result;
    } finally {
      unsubscribe?.();
    }
  }
}
