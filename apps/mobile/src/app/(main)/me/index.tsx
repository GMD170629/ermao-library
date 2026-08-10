import { Alert, View } from 'react-native';
import type { ReactNode } from 'react';

import { useAppFlow } from '../../../features/app-flow/public';
import { useI18n } from '../../../shared/i18n/public';
import {
  AppButton,
  ScreenScaffold,
  SurfaceCard,
  SystemListItem,
  useAppTheme,
} from '../../../shared/ui/public';

export default function MeRoute(): ReactNode {
  const flow = useAppFlow();
  const { t } = useI18n();
  const theme = useAppTheme();
  const state = flow.state;

  if (state.phase !== 'authenticated' && state.phase !== 'logging-out') {
    return null;
  }

  const pending = state.phase === 'logging-out';
  const session = state.session;
  const profile = state.profile;

  const confirmManageConnections = (): void => {
    Alert.alert(
      t('me.manageConnectionsConfirmTitle'),
      t('me.manageConnectionsConfirmBody'),
      [
        { text: t('common.cancel'), style: 'cancel' },
        {
          text: t('me.manageConnectionsConfirmAction'),
          onPress: () => {
            void flow.logoutForConnectionManagement();
          },
        },
      ],
    );
  };
  const confirmSignOut = (): void => {
    Alert.alert(t('me.signOutConfirmTitle'), t('me.signOutConfirmBody'), [
      { text: t('common.cancel'), style: 'cancel' },
      {
        text: t('me.signOutConfirmAction'),
        style: 'destructive',
        onPress: () => {
          void flow.logout();
        },
      },
    ]);
  };

  return (
    <ScreenScaffold edges={[]} testID="me-screen">
      <View
        style={{
          gap: theme.spacing.xl,
          paddingBottom: theme.spacing.xxl,
        }}
      >
        <SurfaceCard padding="none">
          <SystemListItem
            iconName="person"
            label={session.user.name}
            supportingText={session.user.email}
          />
        </SurfaceCard>
        <SurfaceCard padding="none">
          <SystemListItem
            iconName="server"
            label={t('me.serverLabel')}
            onPress={confirmManageConnections}
            supportingText={profile.baseUrl.value}
            testID="manage-server-connections"
          />
        </SurfaceCard>
        <AppButton
          accessibilityHint={t('me.signOutHint')}
          fullWidth
          iconName="logout"
          label={pending ? t('shell.loggingOut') : t('me.signOut')}
          loading={pending}
          onPress={confirmSignOut}
          variant="destructive"
        />
      </View>
    </ScreenScaffold>
  );
}
