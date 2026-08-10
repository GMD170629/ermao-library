import type { ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { useI18n } from '../shared/i18n/public';
import { InlineNotice, useAppTheme } from '../shared/ui/public';
import { AppStatusBar } from './app-shell';

export type MainApplicationShellProps = Readonly<{
  children: ReactNode;
  sessionWarning?: 'logout-failed' | 'session-stale';
}>;

export function MainApplicationShell({
  children,
  sessionWarning,
}: MainApplicationShellProps): ReactNode {
  const theme = useAppTheme();
  const { t } = useI18n();
  return (
    <View
      style={[styles.root, { backgroundColor: theme.colors.background }]}
    >
      <AppStatusBar />
      {sessionWarning === undefined ? null : (
        <SafeAreaView
          edges={['top', 'right', 'left']}
          style={[
            styles.warning,
            {
              backgroundColor: theme.colors.background,
              paddingHorizontal: theme.spacing.md,
              paddingBottom: theme.spacing.xs,
            },
          ]}
        >
          <InlineNotice
            body={
              sessionWarning === 'logout-failed'
                ? t('shell.logoutFailureBody')
                : t('shell.sessionStaleBody')
            }
            title={
              sessionWarning === 'logout-failed'
                ? t('shell.logoutFailureTitle')
                : t('shell.sessionStaleTitle')
            }
            tone="warning"
          />
        </SafeAreaView>
      )}
      <View style={styles.navigation}>{children}</View>
    </View>
  );
}

const styles = StyleSheet.create({
  navigation: { flex: 1 },
  root: { flex: 1 },
  warning: { width: '100%' },
});
