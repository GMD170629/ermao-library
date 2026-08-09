import { StatusBar } from 'expo-status-bar';
import type { ReactNode } from 'react';
import {
  RefreshControl,
  ScrollView,
  StyleSheet,
  View,
  useWindowDimensions,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import {
  SafeAreaView,
  type Edge,
} from 'react-native-safe-area-context';

import { useAppTheme } from './theme-provider';

const DEFAULT_EDGES: readonly Edge[] = [
  'top',
  'right',
  'bottom',
  'left',
];

export type ScreenScaffoldProps = Readonly<{
  accessibilityLanguage?: string;
  children: ReactNode;
  contentStyle?: StyleProp<ViewStyle>;
  edges?: readonly Edge[];
  onRefresh?: () => void;
  refreshing?: boolean;
  scrollable?: boolean;
  testID?: string;
}>;

export function ScreenScaffold({
  accessibilityLanguage,
  children,
  contentStyle,
  edges = DEFAULT_EDGES,
  onRefresh,
  refreshing = false,
  scrollable = true,
  testID,
}: ScreenScaffoldProps): ReactNode {
  const theme = useAppTheme();
  const { width } = useWindowDimensions();
  const horizontalPadding =
    width >= theme.breakpoint.expandedMinWidth
      ? theme.breakpoint.expandedHorizontalPadding
      : width < 360
        ? theme.breakpoint.compactMinimumHorizontalPadding
        : theme.breakpoint.compactHorizontalPadding;
  const sharedContentStyle: StyleProp<ViewStyle> = [
    styles.content,
    {
      maxWidth: theme.breakpoint.contentMaxWidth,
      paddingHorizontal: horizontalPadding,
    },
    contentStyle,
  ];

  return (
    <SafeAreaView
      {...(accessibilityLanguage === undefined
        ? {}
        : { accessibilityLanguage })}
      edges={edges}
      style={[
        styles.safeArea,
        { backgroundColor: theme.colors.background },
      ]}
      testID={testID}
    >
      <StatusBar style={theme.isDark ? 'light' : 'dark'} />
      {scrollable ? (
        <ScrollView
          automaticallyAdjustKeyboardInsets
          contentContainerStyle={[
            styles.scrollContent,
            {
              paddingBottom: theme.spacing.xxl,
              paddingTop: theme.spacing.sm,
            },
            sharedContentStyle,
          ]}
          keyboardDismissMode="interactive"
          keyboardShouldPersistTaps="handled"
          {...(onRefresh === undefined
            ? {}
            : {
                refreshControl: (
                  <RefreshControl
                    colors={[theme.colors.tint]}
                    onRefresh={onRefresh}
                    progressBackgroundColor={theme.colors.card}
                    refreshing={refreshing}
                    tintColor={theme.colors.tint}
                  />
                ),
              })}
        >
          {children}
        </ScrollView>
      ) : (
        <View
          style={[
            styles.fixedContent,
            {
              paddingBottom: theme.spacing.lg,
              paddingTop: theme.spacing.sm,
            },
            sharedContentStyle,
          ]}
        >
          {children}
        </View>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  content: {
    alignSelf: 'center',
    width: '100%',
  },
  fixedContent: {
    flex: 1,
  },
  safeArea: {
    flex: 1,
  },
  scrollContent: {
    flexGrow: 1,
  },
});
