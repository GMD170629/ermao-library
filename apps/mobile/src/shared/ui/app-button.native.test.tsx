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

  test('maps business variants to native button variants', async () => {
    const rendered = await render(
      <AppThemeProvider colorScheme="light">
        <AppButton label="Continue" onPress={jest.fn()} />
        <AppButton label="More" onPress={jest.fn()} variant="secondary" />
        <AppButton label="Skip" onPress={jest.fn()} variant="ghost" />
        <AppButton label="Delete" onPress={jest.fn()} variant="destructive" />
      </AppThemeProvider>,
    );

    expect(rendered.getAllByTestId('native-button-filled')).toHaveLength(2);
    expect(rendered.getByTestId('native-button-outlined')).toBeOnTheScreen();
    expect(rendered.getByTestId('native-button-text')).toBeOnTheScreen();
  });

  test('passes only numeric dimensions to a full-width native button', async () => {
    const rendered = await render(
      <AppThemeProvider colorScheme="light">
        <AppButton
          fullWidth
          label="Continue"
          onPress={jest.fn()}
          testID="full-width-button"
        />
      </AppThemeProvider>,
    );

    const button = rendered.getByTestId('full-width-button');
    expect(button.props.style).toEqual({ height: expect.any(Number) });
    expect(JSON.stringify(button.props.style)).not.toContain('100%');
  });
});
