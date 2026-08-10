import assert from 'node:assert/strict';
import test from 'node:test';

import { appTheme } from './theme';

test('theme synchronizes the Web light palette and mobile dark adaptations', () => {
  const light = appTheme('light');
  const dark = appTheme('dark');

  assert.deepEqual(
    {
      actionFill: light.colors.actionFill,
      actionPressed: light.colors.actionPressed,
      background: light.colors.background,
      border: light.colors.border,
      brand: light.colors.brand,
      card: light.colors.card,
      cardStrong: light.colors.cardStrong,
      danger: light.colors.danger,
      onAction: light.colors.onAction,
      success: light.colors.success,
      text: light.colors.text,
      textMuted: light.colors.textMuted,
      tint: light.colors.tint,
      tintText: light.colors.tintText,
      warning: light.colors.warning,
    },
    {
      actionFill: '#FF4F2A',
      actionPressed: '#E94320',
      background: '#FBFAF8',
      border: '#E6E1DB',
      brand: '#FF4F2A',
      card: '#FFFDFA',
      cardStrong: '#FFFFFF',
      danger: '#A53A32',
      onAction: '#15171B',
      success: '#3F9C59',
      text: '#17191D',
      textMuted: '#77736F',
      tint: '#FF4F2A',
      tintText: '#A23A22',
      warning: '#C67B12',
    },
  );
  assert.deepEqual(
    {
      actionFill: dark.colors.actionFill,
      background: dark.colors.background,
      border: dark.colors.border,
      brand: dark.colors.brand,
      card: dark.colors.card,
      danger: dark.colors.danger,
      onAction: dark.colors.onAction,
      success: dark.colors.success,
      text: dark.colors.text,
      textMuted: dark.colors.textMuted,
      tint: dark.colors.tint,
      tintText: dark.colors.tintText,
      warning: dark.colors.warning,
    },
    {
      actionFill: '#B9432E',
      background: '#171310',
      border: '#3D332E',
      brand: '#FF7A59',
      card: '#211B18',
      danger: '#FF9289',
      onAction: '#FFF9F5',
      success: '#7DCB92',
      text: '#FFF6F3',
      textMuted: '#C8B8AF',
      tint: '#FF9B7F',
      tintText: '#FF9B7F',
      warning: '#F0B963',
    },
  );
});

test('emphasis and action foregrounds meet their contrast requirements', () => {
  for (const colorScheme of ['light', 'dark'] as const) {
    const theme = appTheme(colorScheme);
    assert.ok(
      contrastRatio(theme.colors.tint, theme.colors.background) >= 3,
      `${colorScheme} tint must meet WCAG AA non-text contrast`,
    );
    assert.ok(
      contrastRatio(theme.colors.tintText, theme.colors.background) >= 4.5,
      `${colorScheme} tintText must meet WCAG AA normal-text contrast`,
    );
    assert.ok(
      contrastRatio(theme.colors.tintText, theme.colors.tintMuted) >= 4.5,
      `${colorScheme} tintText must remain legible on selected surfaces`,
    );
    assert.ok(
      contrastRatio(theme.colors.actionFill, theme.colors.onAction) >= 4.5,
      `${colorScheme} onAction must meet WCAG AA normal-text contrast`,
    );
    assert.ok(
      contrastRatio(theme.colors.actionPressed, theme.colors.onAction) >= 4.5,
      `${colorScheme} pressed onAction must meet WCAG AA normal-text contrast`,
    );
  }
});

test('unspecified component-support tokens retain recorded semantics', () => {
  const light = appTheme('light');
  const dark = appTheme('dark');

  assert.deepEqual(
    {
      borderStrong: light.colors.borderStrong,
      cardStrong: light.colors.cardStrong,
      dangerMuted: light.colors.dangerMuted,
      focus: light.colors.focus,
      overlay: light.colors.overlay,
      successMuted: light.colors.successMuted,
      tintMuted: light.colors.tintMuted,
      warningMuted: light.colors.warningMuted,
    },
    {
      borderStrong: '#D8D1C9',
      cardStrong: '#FFFFFF',
      dangerMuted: '#FEECEB',
      focus: 'rgba(255, 155, 126, 0.42)',
      overlay: 'rgba(23, 25, 29, 0.58)',
      successMuted: '#E8F5EB',
      tintMuted: '#FCE6DF',
      warningMuted: '#FFF3D9',
    },
  );
  assert.deepEqual(
    {
      actionPressed: dark.colors.actionPressed,
      borderStrong: dark.colors.borderStrong,
      cardStrong: dark.colors.cardStrong,
      dangerMuted: dark.colors.dangerMuted,
      focus: dark.colors.focus,
      overlay: dark.colors.overlay,
      successMuted: dark.colors.successMuted,
      tintMuted: dark.colors.tintMuted,
      warningMuted: dark.colors.warningMuted,
    },
    {
      actionPressed: '#963625',
      borderStrong: '#554B44',
      cardStrong: '#26211E',
      dangerMuted: '#4A2422',
      focus: '#D96A50',
      overlay: 'rgba(0, 0, 0, 0.68)',
      successMuted: '#203D29',
      tintMuted: '#4B271F',
      warningMuted: '#44351C',
    },
  );
  assert.equal('accent' in light.colors, false);
  assert.equal('accentMuted' in light.colors, false);
  assert.equal('accentPressed' in light.colors, false);
  assert.equal('onAccent' in light.colors, false);
});

test('semantic layout, type, control, and motion tokens match the fixed baseline', () => {
  const theme = appTheme('light');

  assert.deepEqual(Object.values(theme.spacing), [4, 8, 12, 16, 20, 24, 32, 40]);
  assert.deepEqual(theme.radius, { compact: 10, control: 14, spacious: 20 });
  assert.equal(theme.control.minimumTouchTarget, 44);
  assert.equal(theme.control.regularHeight, 48);
  assert.equal(theme.type.body.fontSize, 17);
  assert.equal(theme.type.largeTitle.fontSize, 34);
  assert.equal(theme.breakpoint.contentMaxWidth, 760);
  assert.ok(theme.motion.micro >= 160 && theme.motion.micro <= 240);
  assert.ok(theme.motion.transition >= 240 && theme.motion.transition <= 320);
});

function contrastRatio(first: string, second: string): number {
  const firstLuminance = relativeLuminance(first);
  const secondLuminance = relativeLuminance(second);
  const lighter = Math.max(firstLuminance, secondLuminance);
  const darker = Math.min(firstLuminance, secondLuminance);
  return (lighter + 0.05) / (darker + 0.05);
}

function relativeLuminance(hex: string): number {
  return (
    0.2126 * linearChannel(hex, 1) +
    0.7152 * linearChannel(hex, 3) +
    0.0722 * linearChannel(hex, 5)
  );
}

function linearChannel(hex: string, start: number): number {
  const channel = Number.parseInt(hex.slice(start, start + 2), 16) / 255;
  return channel <= 0.04045
    ? channel / 12.92
    : ((channel + 0.055) / 1.055) ** 2.4;
}
