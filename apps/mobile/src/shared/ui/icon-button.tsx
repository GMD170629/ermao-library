import type { ReactNode } from 'react';
import {
  Pressable,
  StyleSheet,
  type AccessibilityState,
} from 'react-native';

import { useAppTheme } from './theme-provider';

export type IconButtonProps = Readonly<{
  accessibilityHint?: string;
  accessibilityLabel: string;
  accessibilityState?: AccessibilityState;
  disabled?: boolean;
  icon: ReactNode;
  onPress: () => void;
  shape?: 'circle' | 'rounded';
  testID?: string;
  tone?: 'danger' | 'neutral' | 'tint';
}>;

export function IconButton({
  accessibilityHint,
  accessibilityLabel,
  accessibilityState,
  disabled = false,
  icon,
  onPress,
  shape = 'rounded',
  testID,
  tone = 'neutral',
}: IconButtonProps): ReactNode {
  const theme = useAppTheme();
  const inactive = disabled || accessibilityState?.disabled === true;
  const background =
    tone === 'tint'
      ? theme.colors.tintMuted
      : tone === 'danger'
        ? theme.colors.dangerMuted
        : theme.colors.cardStrong;

  return (
    <Pressable
      accessibilityHint={accessibilityHint}
      accessibilityLabel={accessibilityLabel}
      accessibilityRole="button"
      accessibilityState={{ ...accessibilityState, disabled: inactive }}
      disabled={inactive}
      hitSlop={6}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        {
          backgroundColor: background,
          borderColor: theme.colors.border,
          borderRadius:
            shape === 'circle'
              ? theme.control.regularHeight / 2
              : theme.radius.control,
          height: theme.control.regularHeight,
          width: theme.control.regularHeight,
        },
        pressed && styles.pressed,
        inactive && styles.disabled,
      ]}
      testID={testID}
    >
      {icon}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    alignItems: 'center',
    borderWidth: StyleSheet.hairlineWidth,
    justifyContent: 'center',
  },
  disabled: {
    opacity: 0.45,
  },
  pressed: {
    opacity: 0.68,
  },
});
