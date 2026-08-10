import type { TextStyle, ViewStyle } from 'react-native';

export type ColorScheme = 'dark' | 'light';

export type TextVariant =
  | 'body'
  | 'caption'
  | 'headline'
  | 'label'
  | 'largeTitle'
  | 'title';

type SemanticTypeStyle = Readonly<
  Pick<
    TextStyle,
    'fontSize' | 'fontWeight' | 'letterSpacing' | 'lineHeight'
  >
>;

export type AppTheme = Readonly<{
  breakpoint: Readonly<{
    compactHorizontalPadding: number;
    compactMinimumHorizontalPadding: number;
    contentMaxWidth: number;
    expandedHorizontalPadding: number;
    expandedMinWidth: number;
  }>;
  colors: Readonly<{
    actionFill: string;
    actionPressed: string;
    background: string;
    border: string;
    borderStrong: string;
    brand: string;
    card: string;
    cardStrong: string;
    danger: string;
    dangerMuted: string;
    focus: string;
    onAction: string;
    overlay: string;
    success: string;
    successMuted: string;
    text: string;
    textMuted: string;
    tint: string;
    tintMuted: string;
    tintText: string;
    warning: string;
    warningMuted: string;
  }>;
  control: Readonly<{
    iconLarge: number;
    iconMedium: number;
    iconSmall: number;
    minimumTouchTarget: number;
    regularHeight: number;
  }>;
  elevation: Readonly<{
    card: Readonly<ViewStyle>;
    floating: Readonly<ViewStyle>;
    none: Readonly<ViewStyle>;
  }>;
  isDark: boolean;
  /** @deprecated Prefer the named semantic token groups. */
  metrics: Readonly<{
    compactRadius: number;
    contentMaxWidth: number;
    controlHeight: number;
    radius: number;
    spaciousRadius: number;
  }>;
  motion: Readonly<{
    micro: number;
    microMaximum: number;
    microMinimum: number;
    reduced: number;
    transition: number;
    transitionMaximum: number;
    transitionMinimum: number;
  }>;
  radius: Readonly<{
    compact: number;
    control: number;
    spacious: number;
  }>;
  spacing: Readonly<{
    lg: number;
    md: number;
    sm: number;
    xl: number;
    xs: number;
    xxl: number;
    xxxl: number;
    xxs: number;
  }>;
  type: Readonly<Record<TextVariant, SemanticTypeStyle>>;
}>;

const spacing: AppTheme['spacing'] = {
  xxs: 4,
  xs: 8,
  sm: 12,
  md: 16,
  lg: 20,
  xl: 24,
  xxl: 32,
  xxxl: 40,
};

const type: AppTheme['type'] = {
  body: {
    fontSize: 17,
    fontWeight: '400',
    letterSpacing: 0,
    lineHeight: 25,
  },
  caption: {
    fontSize: 13,
    fontWeight: '400',
    letterSpacing: 0,
    lineHeight: 18,
  },
  headline: {
    fontSize: 18,
    fontWeight: '700',
    letterSpacing: 0,
    lineHeight: 24,
  },
  label: {
    fontSize: 16,
    fontWeight: '700',
    letterSpacing: 0,
    lineHeight: 21,
  },
  largeTitle: {
    fontSize: 34,
    fontWeight: '800',
    letterSpacing: -0.7,
    lineHeight: 41,
  },
  title: {
    fontSize: 28,
    fontWeight: '700',
    letterSpacing: -0.45,
    lineHeight: 35,
  },
};

const control: AppTheme['control'] = {
  iconLarge: 24,
  iconMedium: 22,
  iconSmall: 20,
  minimumTouchTarget: 44,
  regularHeight: 48,
};

const radius: AppTheme['radius'] = {
  compact: 10,
  control: 14,
  spacious: 20,
};

const breakpoint: AppTheme['breakpoint'] = {
  compactHorizontalPadding: 20,
  compactMinimumHorizontalPadding: 16,
  contentMaxWidth: 760,
  expandedHorizontalPadding: 32,
  expandedMinWidth: 768,
};

const motion: AppTheme['motion'] = {
  micro: 200,
  microMaximum: 240,
  microMinimum: 160,
  reduced: 0,
  transition: 280,
  transitionMaximum: 320,
  transitionMinimum: 240,
};

