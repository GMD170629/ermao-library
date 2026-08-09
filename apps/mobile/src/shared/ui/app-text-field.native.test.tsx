import { fireEvent, render } from '@testing-library/react-native';
import { Pressable, Text } from 'react-native';

import { AppTextField } from './app-text-field';
import { AppThemeProvider } from './theme-provider';

describe('AppTextField', () => {
  test('keeps a persistent label and emits edited values', async () => {
    const onChangeText = jest.fn();
    const rendered = await render(
      <AppThemeProvider colorScheme="light">
        <AppTextField
          hint="Use the address from your browser"
          label="Library address"
          maxLength={2048}
          onChangeText={onChangeText}
          placeholder="https://books.example.com"
          value=""
        />
      </AppThemeProvider>,
    );

    const input = rendered.getByLabelText('Library address');
    expect(rendered.getByText('Library address')).toBeOnTheScreen();
    expect(rendered.getByText('Use the address from your browser')).toBeOnTheScreen();
    expect(input).toHaveProp('maxLength', 2048);

    fireEvent.changeText(input, 'https://books.example.com');
    expect(onChangeText).toHaveBeenCalledWith('https://books.example.com');
  });

  test('announces a nearby error and exposes secure and disabled states', async () => {
    const rendered = await render(
      <AppThemeProvider colorScheme="dark">
        <AppTextField
          disabled
          error="Enter your password"
          label="Password"
          onChangeText={jest.fn()}
          secureTextEntry
          value=""
        />
      </AppThemeProvider>,
    );

    const input = rendered.getByLabelText('Password');
    expect(input).toBeDisabled();
    expect(input).toHaveProp('secureTextEntry', true);
    expect(input).toHaveProp('accessibilityState', { disabled: true });
    expect(rendered.getByText('Enter your password')).toHaveProp(
      'accessibilityLiveRegion',
      'assertive',
    );
  });

  test('renders a label action without replacing the persistent label', async () => {
    const onLabelAction = jest.fn();
    const rendered = await render(
      <AppThemeProvider colorScheme="light">
        <AppTextField
          label="Password"
          labelAction={
            <Pressable
              accessibilityRole="button"
              onPress={onLabelAction}
            >
              <Text>Forgot password?</Text>
            </Pressable>
          }
          onChangeText={jest.fn()}
          testID="password-field"
          value=""
        />
      </AppThemeProvider>,
    );

    expect(rendered.getByText('Password')).toBeOnTheScreen();
    await fireEvent.press(
      rendered.getByRole('button', { name: 'Forgot password?' }),
    );
    expect(onLabelAction).toHaveBeenCalledTimes(1);
  });

  test('draws a three-point focus ring without changing the field border width', async () => {
    const rendered = await render(
      <AppThemeProvider colorScheme="dark">
        <AppTextField
          label="Email"
          onChangeText={jest.fn()}
          testID="email-field"
          value=""
        />
      </AppThemeProvider>,
    );
    const input = rendered.getByLabelText('Email');
    const container = rendered.getByTestId('email-field-container');

    expect(container).toHaveStyle({ borderWidth: 1 });
    expect(
      rendered.queryByTestId('email-field-focus-ring', {
        includeHiddenElements: true,
      }),
    ).toBeNull();

    await fireEvent(input, 'focus');

    expect(container).toHaveStyle({ borderWidth: 1 });
    expect(
      rendered.getByTestId('email-field-focus-ring', {
        includeHiddenElements: true,
      }),
    ).toHaveStyle({ borderColor: '#D96A50', borderWidth: 3 });

    await fireEvent(input, 'blur');
    expect(
      rendered.queryByTestId('email-field-focus-ring', {
        includeHiddenElements: true,
      }),
    ).toBeNull();
  });
});
