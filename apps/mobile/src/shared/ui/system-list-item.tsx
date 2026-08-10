import { Host, Icon, ListItem, RNHostView } from '@expo/ui';
import type { ReactElement, ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

import {
  appNativeIconName,
  type AppIconName,
} from './app-icon';
import { useAppTheme } from './theme-provider';

export type SystemListItemProps = Readonly<{
  disabled?: boolean;
  iconName?: AppIconName;
  label: string;
  leading?: ReactElement;
  onPress?: () => void;
  selected?: boolean;
  supportingText?: string;
  testID?: string;
}>;

export function SystemListItem({
  disabled = false,
  iconName,
  label,
  leading,
  onPress,
  selected = false,
  supportingText,
  testID,
}: SystemListItemProps): ReactNode {
  const theme = useAppTheme();
  const leadingContent =
    leading === undefined ? (
      iconName === undefined ? undefined : (
        <Icon
          name={appNativeIconName(iconName)}
          size={theme.control.iconMedium}
        />
      )
    ) : (
      <RNHostView matchContents>{leading}</RNHostView>
    );
  const trailing = selected ? (
    <Icon
      name={appNativeIconName('check')}
      size={theme.control.iconMedium}
    />
  ) : onPress === undefined ? undefined : (
    <Icon
      name={appNativeIconName('chevron-right')}
      size={theme.control.iconSmall}
    />
  );
  return (
    <View
      accessibilityState={{ disabled, selected }}
      style={[styles.row, disabled && styles.disabled]}
    >
      <Host
        colorScheme={theme.isDark ? 'dark' : 'light'}
        matchContents={{ horizontal: false, vertical: true }}
        seedColor={theme.colors.tint}
        style={styles.host}
      >
        <ListItem
          {...(leadingContent === undefined ? {} : { leading: leadingContent })}
          {...(trailing === undefined ? {} : { trailing })}
          {...(supportingText === undefined ? {} : { supportingText })}
          {...(disabled || onPress === undefined ? {} : { onPress })}
          {...(testID === undefined ? {} : { testID })}
        >
          {label}
        </ListItem>
      </Host>
    </View>
  );
}

const styles = StyleSheet.create({
  disabled: { opacity: 0.48 },
  host: { width: '100%' },
  row: { minHeight: 48, width: '100%' },
});
