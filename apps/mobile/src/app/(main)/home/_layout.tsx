import { Stack } from 'expo-router';
import type { ReactNode } from 'react';

import { useI18n } from '../../../shared/i18n/public';
import {
  SystemActionMenu,
  useAppTheme,
  useAppThemeController,
} from '../../../shared/ui/public';

export default function HomeLayout(): ReactNode {
  const { t } = useI18n();
  const theme = useAppTheme();
  const themeController = useAppThemeController();
  return (
    <Stack
      screenOptions={{
        contentStyle: { backgroundColor: theme.colors.background },
        headerStyle: { backgroundColor: theme.colors.background },
        headerTintColor: theme.colors.tint,
        headerTitleStyle: { color: theme.colors.text },
      }}
    >
      <Stack.Screen
        name="index"
        options={{
          headerLargeTitle: true,
          headerRight: () => (
            <SystemActionMenu
              accessibilityLabel={t('library.home.themeHint')}
              actions={[
                {
                  id: 'system',
                  selected: themeController.preference === 'system',
                  title: t('library.home.useSystemTheme'),
                },
                {
                  id: 'light',
                  selected: themeController.preference === 'light',
                  title: t('library.home.useLightTheme'),
                },
                {
                  id: 'dark',
                  selected: themeController.preference === 'dark',
                  title: t('library.home.useDarkTheme'),
                },
              ]}
              iconName="sun"
              onAction={themeController.setPreference}
              testID="home-theme-menu"
              title={t('library.home.themeMenuTitle')}
            />
          ),
          title: t('library.home.title'),
        }}
      />
    </Stack>
  );
}
