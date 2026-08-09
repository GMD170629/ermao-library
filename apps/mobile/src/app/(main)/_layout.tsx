import { Slot } from 'expo-router';
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

export default function MainLayout(): ReactNode {
  const flow = useAppFlow();
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

  const shell = (
    <MainApplicationShell
      {...(sessionWarning === undefined ? {} : { sessionWarning })}
    >
      <Slot />
    </MainApplicationShell>
  );
  return libraryController === null ? (
    shell
  ) : (
    <LibraryProvider controller={libraryController}>
      {shell}
    </LibraryProvider>
  );
}
