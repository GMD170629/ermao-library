import {
  fireEvent,
  render,
} from '@testing-library/react-native';

import { AppButton } from './app-button';
import { AppThemeProvider } from './theme-provider';

describe('AppButton', () => {
  test('exposes its label and emits the user intention', async () => {
    const onPress = jest.fn();
    const rendered = await render(
      <AppThemeProvider colorScheme="light">
        <AppButton label="Connect server" onPress={onPress} />
      </AppThemeProvider>,
    );

    await fireEvent.press(
      rendered.getByRole('button', { name: 'Connect server' }),
    );

    expect(onPress).toHaveBeenCalledTimes(1);
  });

  test('does not emit presses while an operation is loading', async () => {
    const onPress = jest.fn();
    const rendered = await render(
      <AppThemeProvider colorScheme="dark">
        <AppButton
          label="Checking server"
          loading
          onPress={onPress}
        />
      </AppThemeProvider>,
    );

    const button = rendered.getByRole('button', {
      name: 'Checking server',
    });
    expect(button).toBeDisabled();
    await fireEvent.press(button);
    expect(onPress).not.toHaveBeenCalled();
  });

  test('uses the action palette for the primary button in both appearances', async () => {
    const light = await render(
      <AppThemeProvider colorScheme="light">
        <AppButton label="Continue" onPress={jest.fn()} />
      </AppThemeProvider>,
    );
    const dark = await render(
      <AppThemeProvider colorScheme="dark">
        <AppButton label="Continue" onPress={jest.fn()} />
      </AppThemeProvider>,
    );

    expect(light.getByRole('button', { name: 'Continue' })).toHaveStyle({
      backgroundColor: '#A23A22',
      borderColor: '#A23A22',
    });
    expect(dark.getByRole('button', { name: 'Continue' })).toHaveStyle({
      backgroundColor: '#B9432E',
      borderColor: '#B9432E',
    });
    expect(light.getByText('Continue')).toHaveStyle({ color: '#FFF9F5' });
    expect(dark.getByText('Continue')).toHaveStyle({ color: '#FFF9F5' });
  });
});
