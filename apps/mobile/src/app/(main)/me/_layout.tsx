import { Stack } from 'expo-router';
import type { ReactNode } from 'react';

import { useI18n } from '../../../shared/i18n/public';
import { useAppTheme } from '../../../shared/ui/public';

export default function MeLayout(): ReactNode {
  const { t } = useI18n();
  const theme = useAppTheme();
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
        options={{ headerLargeTitle: true, title: t('me.title') }}
      />
    </Stack>
  );
}
