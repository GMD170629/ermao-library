import { usePathname, useRouter } from 'expo-router';
import type { ReactNode } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useI18n } from '../shared/i18n/public';
import { AppIcon, AppText, useAppTheme } from '../shared/ui/public';
import {
  compactNavigationVerticalPadding,
  shellRouteDefinitions,
  shellRouteForPath,
  shellRoutes,
} from './navigation';

export type ShellNavigationProps = Readonly<{
  expanded: boolean;
}>;

export function ShellNavigation({
  expanded,
}: ShellNavigationProps): ReactNode {
  const theme = useAppTheme();
  const { t } = useI18n();
  const pathname = usePathname();
  const router = useRouter();
  const safeAreaInsets = useSafeAreaInsets();
  const selectedRoute = shellRouteForPath(pathname);
  const compactPadding = compactNavigationVerticalPadding({
    bottomInset: safeAreaInsets.bottom,
    edgePadding: theme.spacing.xxs,
    maximumSafeAreaOverlap: theme.spacing.md,
    minimumSafeBottomClearance: theme.spacing.xs,
  });

  return (
    <View
      accessibilityLabel={t('shell.navigationLabel')}
      accessibilityRole="tablist"
      style={[
        expanded ? styles.expanded : styles.compact,
        !expanded && compactPadding,
        {
          backgroundColor: theme.colors.card,
          borderColor: theme.colors.border,
        },
      ]}
    >
      {shellRoutes.map((route) => {
        const definition = shellRouteDefinitions[route];
        const selected = route === selectedRoute;
        const label = t(definition.labelKey);

        return (
          <Pressable
            accessibilityHint={t(definition.hintKey)}
            accessibilityLabel={label}
            accessibilityRole="tab"
            accessibilityState={{ selected }}
            hitSlop={4}
            key={route}
            onPress={() => {
              if (!selected) {
                router.replace(definition.path);
              }
            }}
            style={({ pressed }) => [
              styles.item,
              expanded ? styles.expandedItem : styles.compactItem,
              selected && {
                backgroundColor: theme.colors.tintMuted,
              },
              pressed && {
                backgroundColor: theme.colors.tintMuted,
                opacity: 0.7,
              },
            ]}
          >
            <AppIcon
              color={
                selected
                  ? theme.colors.tint
                  : theme.colors.textMuted
              }
              decorative
              name={definition.iconName}
              size={
                expanded
                  ? theme.control.iconMedium
                  : theme.control.iconLarge
              }
            />
            <AppText
              style={[
                expanded ? styles.expandedLabel : styles.compactLabel,
                {
                  color: selected
                    ? theme.colors.tint
                    : theme.colors.textMuted,
                },
              ]}
              variant={expanded ? 'label' : 'caption'}
            >
              {label}
            </AppText>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  compact: {
    borderTopWidth: StyleSheet.hairlineWidth,
    flexDirection: 'row',
    paddingHorizontal: 6,
  },
  compactItem: {
    flex: 1,
    gap: 2,
    minHeight: 60,
    paddingHorizontal: 4,
  },
  compactLabel: {
    textAlign: 'center',
  },
  expanded: {
    flex: 1,
    gap: 4,
    padding: 12,
  },
  expandedItem: {
    flexDirection: 'row',
    gap: 12,
    justifyContent: 'flex-start',
    minHeight: 48,
    paddingHorizontal: 12,
  },
  expandedLabel: {
    flexShrink: 1,
  },
  item: {
    alignItems: 'center',
    borderRadius: 14,
    justifyContent: 'center',
    position: 'relative',
    paddingVertical: 6,
  },
});
