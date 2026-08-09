import type { ReactNode } from 'react';
import { fireEvent, render } from '@testing-library/react-native';
import { AppState } from 'react-native';

import { I18nProvider } from '../../../shared/i18n/public';
import { AppThemeProvider } from '../../../shared/ui/public';
import type { ConnectionSubmissionState } from './contracts';
import { QrScannerScreen } from './qr-scanner-screen';

let mockCameraPermission: Readonly<{
  canAskAgain: boolean;
  granted: boolean;
}> | null = { canAskAgain: true, granted: true };
const mockRequestCameraPermission = jest.fn();

jest.mock('expo-camera', () => ({
  CameraView: () => null,
  useCameraPermissions: () => [
    mockCameraPermission,
    mockRequestCameraPermission,
  ],
}));

jest.mock('expo-localization', () => ({
  useLocales: () => [{ languageTag: 'en-US' }],
}));

const noOperation = (): void => undefined;
const originalAppState = Object.getOwnPropertyDescriptor(
  AppState,
  'currentState',
);

beforeAll(() => {
  Object.defineProperty(AppState, 'currentState', {
    configurable: true,
    value: 'active',
  });
});

beforeEach(() => {
  mockCameraPermission = { canAskAgain: true, granted: true };
  mockRequestCameraPermission.mockReset();
});

afterAll(() => {
  if (originalAppState !== undefined) {
    Object.defineProperty(AppState, 'currentState', originalAppState);
  }
});

function ScannerFixture({
  onOpenSettings,
  onScanAgain = noOperation,
  state,
}: Readonly<{
  onOpenSettings?: () => Promise<void>;
  onScanAgain?: () => void;
  state: ConnectionSubmissionState;
}>): ReactNode {
  return (
    <AppThemeProvider colorScheme="light">
      <I18nProvider>
        <QrScannerScreen
          onBack={noOperation}
          onCodeAccepted={noOperation}
          {...(onOpenSettings === undefined ? {} : { onOpenSettings })}
          onScanAgain={onScanAgain}
          state={state}
        />
      </I18nProvider>
    </AppThemeProvider>
  );
}

describe('QrScannerScreen submission state', () => {
  test('renders controller-owned connecting progress', async () => {
    const view = await render(
      <ScannerFixture state={{ status: 'connecting' }} />,
    );

    expect(
      view.getByText('QR code recognized. Checking the library…'),
    ).toBeOnTheScreen();
    await view.unmount();
  });

  test('renders a named failure and unlock intention', async () => {
    const onScanAgain = jest.fn();
    const view = await render(
      <ScannerFixture
        onScanAgain={onScanAgain}
        state={{ issue: 'network', status: 'failed' }}
      />,
    );

    expect(
      view.getByText(/server could not be reached/),
    ).toBeOnTheScreen();
    await fireEvent.press(
      view.getByRole('button', { name: 'Scan again' }),
    );
    expect(onScanAgain).toHaveBeenCalledTimes(1);
    await view.unmount();
  });

  test('explains camera use before requesting permission', async () => {
    mockCameraPermission = { canAskAgain: true, granted: false };
    const view = await render(
      <ScannerFixture state={{ status: 'idle' }} />,
    );

    expect(
      view.getByText(/camera is used only to read a connection QR code/i),
    ).toBeOnTheScreen();
    await fireEvent.press(
      view.getByRole('button', { name: 'Allow camera access' }),
    );
    expect(mockRequestCameraPermission).toHaveBeenCalledTimes(1);
    await view.unmount();
  });

  test('offers a recoverable settings path after permission denial', async () => {
    mockCameraPermission = { canAskAgain: false, granted: false };
    const onOpenSettings = jest.fn<Promise<void>, []>().mockResolvedValue();
    const view = await render(
      <ScannerFixture
        onOpenSettings={onOpenSettings}
        state={{ status: 'idle' }}
      />,
    );

    expect(view.getByText('Camera access is off')).toBeOnTheScreen();
    await fireEvent.press(
      view.getByRole('button', { name: 'Open settings' }),
    );
    expect(onOpenSettings).toHaveBeenCalledTimes(1);
    await view.unmount();
  });
});
