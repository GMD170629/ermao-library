import { fireEvent, render, waitFor } from '@testing-library/react-native';
import { Pressable, Text } from 'react-native';

import type {
  ThemePreference,
  ThemePreferenceStore,
} from '../preferences/public';
import {
  AppThemeProvider,
  useAppThemeController,
} from './theme-provider';

class FakeThemePreferenceStore implements ThemePreferenceStore {
  readonly saved: ThemePreference[] = [];

  constructor(private readonly loaded: ThemePreference) {}

  load(): ThemePreference {
    return this.loaded;
  }

  save(preference: ThemePreference): Promise<void> {
    this.saved.push(preference);
    return Promise.resolve();
  }
}

function ThemeProbe() {
  const controller = useAppThemeController();
  return (
    <Pressable
      accessibilityLabel="toggle-theme"
      accessibilityRole="button"
      onPress={controller.toggleColorScheme}
    >
      <Text>{`${controller.colorScheme}:${controller.preference}`}</Text>
    </Pressable>
  );
}

describe('AppThemeProvider', () => {
  test('loads and persists an explicit theme selection', async () => {
    const store = new FakeThemePreferenceStore('dark');
    const view = await render(
      <AppThemeProvider preferenceStore={store}>
        <ThemeProbe />
      </AppThemeProvider>,
    );

    await waitFor(() => {
      expect(view.getByText('dark:dark')).toBeTruthy();
    });
    await fireEvent.press(
      view.getByRole('button', { name: 'toggle-theme' }),
    );
    expect(view.getByText('light:light')).toBeTruthy();
    expect(store.saved).toEqual(['light']);
    await view.unmount();
  });
});
