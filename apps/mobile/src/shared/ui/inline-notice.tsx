import type { ReactNode } from 'react';
import { View } from 'react-native';

import { AppIcon, type AppIconName } from './app-icon';
import { AppText } from './app-text';
import { useAppTheme } from './theme-provider';

export type InlineNoticeTone = 'danger' | 'info' | 'success' | 'warning';

export type InlineNoticeProps = Readonly<{
  body: string;
  title?: string;
  tone?: InlineNoticeTone;
}>;

export function InlineNotice({
  body,
  title,
  tone = 'info',
}: InlineNoticeProps): ReactNode {
  const theme = useAppTheme();
  const appearance =
    tone === 'danger'
      ? {
          background: theme.colors.dangerMuted,
          icon: 'warning' as AppIconName,
          marker: theme.colors.danger,
        }
      : tone === 'warning'
        ? {
            background: theme.colors.warningMuted,
            icon: 'warning' as AppIconName,
            marker: theme.colors.warning,
          }
        : tone === 'success'
          ? {
              background: theme.colors.successMuted,
              icon: 'check' as AppIconName,
              marker: theme.colors.success,
            }
          : {
              background: theme.colors.tintMuted,
              icon: 'info' as AppIconName,
              marker: theme.colors.tint,
            };

  return (
    <View
      accessibilityLiveRegion={tone === 'danger' ? 'assertive' : 'polite'}
      accessibilityRole={tone === 'danger' ? 'alert' : 'text'}
      style={{
        alignItems: 'flex-start',
        backgroundColor: appearance.background,
        borderRadius: theme.radius.control,
        flexDirection: 'row',
        gap: theme.spacing.sm,
        padding: theme.spacing.md,
      }}
    >
      <AppIcon
        color={appearance.marker}
        name={appearance.icon}
        size={theme.control.iconSmall}
      />
      <View style={{ flex: 1, gap: theme.spacing.xxs }}>
        {title === undefined ? null : (
          <AppText variant="label">{title}</AppText>
        )}
        <AppText>{body}</AppText>
      </View>
    </View>
  );
}
