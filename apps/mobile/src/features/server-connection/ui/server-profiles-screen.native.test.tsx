import type { ReactNode } from 'react';
import { Alert } from 'react-native';
import { fireEvent, render } from '@testing-library/react-native';

import { I18nProvider } from '../../../shared/i18n/public';
import { AppThemeProvider } from '../../../shared/ui/public';
import { ServerProfilesScreen } from './server-profiles-screen';
import type { ServerProfilesViewState } from './contracts';

jest.mock('expo-localization', () => ({
  useLocales: () => [{ languageTag: 'en-US' }],
}));

const noOperation = (): void => undefined;

function ProfilesFixture({
  mode = 'editable',
  onResetCorrupt = noOperation,
  state,
}: Readonly<{
  mode?: 'editable' | 'read-only';
  onResetCorrupt?: () => void;
  state: ServerProfilesViewState;
}>): ReactNode {
  const screen =
    mode === 'editable' ? (
      <ServerProfilesScreen
        mode="editable"
        onAddAddress={noOperation}
        onAddQr={noOperation}
        onBack={noOperation}
        onDelete={noOperation}
        onResetCorrupt={onResetCorrupt}
        onRetry={noOperation}
        onSelect={noOperation}
        state={state}
      />
    ) : (
      <ServerProfilesScreen
        mode="read-only"
        onBack={noOperation}
        onRetry={noOperation}
        state={state}
      />
    );

  return (
    <AppThemeProvider colorScheme="light">
      <I18nProvider>{screen}</I18nProvider>
    </AppThemeProvider>
  );
}

describe('ServerProfilesScreen', () => {
  test('offers destructive reset only for completely corrupt storage', async () => {
    const networkView = await render(
      <ProfilesFixture
        state={{ issue: 'network', status: 'failed' }}
      />,
    );

    expect(
      networkView.queryByRole('button', {
        name: 'Reset local server connections',
      }),
    ).toBeNull();
    await networkView.unmount();

    const corruptView = await render(
      <ProfilesFixture
        state={{ issue: 'corrupt-storage', status: 'failed' }}
      />,
    );
    expect(
      corruptView.getByRole('button', {
        name: 'Reset local server connections',
      }),
    ).toBeOnTheScreen();
    await corruptView.unmount();
  });

  test('requires confirmation before emitting a corrupt reset', async () => {
    const onResetCorrupt = jest.fn();
    const alertSpy = jest
      .spyOn(Alert, 'alert')
      .mockImplementation(() => undefined);
    const view = await render(
      <ProfilesFixture
        onResetCorrupt={onResetCorrupt}
        state={{ issue: 'corrupt-storage', status: 'failed' }}
      />,
    );

    await fireEvent.press(
      view.getByRole('button', {
        name: 'Reset local server connections',
      }),
    );
    expect(onResetCorrupt).not.toHaveBeenCalled();

    const alertButtons = alertSpy.mock.calls[0]?.[2];
    alertButtons
      ?.find((button) => button.style === 'destructive')
      ?.onPress?.();
    expect(onResetCorrupt).toHaveBeenCalledTimes(1);
    alertSpy.mockRestore();
    await view.unmount();
  });

  test('renders typed recovery warnings above an empty catalog', async () => {
    const view = await render(
      <ProfilesFixture
        state={{
          profiles: [],
          status: 'ready',
          warnings: [
            'recovered-older-snapshot',
            'maintenance-cleanup-failed',
          ],
        }}
      />,
    );

    expect(
      view.getByText(/older valid snapshot was restored/),
    ).toBeOnTheScreen();
    expect(
      view.getByText(/old snapshots could not be cleaned up/),
    ).toBeOnTheScreen();
    await view.unmount();
  });

  test('keeps recovery-unknown catalogs readable without write actions', async () => {
    const view = await render(
      <ProfilesFixture
        mode="read-only"
        state={{
          profiles: [
            {
              active: false,
              basePath: '/reader-service',
              baseUrl: 'https://books.example.com',
              id: 'server-1',
              initialized: true,
              lastVerifiedAtMs: 1_700_000_000_000,
            },
          ],
          status: 'ready',
          warnings: ['recovered-older-snapshot'],
        }}
      />,
    );

    expect(view.getByText('https://books.example.com')).toBeOnTheScreen();
    expect(view.getByText('Base path')).toBeOnTheScreen();
    expect(view.getByText('/reader-service')).toBeOnTheScreen();
    expect(
      view.getByRole('button', { name: 'Refresh recovery state' }),
    ).toBeOnTheScreen();
    expect(
      view.queryByRole('button', { name: 'Select' }),
    ).toBeNull();
    expect(
      view.queryByRole('button', { name: 'Delete' }),
    ).toBeNull();
    expect(
      view.queryByRole('button', { name: 'Add library web address' }),
    ).toBeNull();
    await view.unmount();
  });
});
