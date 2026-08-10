import type { ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

import { AppIcon } from './app-icon';
import { AppText } from './app-text';
import { IconButton } from './icon-button';
import { useAppTheme } from './theme-provider';

export type PageHeaderProps = Readonly<{
  backAccessibilityHint?: string;
  backLabel?: string;
  description?: string;
  eyebrow?: string;
  onBack?: () => void;
  title: string;
  trailing?: ReactNode;
}>;

export function PageHeader({
  backAccessibilityHint,
  backLabel,
  description,
  eyebrow,
  onBack,
  title,
  trailing,
}: PageHeaderProps): ReactNode {
  const theme = useAppTheme();
  const hasBack = onBack !== undefined && backLabel !== undefined;
  const titleTrailing = hasBack ? undefined : trailing;

  return (
    <View style={{ gap: theme.spacing.lg }}>
      {hasBack ? (
        <View
          style={{
            alignItems: 'center',
            flexDirection: 'row',
            minHeight: theme.control.regularHeight,
          }}
        >
          <IconButton
            {...(backAccessibilityHint === undefined
              ? {}
              : { accessibilityHint: backAccessibilityHint })}
            accessibilityLabel={backLabel}
            icon={
              <AppIcon
                color={theme.colors.tint}
                name="back"
                size={theme.control.iconLarge}
              />
            }
            onPress={onBack}
            tone="tint"
          />
          <View style={{ flex: 1 }} />
          {trailing}
        </View>
      ) : null}
      <View style={{ gap: theme.spacing.xs }}>
        {eyebrow === undefined ? null : (
          <AppText muted variant="caption">
            {eyebrow}
          </AppText>
        )}
        <View style={[styles.titleRow, { gap: theme.spacing.md }]}>
          <AppText
            accessibilityRole="header"
            style={styles.title}
            variant="largeTitle"
          >
            {title}
          </AppText>
          {titleTrailing}
        </View>
        {description === undefined ? null : (
          <AppText muted>{description}</AppText>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  title: {
    flex: 1,
    minWidth: 0,
  },
  titleRow: {
    alignItems: 'center',
    flexDirection: 'row',
  },
});
