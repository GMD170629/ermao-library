import type { ReactNode } from 'react';
import { ActivityIndicator, View } from 'react-native';

import { AppText } from './app-text';
import { useAppTheme } from './theme-provider';

export type LoadingStateProps = Readonly<{
  label: string;
}>;

export function LoadingState({ label }: LoadingStateProps): ReactNode {
  const theme = useAppTheme();
  return (
    <View
      accessibilityLabel={label}
      accessibilityLiveRegion="polite"
      accessibilityRole="progressbar"
      style={{
        alignItems: 'center',
        flexDirection: 'row',
        gap: theme.spacing.sm,
        justifyContent: 'center',
        minHeight: theme.control.regularHeight * 2,
        padding: theme.spacing.lg,
      }}
    >
      <ActivityIndicator
        accessibilityElementsHidden
        color={theme.colors.tint}
        importantForAccessibility="no-hide-descendants"
        size="small"
      />
      <AppText muted>{label}</AppText>
    </View>
  );
}
