import { Stack } from 'expo-router';
import type { ReactNode } from 'react';

import { useI18n } from '../../../shared/i18n/public';
import { useAppTheme } from '../../../shared/ui/public';

export default function LibraryLayout(): ReactNode {
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
        options={{ headerLargeTitle: true, title: t('library.shelves.title') }}
      />
      <Stack.Screen
        name="books"
        options={{ title: t('library.books.title') }}
      />
      <Stack.Screen
        name="collection/[collectionId]"
        options={{ title: t('library.shelves.collectionTitle') }}
      />
      <Stack.Screen
        name="import"
        options={{
          presentation: 'formSheet',
          sheetAllowedDetents: [0.65, 1],
          sheetGrabberVisible: true,
          sheetInitialDetentIndex: 0,
          title: t('library.import.title'),
        }}
      />
      <Stack.Screen
        name="shelf-editor"
        options={{
          presentation: 'formSheet',
          sheetAllowedDetents: [0.5, 0.9],
          sheetGrabberVisible: true,
          sheetInitialDetentIndex: 0,
          title: t('library.shelves.modalTitle'),
        }}
      />
    </Stack>
  );
}