const metrics: AppTheme['metrics'] = {
  compactRadius: radius.compact,
  contentMaxWidth: breakpoint.contentMaxWidth,
  controlHeight: control.regularHeight,
  radius: radius.control,
  spaciousRadius: radius.spacious,
};

const lightElevation: AppTheme['elevation'] = {
  card: {
    elevation: 1,
    shadowColor: '#3B2D24',
    shadowOffset: { height: 2, width: 0 },
    shadowOpacity: 0.04,
    shadowRadius: 8,
  },
  floating: {
    elevation: 6,
    shadowColor: '#3B2D24',
    shadowOffset: { height: 8, width: 0 },
    shadowOpacity: 0.12,
    shadowRadius: 16,
  },
  none: {
    elevation: 0,
    shadowOpacity: 0,
  },
};

const darkElevation: AppTheme['elevation'] = {
  card: {
    elevation: 1,
    shadowColor: '#000000',
    shadowOffset: { height: 2, width: 0 },
    shadowOpacity: 0.16,
    shadowRadius: 8,
  },
  floating: {
    elevation: 6,
    shadowColor: '#000000',
    shadowOffset: { height: 8, width: 0 },
    shadowOpacity: 0.28,
    shadowRadius: 16,
  },
  none: {
    elevation: 0,
    shadowOpacity: 0,
  },
};

const sharedTheme = {
  breakpoint,
  control,
  metrics,
  motion,
  radius,
  spacing,
  type,
} as const;

// Keep the native light appearance aligned with the Web palette without
// importing a Web-private stylesheet at runtime.
const webLightPalette = {
  accent: '#FF4F2A',
  accentHover: '#E94320',
  accentSoft: '#FCE6DF',
  background: '#FBFAF8',
  border: '#E6E1DB',
  borderStrong: '#D8D1C9',
  focus: 'rgba(255, 155, 126, 0.42)',
  panel: '#FFFDFA',
  panelStrong: '#FFFFFF',
  success: '#3F9C59',
  text: '#17191D',
  textMuted: '#77736F',
  warning: '#C67B12',
} as const;

const lightAccessibilityColors = {
  onAction: '#15171B',
  tintText: '#A23A22',
} as const;

const lightTheme: AppTheme = {
  ...sharedTheme,
  elevation: lightElevation,
  isDark: false,
  colors: {
    actionFill: webLightPalette.accent,
    actionPressed: webLightPalette.accentHover,
    background: webLightPalette.background,
    border: webLightPalette.border,
    borderStrong: webLightPalette.borderStrong,
    brand: webLightPalette.accent,
    card: webLightPalette.panel,
    cardStrong: webLightPalette.panelStrong,
    danger: '#A53A32',
    dangerMuted: '#FEECEB',
    focus: webLightPalette.focus,
    onAction: lightAccessibilityColors.onAction,
    overlay: 'rgba(23, 25, 29, 0.58)',
    success: webLightPalette.success,
    successMuted: '#E8F5EB',
    text: webLightPalette.text,
    textMuted: webLightPalette.textMuted,
    tint: webLightPalette.accent,
    tintMuted: webLightPalette.accentSoft,
    tintText: lightAccessibilityColors.tintText,
    warning: webLightPalette.warning,
    warningMuted: '#FFF3D9',
  },
};

const darkTheme: AppTheme = {
  ...sharedTheme,
  elevation: darkElevation,
  isDark: true,
  colors: {
    actionFill: '#B9432E',
    actionPressed: '#963625',
    background: '#171310',
    border: '#3D332E',
    borderStrong: '#554B44',
    brand: '#FF7A59',
    card: '#211B18',
    cardStrong: '#26211E',
    danger: '#FF9289',
    dangerMuted: '#4A2422',
    focus: '#D96A50',
    onAction: '#FFF9F5',
    overlay: 'rgba(0, 0, 0, 0.68)',
    success: '#7DCB92',
    successMuted: '#203D29',
    text: '#FFF6F3',
    textMuted: '#C8B8AF',
    tint: '#FF9B7F',
    tintMuted: '#4B271F',
    tintText: '#FF9B7F',
    warning: '#F0B963',
    warningMuted: '#44351C',
  },
};

export function appTheme(colorScheme: ColorScheme): AppTheme {
  return colorScheme === 'dark' ? darkTheme : lightTheme;
}
