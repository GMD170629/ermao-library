import type { AuthenticatedSession } from '../../identity/public';
import type {
  CancellationToken,
  ServerProfile,
  ServerProfilePersistenceWarning,
} from '../../server-connection/public';
import type { AppFlowFailure } from '../model/app-flow-state';

export type ActiveProfileResult =
  | Readonly<{
      outcome: 'loaded';
      profile: ServerProfile | null;
      warnings: readonly ServerProfilePersistenceWarning[];
    }>
  | Readonly<{ outcome: 'failed'; failure: AppFlowFailure }>;

export type ConnectProfileResult =
  | Readonly<{
      outcome: 'connected';
      profile: ServerProfile;
      warnings: readonly ServerProfilePersistenceWarning[];
    }>
  | Readonly<{ outcome: 'failed'; failure: AppFlowFailure }>;

export type RestoreFlowSessionResult =
  | Readonly<{
      outcome: 'authenticated';
      session: AuthenticatedSession;
    }>
  | Readonly<{ outcome: 'unauthenticated' }>
  | Readonly<{ outcome: 'failed'; failure: AppFlowFailure }>;

export type LoginFlowResult =
  | Readonly<{
      outcome: 'authenticated';
      session: AuthenticatedSession;
    }>
  | Readonly<{
      outcome: 'rejected';
      reason: 'account-disabled' | 'invalid-credentials' | 'setup-required';
    }>
  | Readonly<{ outcome: 'failed'; failure: AppFlowFailure }>;

export type LogoutFlowResult =
  | Readonly<{ outcome: 'logged-out' }>
  | Readonly<{ outcome: 'failed'; failure: AppFlowFailure }>;

export type SignInCommand = Readonly<{
  serverAddress: string;
  email: string;
  password: string;
}>;

export interface AppFlowGateway {
  loadActiveProfile(cancellation: CancellationToken): Promise<ActiveProfileResult>;
  recheckProfile(
    profile: ServerProfile,
    cancellation: CancellationToken,
  ): Promise<ConnectProfileResult>;
  selectProfile(
    profileId: string,
    cancellation: CancellationToken,
  ): Promise<ConnectProfileResult>;
  connect(
    candidate: string,
    source: 'manual' | 'qr',
    cancellation: CancellationToken,
  ): Promise<ConnectProfileResult>;
  restoreSession(
    profile: ServerProfile,
    cancellation: CancellationToken,
  ): Promise<RestoreFlowSessionResult>;
  login(
    profile: ServerProfile,
    credentials: Readonly<{ email: string; password: string }>,
    cancellation: CancellationToken,
  ): Promise<LoginFlowResult>;
  logout(
    profile: ServerProfile,
    cancellation: CancellationToken,
  ): Promise<LogoutFlowResult>;
}

export interface AppFlowCancellationSource {
  readonly token: CancellationToken;
  cancel(): void;
}

export interface AppFlowCancellationFactory {
  create(): AppFlowCancellationSource;
}
