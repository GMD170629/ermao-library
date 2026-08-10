import { useRouter } from 'expo-router';
import type { ReactNode } from 'react';

import {
  ConnectionHomeScreen,
  QrScannerScreen,
  ServerAddressScreen,
  type ConnectionIssue,
  type ConnectionSubmissionState,
} from '../../server-connection/ui/public';
import type { AppFlowFailure, AppFlowState } from '../model/app-flow-state';
import { useAppFlow } from './app-flow-provider';

function connectionIssue(failure: AppFlowFailure): ConnectionIssue {
  switch (failure.reason) {
    case 'CREDENTIALS_NOT_ALLOWED':
    case 'DEVICE_LOOPBACK_NOT_ALLOWED':
    case 'EMPTY':
    case 'INSECURE_REMOTE_NOT_ALLOWED':
    case 'INVALID':
    case 'QUERY_OR_FRAGMENT_NOT_ALLOWED':
    case 'UNSUPPORTED_SCHEME':
    case 'cancelled':
    case 'network':
    case 'timeout':
      return failure.reason;
    case 'capacity-reached':
      return 'capacity';
    case 'conflict':
      return 'conflict';
    case 'corrupt-local-data':
      return 'corrupt-storage';
    case 'storage-unavailable':
      return 'storage-unavailable';
    case 'invalid-response':
    case 'unexpected-http-status':
      return 'incompatible';
    case 'error':
      return 'unhealthy';
    default:
      return 'unknown';
  }
}

function submissionState(state: AppFlowState): ConnectionSubmissionState {
  if (state.phase === 'connecting' && state.intent === 'connection') {
    return { status: 'connecting' };
  }
  if (
    state.phase === 'connection-required' &&
    state.failure !== undefined
  ) {
    return { status: 'failed', issue: connectionIssue(state.failure) };
  }
  return { status: 'idle' };
}

export function ConnectionHomeFlowScreen(): ReactNode {
  const router = useRouter();
  const { state } = useAppFlow();
  const navigation = {
    onEnterAddress: () => router.push('/address'),
    onScanQr: () => router.push('/scan'),
  };
  return state.phase === 'signed-out' && state.profile !== null ? (
    <ConnectionHomeScreen
      activeServerUrl={state.profile.baseUrl.value}
      mode="signed-out"
      onEnterAddress={navigation.onEnterAddress}
      onManageProfiles={() => router.push('/connections')}
      onScanQr={navigation.onScanQr}
    />
  ) : (
    <ConnectionHomeScreen
      mode="needs-connection"
      onEnterAddress={navigation.onEnterAddress}
      onScanQr={navigation.onScanQr}
    />
  );
}

export function ServerAddressFlowScreen(): ReactNode {
  const router = useRouter();
  const flow = useAppFlow();
  return (
    <ServerAddressScreen
      onCancel={flow.cancelPendingConnection}
      onConnect={(address) => {
        void flow.connect(address, 'manual');
      }}
      onScanQr={() => router.push('/scan')}
      state={submissionState(flow.state)}
    />
  );
}

export function QrScannerFlowScreen(): ReactNode {
  const flow = useAppFlow();
  return (
    <QrScannerScreen
      onCodeAccepted={(payload) => {
        void flow.connect(payload, 'qr');
      }}
      onScanAgain={flow.cancelPendingConnection}
      state={submissionState(flow.state)}
    />
  );
}
