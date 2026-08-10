import { MenuView, type MenuAction } from '@expo/ui/community/menu';
import type { ReactNode } from 'react';
import { View } from 'react-native';

import { AppIcon, type AppIconName } from './app-icon';
import { useAppTheme } from './theme-provider';

export type SystemActionMenuItem<ActionId extends string> = Readonly<{
  destructive?: boolean;
  disabled?: boolean;
  id: ActionId;
  selected?: boolean;
  title: string;
}>;

export type SystemActionMenuProps<ActionId extends string> = Readonly<{
  accessibilityLabel: string;
  actions: readonly SystemActionMenuItem<ActionId>[];
  iconName?: AppIconName;
  onAction(actionId: ActionId): void;
  testID?: string;
  title?: string;
}>;

export function SystemActionMenu<ActionId extends string>({
  accessibilityLabel,
  actions,
  iconName = 'more',
  onAction,
  testID,
  title,
}: SystemActionMenuProps<ActionId>): ReactNode {
  const theme = useAppTheme();
  const nativeActions: MenuAction[] = actions.map((action) => ({
    id: action.id,
    title: action.title,
    ...(action.selected ? { state: 'on' as const } : {}),
    ...(action.destructive || action.disabled
      ? {
          attributes: {
            ...(action.destructive ? { destructive: true } : {}),
            ...(action.disabled ? { disabled: true } : {}),
          },
        }
      : {}),
  }));
  return (
    <MenuView
      actions={nativeActions}
      onPressAction={(event) => {
        const selectedAction = actions.find(
          (action) => action.id === event.nativeEvent.event,
        );
        if (selectedAction !== undefined) onAction(selectedAction.id);
      }}
      shouldOpenOnLongPress={false}
      style={{ minHeight: 44, minWidth: 44 }}
      {...(testID === undefined ? {} : { testID })}
      {...(title === undefined ? {} : { title })}
    >
      <View
        accessibilityLabel={accessibilityLabel}
        accessibilityRole="button"
        style={{
          alignItems: 'center',
          height: 44,
          justifyContent: 'center',
          width: 44,
        }}
      >
        <AppIcon
          color={theme.colors.tint}
          decorative
          name={iconName}
          size={theme.control.iconMedium}
        />
      </View>
    </MenuView>
  );
}
