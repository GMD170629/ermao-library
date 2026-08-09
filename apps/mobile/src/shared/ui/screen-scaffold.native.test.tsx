import { fireEvent, render } from '@testing-library/react-native';
import { Text } from 'react-native';

import { ScreenScaffold } from './screen-scaffold';

test('exposes an accessible native pull-to-refresh action when requested', async () => {
  const onRefresh = jest.fn();
  const view = await render(
    <ScreenScaffold onRefresh={onRefresh} refreshing testID="screen">
      <Text>Library</Text>
    </ScreenScaffold>,
  );

  if (view.root === null) throw new Error('Expected a rendered root');
  const controls = view.root.queryAll(
    (instance: Readonly<{ type: string }>) =>
      instance.type === 'RCTRefreshControl',
  );
  expect(controls).toHaveLength(1);
  const control = controls[0];
  if (control === undefined) throw new Error('Expected a refresh control');
  await fireEvent(control, 'refresh');

  expect(onRefresh).toHaveBeenCalledTimes(1);
});
