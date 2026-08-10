import { Stack } from 'expo-router';
import type { ReactNode } from 'react';

import { useI18n } from '../../../shared/i18n/public';
import { useAppTheme } from '../../../shared/ui/public';
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
        <Stack.Screen name="reader" />
      </Stack.Protected>
    </Stack>
  );
}

export function ProtectedConnectionRoutes({
  state: _state,
}: Readonly<{ state: AppFlowState }>): ReactNode {
  const { t } = useI18n();
  const theme = useAppTheme();
  return (
    <Stack
      screenOptions={{
        contentStyle: { backgroundColor: theme.colors.background },
        headerBackButtonDisplayMode: 'minimal',
        headerStyle: { backgroundColor: theme.colors.background },
        headerTintColor: theme.colors.tint,
        headerTitleStyle: { color: theme.colors.text },
      }}
    >
      <Stack.Screen
        name="connect"
        options={{ headerShown: false, title: t('connection.home.title') }}
      />
      <Stack.Screen
        name="address"
        options={{ title: t('connection.address.title') }}
      />
      <Stack.Screen
        name="scan"
        options={{ title: t('connection.qr.title') }}
      />
      <Stack.Screen
        name="connections"
        options={{ title: t('connection.profiles.title') }}
      />
    </Stack>
  );
}
