import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  View,
  type StyleProp,
  type TextStyle,
  type ViewStyle,
} from 'react-native';

import { AppText } from './app-text';
import { useAppTheme } from './theme-provider';

export type AppButtonVariant =
  | 'destructive'
  | 'ghost'
  | 'primary'
  | 'secondary';

export type AppButtonProps = Readonly<{
  accessibilityHint?: string;
  disabled?: boolean;
  fullWidth?: boolean;
  label: string;
  leadingIcon?: ReactNode;
  loading?: boolean;
  onPress: () => void;
  style?: StyleProp<ViewStyle>;
  testID?: string;
  variant?: AppButtonVariant;
}>;

export function AppButton({
  accessibilityHint,
  disabled = false,
  fullWidth = false,
  label,
  leadingIcon,
  loading = false,
  onPress,
  style,
  testID,
  variant = 'primary',
}: AppButtonProps): ReactNode {
  const theme = useAppTheme();
  const inactive = disabled || loading;
  const appearance = buttonAppearance(theme, variant);

  return (
    <Pressable
      accessibilityHint={accessibilityHint}
      accessibilityLabel={label}
      accessibilityRole="button"
      accessibilityState={{ busy: loading, disabled: inactive }}
      disabled={inactive}
      hitSlop={4}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        fullWidth && styles.fullWidth,
        {
          backgroundColor: appearance.background,
          borderColor: appearance.border,
          borderRadius: theme.radius.control,
          minHeight: theme.control.regularHeight,
          paddingHorizontal: theme.spacing.lg,
          paddingVertical: theme.spacing.sm,
        },
        pressed && !inactive && {
          backgroundColor: appearance.pressed,
        },
        inactive && styles.inactive,
        style,
      ]}
      testID={testID}
    >
      <View style={[styles.content, { gap: theme.spacing.xs }]}>
        {loading ? (
          <ActivityIndicator
            accessibilityElementsHidden
            color={appearance.text}
            importantForAccessibility="no-hide-descendants"
            size="small"
          />
        ) : (
          leadingIcon
        )}
        <AppText
          style={[
            styles.label,
            { color: appearance.text } satisfies TextStyle,
          ]}
          variant="label"
        >
          {label}
        </AppText>
      </View>
    </Pressable>
  );
}

function buttonAppearance(
  theme: ReturnType<typeof useAppTheme>,
  variant: AppButtonVariant,
): Readonly<{
  background: string;
  border: string;
  pressed: string;
  text: string;
}> {
  if (variant === 'destructive') {
    return {
      background: theme.colors.dangerMuted,
      border: theme.colors.dangerMuted,
      pressed: theme.colors.borderStrong,
      text: theme.colors.danger,
    };
  }
  if (variant === 'secondary') {
    return {
      background: theme.colors.cardStrong,
      border: theme.colors.borderStrong,
      pressed: theme.colors.tintMuted,
      text: theme.colors.text,
    };
  }
  if (variant === 'ghost') {
    return {
      background: 'transparent',
      border: 'transparent',
      pressed: theme.colors.tintMuted,
      text: theme.colors.tint,
    };
  }
  return {
    background: theme.colors.actionFill,
    border: theme.colors.actionFill,
    pressed: theme.colors.actionPressed,
    text: theme.colors.onAction,
  };
}

const styles = StyleSheet.create({
  button: {
    alignItems: 'center',
    borderWidth: 1,
    justifyContent: 'center',
  },
  content: {
    alignItems: 'center',
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'center',
  },
  fullWidth: {
    alignSelf: 'stretch',
  },
  inactive: {
    opacity: 0.48,
  },
  label: {
    textAlign: 'center',
  },
});
