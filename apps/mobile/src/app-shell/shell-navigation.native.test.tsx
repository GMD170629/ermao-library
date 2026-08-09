import { fireEvent, render } from '@testing-library/react-native';

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
      <AppThemeProvider colorScheme="light">
        <I18nProvider>
          <ShellNavigation expanded={false} />
        </I18nProvider>
      </AppThemeProvider>,
    );

    const home = view.getByRole('tab', { name: 'Home' });
    const library = view.getByRole('tab', { name: 'Bookshelf' });
    const me = view.getByRole('tab', { name: 'Me' });

    expect(home.props.accessibilityState).toEqual({ selected: false });
    expect(library.props.accessibilityState).toEqual({ selected: true });
    expect(me.props.accessibilityState).toEqual({ selected: false });

    await fireEvent.press(library);
    expect(mockReplace).not.toHaveBeenCalled();

    await fireEvent.press(me);
    expect(mockReplace).toHaveBeenCalledWith('/me');
    await view.unmount();
  });
});
