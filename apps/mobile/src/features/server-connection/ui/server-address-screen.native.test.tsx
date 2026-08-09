import type { ReactNode } from 'react';
import { fireEvent, render } from '@testing-library/react-native';

import { I18nProvider } from '../../../shared/i18n/public';
import { AppThemeProvider } from '../../../shared/ui/public';
import { ServerAddressScreen } from './server-address-screen';

jest.mock('expo-localization', () => ({
  useLocales: () => [{ languageTag: 'en-US' }],
}));

const noOperation = (): void => undefined;

function AddressFixture({
  initialAddress,
  onCancel = noOperation,
  onConnect,
  state = { status: 'idle' },
}: Readonly<{
  initialAddress: string;
  onCancel?: () => void;
  onConnect: (address: string) => void;
  state?: Parameters<typeof ServerAddressScreen>[0]['state'];
}>): ReactNode {
  return (
    <AppThemeProvider colorScheme="light">
      <I18nProvider>
        <ServerAddressScreen
          initialAddress={initialAddress}
          onBack={noOperation}
          onCancel={onCancel}
          onConnect={onConnect}
          onScanQr={noOperation}
          state={state}
        />
      </I18nProvider>
    </AppThemeProvider>
  );
}

describe('ServerAddressScreen public address contract', () => {
  test('asks for the browser-facing library address and submits it unchanged', async () => {
    const onConnect = jest.fn<void, [string]>();
    const view = await render(
      <AddressFixture
        initialAddress=" https://books.example.com/shuku/ "
        onConnect={onConnect}
      />,
    );

    expect(view.getByText('Enter library web address')).toBeOnTheScreen();
    expect(
      view.getByText(
        'Enter the root address where Ermao Books opens in your browser. The app automatically uses the API on the same domain and base path; do not enter a backend address or /api path.',
      ),
    ).toBeOnTheScreen();

    expect(view.getByLabelText('Library web address')).toBeOnTheScreen();
    await fireEvent.press(
      view.getByRole('button', { name: 'Connect library' }),
    );

    expect(onConnect).toHaveBeenCalledWith(
      'https://books.example.com/shuku/',
    );
    await view.unmount();
  });

  test('keeps validation feedback beside the field without clearing its value', async () => {
    const view = await render(
      <AddressFixture
        initialAddress="books.example.com"
        onConnect={jest.fn()}
        state={{ issue: 'INSECURE_REMOTE_NOT_ALLOWED', status: 'failed' }}
      />,
    );

    expect(
      view.getByText('Public servers must use HTTPS.'),
    ).toBeOnTheScreen();
    expect(view.getByLabelText('Library web address')).toHaveProp(
      'value',
      'books.example.com',
    );
    await view.unmount();
  });

  test('disables address editing and offers cancellation while connecting', async () => {
    const onCancel = jest.fn();
    const view = await render(
      <AddressFixture
        initialAddress="https://books.example.com"
        onCancel={onCancel}
        onConnect={jest.fn()}
        state={{ status: 'connecting' }}
      />,
    );

    expect(view.getByLabelText('Library web address')).toHaveProp(
      'editable',
      false,
    );
    await fireEvent.press(
      view.getByRole('button', { name: 'Cancel' }),
    );
    expect(onCancel).toHaveBeenCalledTimes(1);
    await view.unmount();
  });
});
