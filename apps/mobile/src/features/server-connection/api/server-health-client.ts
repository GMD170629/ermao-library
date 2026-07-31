import type { JsonTransport } from '../../../shared/api/json-transport';
import type {
  CancellationToken,
  ServerHealthGateway,
  ServerHealthProbeResult,
  ServerUnreachableReason,
} from '../application/ports';
import {
  serverHealthUrl,
  type ServerBaseUrl,
} from '../model/server-address';
import { decodeServiceHealth } from './health-schema';

const HEALTH_TIMEOUT_MS = 8_000;
const HEALTH_MAXIMUM_RESPONSE_BYTES = 16 * 1024;

export class ServerHealthClient implements ServerHealthGateway {
  constructor(private readonly transport: JsonTransport) {}

  async probe(
    baseUrl: ServerBaseUrl,
    cancellation?: CancellationToken,
  ): Promise<ServerHealthProbeResult> {
    const controller = new AbortController();
    const unsubscribe = cancellation?.subscribe(() => {
      controller.abort();
    });
    if (cancellation?.isCancellationRequested()) {
      controller.abort();
    }

    try {
      const response = await this.transport.get({
        maximumResponseBytes: HEALTH_MAXIMUM_RESPONSE_BYTES,
        signal: controller.signal,
        timeoutMs: HEALTH_TIMEOUT_MS,
        url: serverHealthUrl(baseUrl),
      });
      if (!response.ok) {
        if (
          response.reason === 'invalid-json' ||
          response.reason === 'response-too-large'
        ) {
          return {
            outcome: 'incompatible',
            reason: 'invalid-response',
            status: response.status,
          };
        }
        const reason: ServerUnreachableReason =
          response.reason === 'aborted'
            ? 'cancelled'
            : response.reason;
        return { outcome: 'unreachable', reason };
      }

      const health = decodeServiceHealth(response.body);
      if (!health.ok) {
        return {
          outcome: 'incompatible',
          reason: 'invalid-response',
          status: response.status,
        };
      }

      if (health.value.status === 'error') {
        return { outcome: 'unhealthy', status: 'error' };
      }
      if (response.status !== 200) {
        return {
          outcome: 'incompatible',
          reason: 'unexpected-http-status',
          status: response.status,
        };
      }
      return { outcome: 'healthy' };
    } finally {
      unsubscribe?.();
    }
  }
}