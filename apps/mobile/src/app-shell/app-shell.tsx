import { StatusBar } from 'expo-status-bar';
import { StyleSheet, View } from 'react-native';
import {
  initialWindowMetrics,
  SafeAreaProvider,
  SafeAreaView,
} from 'react-native-safe-area-context';
import type { ReactNode } from 'react';

import { I18nProvider, useI18n } from '../shared/i18n/public';
import { ExpoThemePreferenceStore } from '../shared/preferences/public';
import { AppThemeProvider, useAppTheme } from '../shared/ui/public';

const themePreferenceStore = new ExpoThemePreferenceStore();

export type MobileRootProvidersProps = Readonly<{
  children: ReactNode;
}>;

export function MobileRootProviders({
  children,
}: MobileRootProvidersProps): ReactNode {
  return (
    <SafeAreaProvider initialMetrics={initialWindowMetrics}>
      <AppThemeProvider preferenceStore={themePreferenceStore}>
        <I18nProvider>
          <LocalizedApplicationRoot>{children}</LocalizedApplicationRoot>
        </I18nProvider>
      </AppThemeProvider>
    </SafeAreaProvider>
  );
}

function LocalizedApplicationRoot({
  children,
}: MobileRootProvidersProps): ReactNode {
  const { locale } = useI18n();
  const theme = useAppTheme();
  return (
    <View
      accessibilityLanguage={locale}
      style={[
        styles.root,
        { backgroundColor: theme.colors.background },
      ]}
    >
      {children}
    </View>
  );
}

export function AppStatusBar(): ReactNode {
  const theme = useAppTheme();
  return <StatusBar style={theme.isDark ? 'light' : 'dark'} />;
}

export function StandaloneApplicationSurface({
  children,
}: MobileRootProvidersProps): ReactNode {
  const theme = useAppTheme();
  return (
    <SafeAreaView
      edges={['top', 'right', 'bottom', 'left']}
      style={[
        styles.surface,
        { backgroundColor: theme.colors.background },
      ]}
    >
      <AppStatusBar />
      {children}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  surface: {
    flex: 1,
  },
});
