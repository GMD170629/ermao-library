import { useRouter } from 'expo-router';
import { useState, type ReactNode } from 'react';

import {
  encodeBooksRouteQuery,
  LibraryHomeScreen,
  LibraryImportModal,
  useLibrary,
} from '../../features/library/public';
import { useAppThemeController } from '../../shared/ui/public';

export default function HomeRoute(): ReactNode {
  const router = useRouter();
  const library = useLibrary();
  const theme = useAppThemeController();
  const [importVisible, setImportVisible] = useState(false);

  return (
    <>
      <LibraryHomeScreen
        coverSource={library.coverSource}
        importState={library.state.import}
        onImport={() => setImportVisible(true)}
        onOpenBooks={() =>
          router.push({
            pathname: '/library/books',
            params: encodeBooksRouteQuery({
              ...library.state.books.query,
              shelfId: null,
            }),
          })
        }
        onRefresh={() => {
          void library.loadHome();
        }}
        onRetry={() => {
          void library.loadHome();
        }}
        onToggleTheme={theme.toggleColorScheme}
        state={library.state.home}
        themeMode={theme.colorScheme}
      />
      <LibraryImportModal
        onClose={() => setImportVisible(false)}
        visible={importVisible}
      />
    </>
  );
}
