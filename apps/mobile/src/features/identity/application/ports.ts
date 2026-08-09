import type {
  CancellationToken,
  ServerBaseUrl,
} from '../../server-connection/public';
import type { AuthenticatedSession } from '../model/session';

export type IdentityTransportFailure = Readonly<{
  outcome: 'failure';
  reason: 'cancelled' | 'incompatible-response' | 'network' | 'timeout';
  status?: number;
}>;

export type LoginResult =
  | Readonly<{ outcome: 'authenticated'; session: AuthenticatedSession }>
  | Readonly<{
      outcome: 'rejected';
      reason: 'account-disabled' | 'invalid-credentials' | 'setup-required';
    }>
  | IdentityTransportFailure;

export type RestoreSessionResult =
  | Readonly<{ outcome: 'authenticated'; session: AuthenticatedSession }>
  | Readonly<{ outcome: 'unauthenticated' }>
  | IdentityTransportFailure;

export type LogoutResult =
  | Readonly<{ outcome: 'logged-out' }>
  | IdentityTransportFailure;

export type SetupStatusResult =
  | Readonly<{ outcome: 'loaded'; initialized: boolean }>
  | IdentityTransportFailure;

export interface IdentityGateway {
  loadSetupStatus(
    baseUrl: ServerBaseUrl,
    cancellation?: CancellationToken,
  ): Promise<SetupStatusResult>;
  login(
    baseUrl: ServerBaseUrl,
    credentials: Readonly<{ email: string; password: string }>,
    cancellation?: CancellationToken,
  ): Promise<LoginResult>;
  logout(
    baseUrl: ServerBaseUrl,
    cancellation?: CancellationToken,
  ): Promise<LogoutResult>;
  restoreSession(
    baseUrl: ServerBaseUrl,
    cancellation?: CancellationToken,
  ): Promise<RestoreSessionResult>;
}
