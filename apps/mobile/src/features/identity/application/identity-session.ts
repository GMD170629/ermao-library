import type {
  CancellationToken,
  ServerBaseUrl,
} from '../../server-connection/public';
import type {
  IdentityGateway,
  LoginResult,
  LogoutResult,
  RestoreSessionResult,
  SetupStatusResult,
} from './ports';

export class IdentitySession {
  constructor(private readonly gateway: IdentityGateway) {}

  loadSetupStatus(
    baseUrl: ServerBaseUrl,
    cancellation?: CancellationToken,
  ): Promise<SetupStatusResult> {
    return cancellation === undefined
      ? this.gateway.loadSetupStatus(baseUrl)
      : this.gateway.loadSetupStatus(baseUrl, cancellation);
  }

  login(
    baseUrl: ServerBaseUrl,
    credentials: Readonly<{ email: string; password: string }>,
    cancellation?: CancellationToken,
  ): Promise<LoginResult> {
    const email = credentials.email.trim().toLowerCase();
    if (email.length === 0 || credentials.password.length === 0) {
      return Promise.resolve({
        outcome: 'rejected',
        reason: 'invalid-credentials',
      });
    }
    return cancellation === undefined
      ? this.gateway.login(baseUrl, { email, password: credentials.password })
      : this.gateway.login(
          baseUrl,
          { email, password: credentials.password },
          cancellation,
        );
  }

  logout(
    baseUrl: ServerBaseUrl,
    cancellation?: CancellationToken,
  ): Promise<LogoutResult> {
    return cancellation === undefined
      ? this.gateway.logout(baseUrl)
      : this.gateway.logout(baseUrl, cancellation);
  }

  restoreSession(
    baseUrl: ServerBaseUrl,
    cancellation?: CancellationToken,
  ): Promise<RestoreSessionResult> {
    return cancellation === undefined
      ? this.gateway.restoreSession(baseUrl)
      : this.gateway.restoreSession(baseUrl, cancellation);
  }
}
