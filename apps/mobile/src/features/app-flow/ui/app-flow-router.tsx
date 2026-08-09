import { Stack } from 'expo-router';
import type { ReactNode } from 'react';

import type { AppFlowState } from '../model/app-flow-state';
import {
  canAccessConnectionFlow,
  isAuthenticatedFlow,
  isConnectionFlow,
  isIdentityFlow,
} from '../model/app-flow-state';

export type AppFlowAnchorHref =
  | '/connect'
  | '/connections'
  | '/home'
  | '/login';

export function appFlowAnchorHref(
  state: AppFlowState,
): AppFlowAnchorHref | null {
  if (
    state.phase === 'signed-out' &&
    state.reason === 'connection-management-requested'
  ) {
    return '/connections';
  }
  if (isConnectionFlow(state)) return '/connect';
  if (isIdentityFlow(state)) return '/login';
  if (isAuthenticatedFlow(state)) return '/home';
  return null;
}

export function ProtectedApplicationRoutes({
  state,
}: Readonly<{ state: AppFlowState }>): ReactNode {
  const connectionGroupAvailable = canAccessConnectionFlow(state);
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="index" />
      <Stack.Protected guard={connectionGroupAvailable}>
        <Stack.Screen name="(connection)" />
      </Stack.Protected>
      <Stack.Protected guard={isIdentityFlow(state)}>
        <Stack.Screen name="(auth)" />
      </Stack.Protected>
      <Stack.Protected guard={isAuthenticatedFlow(state)}>
        <Stack.Screen name="(main)" />
      </Stack.Protected>
    </Stack>
  );
}

export function ProtectedConnectionRoutes({
  state: _state,
}: Readonly<{ state: AppFlowState }>): ReactNode {
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="connect" />
      <Stack.Screen name="address" />
      <Stack.Screen name="scan" />
      <Stack.Screen name="connections" />
    </Stack>
  );
}
