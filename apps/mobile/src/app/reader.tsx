import { useRouter } from 'expo-router';
import type { ReactNode } from 'react';

import { PlaceholderScreen } from '../app-shell/public';

export default function ReaderRoute(): ReactNode {
  const router = useRouter();
  return (
    <PlaceholderScreen
      action={{
        hintKey: 'route.library.hint',
        labelKey: 'action.backToLibrary',
        onPress: () => router.replace('/library'),
      }}
      descriptionKey="route.reader.description"
      titleKey="route.reader.title"
    />
  );
}
