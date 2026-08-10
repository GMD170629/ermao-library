import { Button, Host, Icon, Row, Text } from '@expo/ui';
import { useState, type ReactNode } from 'react';
import {
  StyleSheet,
  View,
  type LayoutChangeEvent,
  type StyleProp,
  type ViewStyle,
} from 'react-native';

import {
  appNativeIconName,
  type AppIconName,
} from './app-icon';
import { useAppTheme } from './theme-provider';

export type AppButtonVariant =
  | 'destructive'
  | 'ghost'
  | 'primary'
  | 'secondary';

export type AppButtonProps = Readonly<{
  accessibilityHint?: string;
  containerStyle?: StyleProp<ViewStyle>;
  disabled?: boolean;
  fullWidth?: boolean;
  iconName?: AppIconName;
  label: string;
  loading?: boolean;
  onPress: () => void;
  testID?: string;
  variant?: AppButtonVariant;
}>;

export function AppButton({
  accessibilityHint,
  containerStyle,
  disabled = false,
  fullWidth = false,
  iconName,
  label,
  loading = false,
  onPress,
  testID,
  variant = 'primary',
}: AppButtonProps): ReactNode {
  const theme = useAppTheme();
  const [measuredWidth, setMeasuredWidth] = useState<number>();
  const inactive = disabled || loading;
  const nativeVariant =
    variant === 'primary' || variant === 'destructive'
      ? 'filled'
      : variant === 'secondary'
        ? 'outlined'
        : 'text';
  const seedColor =
    variant === 'destructive'
      ? theme.colors.danger
      : variant === 'primary'
        ? theme.colors.actionFill
        : theme.colors.tint;

  return (
    <View
      accessibilityHint={accessibilityHint}
      accessibilityState={{ busy: loading, disabled: inactive }}
      onLayout={
        fullWidth
          ? (event: LayoutChangeEvent) => {
              setMeasuredWidth(Math.round(event.nativeEvent.layout.width));
            }
          : undefined
      }
      style={[
        styles.container,
        fullWidth && styles.fullWidth,
        containerStyle,
      ]}
    >
      <Host
        colorScheme={theme.isDark ? 'dark' : 'light'}
        matchContents={!fullWidth}
        seedColor={seedColor}
        style={[styles.host, fullWidth && styles.fullWidth]}
      >
        <Button
          disabled={inactive}
          onPress={onPress}
          style={{
            height: theme.control.regularHeight,
            // Expo UI forwards these dimensions to native records, which only
            // accept numeric dp values. Percentage layout stays on the RN host.
            ...(fullWidth && measuredWidth !== undefined
              ? { width: measuredWidth }
              : {}),
          }}
          {...(testID === undefined ? {} : { testID })}
          variant={nativeVariant}
        >
          {iconName === undefined ? (
            <Text>{label}</Text>
          ) : (
            <Row alignment="center" spacing={theme.spacing.xs}>
              <Icon
                name={appNativeIconName(iconName)}
                size={theme.control.iconMedium}
              />
              <Text>{label}</Text>
            </Row>
          )}
        </Button>
      </Host>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    minHeight: 48,
  },
  fullWidth: {
    alignSelf: 'stretch',
    width: '100%',
  },
  host: {
    minHeight: 48,
  },
});
