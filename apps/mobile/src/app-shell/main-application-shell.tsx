import type { ReactNode } from 'react';
import { StyleSheet, useWindowDimensions, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { useI18n } from '../shared/i18n/public';
import {
  InlineNotice,
  useAppTheme,
} from '../shared/ui/public';
import { AppStatusBar } from './app-shell';
import { shouldUseExpandedNavigation } from './navigation';
import { ShellNavigation } from './shell-navigation';

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
  const { fontScale, width } = useWindowDimensions();
  const expanded = shouldUseExpandedNavigation({
    availableWidth: width,
    expandedMinimumWidth: theme.breakpoint.expandedMinWidth,
    fontScale,
  });
  return (
    <SafeAreaView
      edges={['top', 'right', 'bottom', 'left']}
      style={[
        styles.safeArea,
        { backgroundColor: theme.colors.background },
      ]}
    >
      <AppStatusBar />
      <View style={[styles.workspace, expanded && styles.expandedWorkspace]}>
        {expanded ? (
          <View
            style={[
              styles.sidebar,
              {
                backgroundColor: theme.colors.card,
                borderColor: theme.colors.border,
              },
            ]}
          >
            <ShellNavigation expanded />
          </View>
        ) : null}
        <View style={styles.contentColumn}>
          {sessionWarning === undefined ? null : (
            <View
              style={[
                styles.warning,
                {
                  maxWidth: theme.breakpoint.contentMaxWidth,
                  paddingHorizontal:
                    theme.breakpoint.compactHorizontalPadding,
                  paddingVertical: theme.spacing.xs,
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
            </View>
          )}
          <View style={styles.screen}>{children}</View>
          {!expanded ? <ShellNavigation expanded={false} /> : null}
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  contentColumn: {
    flex: 1,
    minWidth: 0,
  },
  expandedWorkspace: {
    flexDirection: 'row',
  },
  safeArea: {
    flex: 1,
  },
  screen: {
    flex: 1,
  },
  sidebar: {
    borderRightWidth: StyleSheet.hairlineWidth,
    width: 232,
  },
  workspace: {
    flex: 1,
  },
  warning: {
    alignSelf: 'center',
    width: '100%',
  },
});
