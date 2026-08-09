import { Alert, StyleSheet, View } from 'react-native';
import type { ReactNode } from 'react';

import { useAppFlow } from '../../features/app-flow/public';
import { useI18n } from '../../shared/i18n/public';
import {
  AppButton,
  AppIcon,
  AppText,
  PageHeader,
  ScreenScaffold,
  SurfaceCard,
  useAppTheme,
} from '../../shared/ui/public';

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
        <PageHeader title={t('me.title')} />
        <SurfaceCard>
          <View style={[styles.heading, { gap: theme.spacing.sm }]}>
            <AppIcon
              color={theme.colors.tint}
              decorative
              name="person"
            />
            <AppText variant="headline">{t('me.accountLabel')}</AppText>
          </View>
          <View style={{ gap: theme.spacing.xxs }}>
            <AppText variant="headline">{session.user.name}</AppText>
            <AppText muted>{session.user.email}</AppText>
          </View>
        </SurfaceCard>
        <SurfaceCard>
          <View style={[styles.heading, { gap: theme.spacing.sm }]}>
            <AppIcon
              color={theme.colors.tint}
              decorative
              name="server"
            />
            <AppText variant="headline">{t('me.serverLabel')}</AppText>
          </View>
          <AppText>{profile.baseUrl.value}</AppText>
          <AppButton
            accessibilityHint={t('me.manageConnectionsHint')}
            disabled={pending}
            fullWidth
            label={t('me.manageConnections')}
            leadingIcon={
              <AppIcon
                color={theme.colors.text}
                decorative
                name="settings"
                size={theme.control.iconMedium}
              />
            }
            onPress={confirmManageConnections}
            variant="secondary"
          />
        </SurfaceCard>
        <AppButton
          accessibilityHint={t('me.signOutHint')}
          fullWidth
          label={pending ? t('shell.loggingOut') : t('me.signOut')}
          leadingIcon={
            <AppIcon
              color={theme.colors.danger}
              decorative
              name="logout"
              size={theme.control.iconMedium}
            />
          }
          loading={pending}
          onPress={confirmSignOut}
          variant="destructive"
        />
      </View>
    </ScreenScaffold>
  );
}

const styles = StyleSheet.create({
  heading: {
    alignItems: 'center',
    flexDirection: 'row',
  },
});
