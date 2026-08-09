import type { ReactNode } from 'react';
import { View } from 'react-native';

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
  const hasNavigation =
    (onBack !== undefined && backLabel !== undefined) || trailing !== undefined;

  return (
    <View style={{ gap: theme.spacing.lg }}>
      {hasNavigation ? (
        <View
          style={{
            alignItems: 'center',
            flexDirection: 'row',
            minHeight: theme.control.regularHeight,
          }}
        >
          {onBack === undefined || backLabel === undefined ? null : (
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
          )}
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
        <AppText accessibilityRole="header" variant="largeTitle">
          {title}
        </AppText>
        {description === undefined ? null : (
          <AppText muted>{description}</AppText>
        )}
      </View>
    </View>
  );
}
