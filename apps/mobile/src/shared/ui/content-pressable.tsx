import type { ReactNode } from 'react';
import {
  Pressable,
  type AccessibilityRole,
  type AccessibilityState,
  type StyleProp,
  type ViewStyle,
} from 'react-native';

export type ContentPressableProps = Readonly<{
  accessibilityHint?: string;
  accessibilityLabel: string;
  accessibilityRole?: AccessibilityRole;
  accessibilityState?: AccessibilityState;
  children: ReactNode;
  disabled?: boolean;
  onLongPress?: () => void;
  onPress: () => void;
  style?: StyleProp<ViewStyle>;
  testID?: string;
}>;

export function ContentPressable({
  accessibilityHint,
  accessibilityLabel,
  accessibilityRole = 'button',
  accessibilityState,
  children,
  disabled = false,
  onLongPress,
  onPress,
  style,
  testID,
}: ContentPressableProps): ReactNode {
  return (
    <Pressable
      accessibilityHint={accessibilityHint}
      accessibilityLabel={accessibilityLabel}
      accessibilityRole={accessibilityRole}
      accessibilityState={{ ...accessibilityState, disabled }}
      disabled={disabled}
      hitSlop={4}
      onLongPress={onLongPress}
      onPress={onPress}
      style={({ pressed }) => [style, pressed && { opacity: 0.72 }]}
      testID={testID}
    >
      {children}
    </Pressable>
  );
}
