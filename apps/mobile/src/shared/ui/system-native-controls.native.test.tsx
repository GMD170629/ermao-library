import * as Haptics from 'expo-haptics';
import { fireEvent, render } from '@testing-library/react-native';

import { AppThemeProvider } from './theme-provider';
import { SystemActionMenu } from './system-action-menu';
import { SystemListItem } from './system-list-item';
import { SystemSegmentedControl } from './system-segmented-control';

describe('native control adapters', () => {
  beforeEach(() => {
    jest.mocked(Haptics.selectionAsync).mockClear();
  });

  test('reports segmented selection and uses system selection feedback', async () => {
    const onChange = jest.fn();
    const view = await render(
      <AppThemeProvider colorScheme="light">
        <SystemSegmentedControl
          onChange={onChange}
          options={[
            { label: 'Grid', value: 'grid' },
            { label: 'List', value: 'list' },
          ]}
          value="grid"
        />
      </AppThemeProvider>,
    );

    expect(view.getByRole('tab', { name: 'Grid' })).toBeSelected();
    await fireEvent.press(view.getByRole('tab', { name: 'List' }));
    expect(onChange).toHaveBeenCalledWith('list');
    expect(Haptics.selectionAsync).toHaveBeenCalledTimes(1);
  });

  test('preserves selected, disabled, and destructive menu actions', async () => {
    const onAction = jest.fn();
    const view = await render(
      <AppThemeProvider colorScheme="dark">
        <SystemActionMenu
          accessibilityLabel="More actions"
          actions={[
            { id: 'current', selected: true, title: 'Current' },
            { disabled: true, id: 'locked', title: 'Locked' },
            { destructive: true, id: 'delete', title: 'Delete' },
          ]}
          onAction={onAction}
        />
      </AppThemeProvider>,
    );

    expect(view.getByRole('menuitem', { name: 'Current' })).toBeSelected();
    expect(view.getByRole('menuitem', { name: 'Locked' })).toBeDisabled();
    await fireEvent.press(view.getByRole('menuitem', { name: 'Delete' }));
    expect(onAction).toHaveBeenCalledWith('delete');
  });

  test('renders list labels, supporting text, selection, and row actions', async () => {
    const onPress = jest.fn();
    const view = await render(
      <AppThemeProvider colorScheme="light">
        <SystemListItem
          iconName="server"
          label="Current server"
          onPress={onPress}
          selected
          supportingText="https://books.example.com"
        />
      </AppThemeProvider>,
    );

    expect(view.getByText('https://books.example.com')).toBeOnTheScreen();
    await fireEvent.press(
      view.getByRole('button', { name: 'Current server' }),
    );
    expect(onPress).toHaveBeenCalledTimes(1);
  });
});
