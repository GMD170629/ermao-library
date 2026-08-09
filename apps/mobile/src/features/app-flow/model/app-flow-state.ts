import type { AuthenticatedSession } from '../../identity/public';
import type {
  ServerProfile,
  ServerProfilePersistenceWarning,
} from '../../server-connection/public';

export type AppFlowFailure = Readonly<{
  area: 'profile' | 'server' | 'session';
  operation: 'connect' | 'load-profile' | 'login' | 'logout' | 'restore';
  reason: string;
}>;

export type SignedOutReason =
  | 'connection-management-requested'
  | 'logout-confirmed'
  | 'no-session'
  | 'session-expired'
  | 'server-setup-required';

export type SignedOutState = Readonly<{
  phase: 'signed-out';
  profile: ServerProfile | null;
  serverAddress: string;
  email: string;
  access: 'ready' | 'setup-required';
  reason: SignedOutReason;
  profileWarnings: readonly ServerProfilePersistenceWarning[];
  warning?: AppFlowFailure;
}>;

export type AuthenticatedState = Readonly<{
  phase: 'authenticated';
  profile: ServerProfile;
  session: AuthenticatedSession;
  freshness: 'checking' | 'fresh' | 'stale';
  profileWarnings: readonly ServerProfilePersistenceWarning[];
  warning?: AppFlowFailure;
}>;

export type AppFlowState =
  | Readonly<{ phase: 'loading-profile' }>
  | Readonly<{
      phase: 'verifying-server';
      profile: ServerProfile;
      profileWarnings: readonly ServerProfilePersistenceWarning[];
    }>
  | Readonly<{
      phase: 'restoring-session';
      profile: ServerProfile;
      profileWarnings: readonly ServerProfilePersistenceWarning[];
    }>
  | Readonly<{
      phase: 'connection-required';
      profileWarnings: readonly ServerProfilePersistenceWarning[];
      failure?: AppFlowFailure;
    }>
  | Readonly<{
      phase: 'connecting';
      intent: 'connection';
      candidate: string;
      source: 'manual' | 'qr';
      profileWarnings: readonly ServerProfilePersistenceWarning[];
    }>
  | Readonly<{
      phase: 'connecting';
      intent: 'sign-in';
      candidate: string;
      source: 'manual';
      profile: ServerProfile | null;
      serverAddress: string;
      email: string;
      profileWarnings: readonly ServerProfilePersistenceWarning[];
    }>
  | Readonly<{
      phase: 'selecting-profile';
      profileId: string;
      profileWarnings: readonly ServerProfilePersistenceWarning[];
    }>
  | SignedOutState
  | Readonly<{
      phase: 'authenticating';
      profile: ServerProfile;
      serverAddress: string;
      email: string;
      profileWarnings: readonly ServerProfilePersistenceWarning[];
    }>
  | AuthenticatedState
  | Readonly<{
      phase: 'logging-out';
      intent: 'manage-connections' | 'sign-out';
      profile: ServerProfile;
      session: AuthenticatedSession;
      profileWarnings: readonly ServerProfilePersistenceWarning[];
    }>;

export function isConnectionFlow(state: AppFlowState): boolean {
  return (
    (state.phase === 'signed-out' &&
      state.reason === 'connection-management-requested') ||
    state.phase === 'connection-required' ||
    (state.phase === 'connecting' && state.intent === 'connection') ||
    state.phase === 'selecting-profile'
  );
}

export function canAccessConnectionFlow(state: AppFlowState): boolean {
  return isConnectionFlow(state) || state.phase === 'signed-out';
}

export function isIdentityFlow(state: AppFlowState): boolean {
  return (
    state.phase === 'signed-out' ||
    state.phase === 'authenticating' ||
    (state.phase === 'connecting' && state.intent === 'sign-in')
  );
}

export function isAuthenticatedFlow(state: AppFlowState): boolean {
  return state.phase === 'authenticated' || state.phase === 'logging-out';
}
