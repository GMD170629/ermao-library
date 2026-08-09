import type { ReactNode } from 'react';
import {
  StyleSheet,
  View,
  type StyleProp,
  type ViewProps,
  type ViewStyle,
} from 'react-native';

import { useAppTheme } from './theme-provider';

export type SurfaceCardProps = Readonly<{
  children: ReactNode;
  padding?: 'compact' | 'none' | 'regular';
  style?: StyleProp<ViewStyle>;
}> & Omit<ViewProps, 'children' | 'style'>;

export function SurfaceCard({
  children,
  padding = 'regular',
  style,
  ...viewProps
}: SurfaceCardProps): ReactNode {
  const theme = useAppTheme();

  return (
    <View
      {...viewProps}
      style={[
        styles.card,
        theme.elevation.card,
        padding === 'compact' && { padding: theme.spacing.md },
        padding === 'regular' && { padding: theme.spacing.xl },
        {
          backgroundColor: theme.colors.card,
          borderColor: theme.colors.border,
          borderRadius: theme.radius.spacious,
          gap: theme.spacing.md,
        },
        style,
      ]}
    >
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: StyleSheet.hairlineWidth,
  },
});
