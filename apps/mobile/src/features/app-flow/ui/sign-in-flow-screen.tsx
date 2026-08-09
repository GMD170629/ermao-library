import { useRouter } from 'expo-router';
import type { ReactNode } from 'react';

import type { AppFlowFailure, AppFlowState } from '../model/app-flow-state';
import { useAppFlow } from './app-flow-provider';
import { SignInScreen, type SignInIssue } from './sign-in-screen';

function issueFromFailure(
  failure: AppFlowFailure | undefined,
): SignInIssue | undefined {
  if (failure === undefined) return undefined;
  if (failure.area === 'server') {
    switch (failure.reason) {
      case 'CREDENTIALS_NOT_ALLOWED':
      case 'DEVICE_LOOPBACK_NOT_ALLOWED':
      case 'EMPTY':
      case 'INSECURE_REMOTE_NOT_ALLOWED':
      case 'INVALID':
      case 'QUERY_OR_FRAGMENT_NOT_ALLOWED':
      case 'UNSUPPORTED_SCHEME':
        return { area: 'url', reason: failure.reason };
      case 'cancelled':
      case 'network':
      case 'timeout':
        return { area: 'server', reason: failure.reason };
      case 'error':
        return { area: 'server', reason: 'unhealthy' };
      case 'invalid-response':
      case 'unexpected-http-status':
        return { area: 'server', reason: 'incompatible' };
      default:
        return { area: 'server', reason: 'unknown' };
    }
  }
  if (failure.area === 'profile') {
    switch (failure.reason) {
      case 'capacity-reached':
        return { area: 'profile', reason: 'capacity' };
      case 'conflict':
        return { area: 'profile', reason: 'conflict' };
      case 'corrupt-local-data':
        return { area: 'profile', reason: 'corrupt-storage' };
      case 'not-found':
        return { area: 'profile', reason: 'not-found' };
      case 'storage-unavailable':
        return { area: 'profile', reason: 'storage-unavailable' };
      default:
        return { area: 'profile', reason: 'unknown' };
    }
  }
  switch (failure.reason) {
    case 'account-disabled':
    case 'cancelled':
    case 'incompatible-response':
    case 'invalid-credentials':
    case 'network':
    case 'setup-required':
    case 'timeout':
      return { area: 'session', reason: failure.reason };
    default:
      return { area: 'session', reason: 'unknown' };
  }
}

function submissionPhase(
  state: Extract<
    AppFlowState,
    | { phase: 'authenticating' }
    | { phase: 'connecting'; intent: 'sign-in' }
    | { phase: 'signed-out' }
  >,
): 'authenticating' | 'connecting' | 'idle' {
  if (state.phase === 'authenticating') return 'authenticating';
  if (state.phase === 'connecting') return 'connecting';
  return 'idle';
}

export function SignInFlowScreen(): ReactNode {
  const flow = useAppFlow();
  const router = useRouter();
  const state = flow.state;
  if (
    state.phase !== 'signed-out' &&
    state.phase !== 'authenticating' &&
    (state.phase !== 'connecting' || state.intent !== 'sign-in')
  ) {
    return null;
  }
  const issue =
    state.phase === 'signed-out'
      ? issueFromFailure(state.warning)
      : undefined;

  return (
    <SignInScreen
      initialEmail={state.email}
      initialServerAddress={state.serverAddress}
      {...(issue === undefined ? {} : { issue })}
      onCancel={flow.cancelPendingLogin}
      onManageConnections={() => router.push('/connections')}
      onSignIn={(command) => {
        void flow.signIn(command);
      }}
      phase={submissionPhase(state)}
      profileWarnings={state.profileWarnings}
      setupRequired={
        state.phase === 'signed-out' && state.access === 'setup-required'
      }
    />
  );
}
