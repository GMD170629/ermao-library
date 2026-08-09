import { fireEvent, render } from '@testing-library/react-native';
import { Alert, type AlertButton } from 'react-native';

import MeRoute from '../../src/app/(main)/me';
import { I18nProvider } from '../../src/shared/i18n/public';
import { AppThemeProvider } from '../../src/shared/ui/public';

const mockLogout = jest.fn(() => Promise.resolve());
const mockLogoutForConnectionManagement = jest.fn(() => Promise.resolve());

jest.mock('expo-localization', () => ({
  useLocales: () => [{ languageTag: 'en-US' }],
}));

jest.mock('../../src/features/app-flow/public', () => ({
  useAppFlow: () => ({
    state: {
      phase: 'authenticated',
      profile: {
        id: 'profile-1',
        baseUrl: { value: 'https://books.example.com' },
      },
      session: {
        user: {
          email: 'reader@example.com',
          name: 'Reader',
        },
      },
    },
    logout: mockLogout,
    logoutForConnectionManagement: mockLogoutForConnectionManagement,
  }),
}));

function confirmButton(buttons: readonly AlertButton[] | undefined): AlertButton {
  const button = buttons?.find((candidate) => candidate.style !== 'cancel');
  if (button === undefined) throw new Error('Expected a confirm button');
  return button;
}

describe('MeRoute', () => {
  beforeEach(() => {
    mockLogout.mockClear();
    mockLogoutForConnectionManagement.mockClear();
  });

  test('shows account and server details and confirms both logout intents', async () => {
    const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
    const view = await render(
      <AppThemeProvider colorScheme="light">
        <I18nProvider>
          <MeRoute />
        </I18nProvider>
      </AppThemeProvider>,
    );

    expect(view.getByText('Reader')).toBeTruthy();
    expect(view.getByText('reader@example.com')).toBeTruthy();
    expect(view.getByText('https://books.example.com')).toBeTruthy();

    await fireEvent.press(
      view.getByRole('button', { name: 'Manage server connections' }),
    );
    expect(mockLogoutForConnectionManagement).not.toHaveBeenCalled();
    confirmButton(alert.mock.calls[0]?.[2]).onPress?.();
    expect(mockLogoutForConnectionManagement).toHaveBeenCalledTimes(1);

    await fireEvent.press(view.getByRole('button', { name: 'Sign out' }));
    expect(mockLogout).not.toHaveBeenCalled();
    confirmButton(alert.mock.calls[1]?.[2]).onPress?.();
    expect(mockLogout).toHaveBeenCalledTimes(1);

    alert.mockRestore();
    await view.unmount();
  });
});
