import type { ReactNode } from 'react';
import {
  Text,
  type StyleProp,
  type TextProps,
  type TextStyle,
} from 'react-native';

import type { TextVariant } from './theme';
import { useAppTheme } from './theme-provider';

export type { TextVariant } from './theme';

export type AppTextProps = Readonly<{
  children: ReactNode;
  muted?: boolean;
  style?: StyleProp<TextStyle>;
  variant?: TextVariant;
}> & Omit<TextProps, 'children' | 'style'>;

export function AppText({
  children,
  muted = false,
  style,
  variant = 'body',
  ...textProps
}: AppTextProps): ReactNode {
  const theme = useAppTheme();

  return (
    <Text
      allowFontScaling
      {...textProps}
      style={[
        theme.type[variant],
        { color: muted ? theme.colors.textMuted : theme.colors.text },
        style,
      ]}
    >
      {children}
    </Text>
  );
}
