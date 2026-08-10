import { fireEvent, render } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { I18nProvider } from '../shared/i18n/public';
import { AppThemeProvider } from '../shared/ui/public';
import { ShellNavigation } from './shell-navigation';

const mockReplace = jest.fn();

jest.mock('expo-localization', () => ({
  useLocales: () => [{ languageTag: 'en-US' }],
}));

jest.mock('expo-router', () => ({
  usePathname: () => '/library',
  useRouter: () => ({ replace: mockReplace }),
}));

describe('ShellNavigation', () => {
  beforeEach(() => {
    mockReplace.mockClear();
  });

  test('renders labeled semantic tabs and navigates to another destination', async () => {
    const view = await render(
      <SafeAreaProvider
        initialMetrics={{
          frame: { height: 852, width: 393, x: 0, y: 0 },
          insets: { bottom: 34, left: 0, right: 0, top: 59 },
        }}
      >
        <AppThemeProvider colorScheme="light">
          <I18nProvider>
            <ShellNavigation expanded={false} />
          </I18nProvider>
        </AppThemeProvider>
      </SafeAreaProvider>,
    );

    const home = view.getByRole('tab', { name: 'Home' });
    const library = view.getByRole('tab', { name: 'Bookshelf' });
    const me = view.getByRole('tab', { name: 'Me' });
    expect(view.getByLabelText('Primary navigation')).toHaveStyle({
      paddingBottom: 22,
      paddingTop: 20,
    });

    expect(home.props.accessibilityState).toEqual({ selected: false });
    expect(library.props.accessibilityState).toEqual({ selected: true });
    expect(me.props.accessibilityState).toEqual({ selected: false });
    expect(library).toHaveStyle({ backgroundColor: '#FCE6DF' });

    await fireEvent.press(library);
    expect(mockReplace).not.toHaveBeenCalled();

    await fireEvent.press(me);
    expect(mockReplace).toHaveBeenCalledWith('/me');
    await view.unmount();
  });
});
