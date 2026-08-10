import { NativeTabs } from 'expo-router/unstable-native-tabs';
import { useMemo, type ReactNode } from 'react';

import { MainApplicationShell } from '../../app-shell/public';
import { mobileRuntime } from '../../bootstrap/mobile-runtime';
import { useAppFlow } from '../../features/app-flow/public';
import {
  AbortLibraryCancellationFactory,
  ExpoLibraryCoverStore,
  ExpoLibraryFilePicker,
  LibraryClient,
  LibraryController,
  LibraryProvider,
} from '../../features/library/public';
import { useI18n } from '../../shared/i18n/public';
import { useAppTheme } from '../../shared/ui/public';

export default function MainLayout(): ReactNode {
  const flow = useAppFlow();
  const { t } = useI18n();
  const theme = useAppTheme();
  const authenticatedState =
    flow.state.phase === 'authenticated' ||
    flow.state.phase === 'logging-out'
      ? flow.state
      : null;
  const baseUrl = authenticatedState?.profile.baseUrl ?? null;
  const canImport =
    authenticatedState?.session.authorization.canManageSystem ?? false;
  const libraryController = useMemo(
    () =>
      baseUrl === null
        ? null
        : new LibraryController(
            new LibraryClient(mobileRuntime.apiTransport),
            new AbortLibraryCancellationFactory(),
            {
              context: { baseUrl, canImport },
              coverStore: new ExpoLibraryCoverStore(),
              filePicker: new ExpoLibraryFilePicker(),
              onSessionExpired: flow.sessionExpired,
            },
          ),
    [baseUrl, canImport, flow.sessionExpired],
  );
  const sessionWarning =
    flow.state.phase === 'authenticated' &&
    flow.state.warning !== undefined
      ? flow.state.warning.operation === 'logout'
        ? 'logout-failed'
        : 'session-stale'
      : undefined;

  const navigation = (
    <MainApplicationShell
      {...(sessionWarning === undefined ? {} : { sessionWarning })}
    >
      <NativeTabs
        backBehavior="history"
        backgroundColor={theme.colors.card}
        iconColor={{
          default: theme.colors.textMuted,
          selected: theme.colors.tint,
        }}
        indicatorColor={theme.colors.tintMuted}
        labelStyle={{
          default: { color: theme.colors.textMuted },
          selected: { color: theme.colors.tintText },
        }}
        labelVisibilityMode="labeled"
        minimizeBehavior="automatic"
        sidebarAdaptable
        tintColor={theme.colors.tint}
      >
        <NativeTabs.Trigger
          accessibilityLabel={t('route.home.label')}
          name="home"
          testID="native-tab-home"
        >
          <NativeTabs.Trigger.Icon
            md={{ default: 'home', selected: 'home' }}
            sf={{ default: 'house', selected: 'house.fill' }}
          />
          <NativeTabs.Trigger.Label>
            {t('route.home.label')}
          </NativeTabs.Trigger.Label>
        </NativeTabs.Trigger>
        <NativeTabs.Trigger
          accessibilityLabel={t('route.library.label')}
          name="library"
          testID="native-tab-library"
        >
          <NativeTabs.Trigger.Icon
            md={{ default: 'local_library', selected: 'local_library' }}
            sf={{
              default: 'books.vertical',
              selected: 'books.vertical.fill',
            }}
          />
          <NativeTabs.Trigger.Label>
            {t('route.library.label')}
          </NativeTabs.Trigger.Label>
        </NativeTabs.Trigger>
        <NativeTabs.Trigger
          accessibilityLabel={t('route.me.label')}
          name="me"
          testID="native-tab-me"
        >
          <NativeTabs.Trigger.Icon
            md={{ default: 'account_circle', selected: 'account_circle' }}
            sf={{
              default: 'person.crop.circle',
              selected: 'person.crop.circle.fill',
            }}
          />
          <NativeTabs.Trigger.Label>
            {t('route.me.label')}
          </NativeTabs.Trigger.Label>
        </NativeTabs.Trigger>
      </NativeTabs>
    </MainApplicationShell>
  );
  return libraryController === null ? (
    navigation
  ) : (
    <LibraryProvider controller={libraryController}>
      {navigation}
    </LibraryProvider>
  );
}
