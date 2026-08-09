import { render } from '@testing-library/react-native';

import { AppIcon } from './app-icon';
import { AppThemeProvider } from './theme-provider';

describe('AppIcon', () => {
  test('keeps decorative symbols out of the accessibility tree', async () => {
    const rendered = await render(
      <AppThemeProvider colorScheme="light">
        <AppIcon name="library" testID="library-icon" />
      </AppThemeProvider>,
    );

    expect(
      rendered.getByTestId('library-icon', { includeHiddenElements: true }),
    ).toHaveProp(
      'importantForAccessibility',
      'no-hide-descendants',
    );
  });

  test('supports a labelled standalone semantic symbol', async () => {
    const rendered = await render(
      <AppThemeProvider colorScheme="dark">
        <AppIcon
          accessibilityLabel="Connection warning"
          decorative={false}
          name="warning"
          testID="warning-icon"
        />
      </AppThemeProvider>,
    );

    expect(rendered.getByLabelText('Connection warning')).toBeOnTheScreen();
  });

  test('renders the library navigation and view-control symbols', async () => {
    const rendered = await render(
      <AppThemeProvider colorScheme="light">
        <AppIcon name="home" testID="home-icon" />
        <AppIcon name="grid" testID="grid-icon" />
        <AppIcon name="list" testID="list-icon" />
        <AppIcon name="search" testID="search-icon" />
        <AppIcon name="sun" testID="sun-icon" />
      </AppThemeProvider>,
    );

    expect(
      rendered.getByTestId('home-icon', { includeHiddenElements: true }),
    ).toBeOnTheScreen();
    expect(
      rendered.getByTestId('grid-icon', { includeHiddenElements: true }),
    ).toBeOnTheScreen();
    expect(
      rendered.getByTestId('list-icon', { includeHiddenElements: true }),
    ).toBeOnTheScreen();
    expect(
      rendered.getByTestId('search-icon', { includeHiddenElements: true }),
    ).toBeOnTheScreen();
    expect(
      rendered.getByTestId('sun-icon', { includeHiddenElements: true }),
    ).toBeOnTheScreen();
  });
});
