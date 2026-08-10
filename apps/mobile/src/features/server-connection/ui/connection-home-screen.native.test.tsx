import type { ReactNode } from 'react';
import { fireEvent, render } from '@testing-library/react-native';

import { I18nProvider } from '../../../shared/i18n/public';
import { AppThemeProvider } from '../../../shared/ui/public';
import { ConnectionHomeScreen } from './connection-home-screen';

jest.mock('expo-localization', () => ({
  useLocales: () => [{ languageTag: 'en-US' }],
}));

function HomeFixture({
  activeServerUrl,
  mode = 'needs-connection',
  onEnterAddress,
  onManageProfiles,
  onScanQr,
}: Readonly<{
  activeServerUrl?: string;
  mode?: 'needs-connection' | 'signed-out';
  onEnterAddress: () => void;
  onManageProfiles?: () => void;
  onScanQr: () => void;
}>): ReactNode {
  return (
    <AppThemeProvider colorScheme="light">
      <I18nProvider>
        <ConnectionHomeScreen
          {...(activeServerUrl === undefined ? {} : { activeServerUrl })}
          mode={mode}
          onEnterAddress={onEnterAddress}
          {...(onManageProfiles === undefined ? {} : { onManageProfiles })}
          onScanQr={onScanQr}
        />
      </I18nProvider>
    </AppThemeProvider>
  );
}

describe('ConnectionHomeScreen', () => {
  test('offers both visible connection methods and emits their intentions', async () => {
    const onEnterAddress = jest.fn();
    const onScanQr = jest.fn();
    const view = await render(
      <HomeFixture
        onEnterAddress={onEnterAddress}
        onScanQr={onScanQr}
      />,
    );

    expect(view.getByText('Ermao Books')).toBeOnTheScreen();
    await fireEvent.press(
      view.getByRole('button', { name: 'Enter library web address' }),
    );
    await fireEvent.press(
      view.getByRole('button', { name: 'Scan a connection QR code' }),
    );

    expect(onEnterAddress).toHaveBeenCalledTimes(1);
    expect(onScanQr).toHaveBeenCalledTimes(1);
    await view.unmount();
  });

  test('shows the current address and profile management after sign-out', async () => {
    const onManageProfiles = jest.fn();
    const view = await render(
      <HomeFixture
        activeServerUrl="https://books.example.com/shuku"
        mode="signed-out"
        onEnterAddress={jest.fn()}
        onManageProfiles={onManageProfiles}
        onScanQr={jest.fn()}
      />,
    );

    expect(
      view.getByText('https://books.example.com/shuku'),
    ).toBeOnTheScreen();
    await fireEvent.press(
      view.getByRole('button', { name: 'Manage saved connections' }),
    );
    expect(onManageProfiles).toHaveBeenCalledTimes(1);
    await view.unmount();
  });
});
