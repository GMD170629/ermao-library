import { fireEvent, render } from '@testing-library/react-native';
import { Text } from 'react-native';

import { IconButton } from './icon-button';
import { AppThemeProvider } from './theme-provider';

describe('IconButton', () => {
  test('supports the circular neutral appearance used by page headers', async () => {
    const rendered = await render(
      <AppThemeProvider colorScheme="light">
        <IconButton
          accessibilityLabel="Change appearance"
          icon={<Text>icon</Text>}
          onPress={jest.fn()}
          shape="circle"
        />
      </AppThemeProvider>,
    );

    expect(
      rendered.getByRole('button', { name: 'Change appearance' }),
    ).toHaveStyle({
      backgroundColor: '#FFFFFF',
      borderColor: '#E4D9D2',
      borderRadius: 24,
      height: 48,
      width: 48,
    });
  });

  test('merges selected and busy accessibility state with its disabled state', async () => {
    const onPress = jest.fn();
    const rendered = await render(
      <AppThemeProvider colorScheme="light">
        <IconButton
          accessibilityLabel="Show password"
          accessibilityState={{ busy: true, selected: true }}
          icon={<Text>icon</Text>}
          onPress={onPress}
        />
      </AppThemeProvider>,
    );

    const button = rendered.getByRole('button', { name: 'Show password' });
    expect(button).toHaveProp('accessibilityState', {
      busy: true,
      disabled: false,
      selected: true,
    });

    await fireEvent.press(button);
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  test('keeps an accessibility-state disabled button non-interactive', async () => {
    const onPress = jest.fn();
    const rendered = await render(
      <AppThemeProvider colorScheme="dark">
        <IconButton
          accessibilityLabel="Refresh"
          accessibilityState={{ disabled: true, selected: false }}
          icon={<Text>icon</Text>}
          onPress={onPress}
        />
      </AppThemeProvider>,
    );

    const button = rendered.getByRole('button', { name: 'Refresh' });
    expect(button).toBeDisabled();
    expect(button).toHaveProp('accessibilityState', {
      disabled: true,
      selected: false,
    });
    await fireEvent.press(button);
    expect(onPress).not.toHaveBeenCalled();
  });
});
