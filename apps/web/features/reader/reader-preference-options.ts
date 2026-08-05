export const READER_THEME_OPTIONS = [
  { value: 'day', label: '白天' },
  { value: 'warm', label: '暖色' },
  { value: 'green', label: '护眼绿' },
  { value: 'night', label: '夜间' },
  { value: 'black', label: '纯黑' }
] as const;

export const READER_FONT_SIZE_OPTIONS = [
  { value: '16', label: '小' },
  { value: '18', label: '中' },
  { value: '22', label: '大' }
] as const;

export const READER_LINE_HEIGHT_OPTIONS = [
  { value: '1.6', label: '小' },
  { value: '1.9', label: '中' },
  { value: '2.2', label: '大' }
] as const;

export const READER_FONT_FAMILY_OPTIONS = [
  { value: 'pingfang', label: '苹方' },
  { value: 'heiti', label: '黑体' },
  { value: 'songti', label: '宋体' },
  { value: 'yahei', label: '微软雅黑' },
  { value: 'kaiti', label: '楷体' }
] as const;

export const READER_PAGE_WIDTH_OPTIONS = [
  { value: '760', label: '窄' },
  { value: '1050', label: '中' },
  { value: '1350', label: '宽' }
] as const;

export const READER_FLOW_OPTIONS = [
  { value: 'paginated', label: '分页' },
  { value: 'scrolled', label: '滚动' }
] as const;

export const READER_SPREAD_MODE_OPTIONS = [
  { value: 'auto', label: '自动' },
  { value: 'single', label: '单页' },
  { value: 'double', label: '双页' }
] as const;

export const READER_FONT_WEIGHT_OPTIONS = [
  { value: '400', label: '常规' },
  { value: '500', label: '中等' },
  { value: '700', label: '粗体' }
] as const;

export const READER_LETTER_SPACING_OPTIONS = [
  { value: '-0.02', label: '紧凑' },
  { value: '0', label: '标准' },
  { value: '0.04', label: '舒展' },
  { value: '0.08', label: '宽松' }
] as const;

export const READER_PAGE_MARGIN_OPTIONS = [
  { value: 'narrow', label: '窄' },
  { value: 'standard', label: '标准' },
  { value: 'wide', label: '宽' }
] as const;

export const READER_PROGRESS_STYLE_OPTIONS = [
  { value: 'auto', label: '自动' },
  { value: 'percent', label: '百分比' },
  { value: 'position', label: '当前位置' },
  { value: 'remaining', label: '剩余量' },
  { value: 'hidden', label: '隐藏' }
] as const;

export const READER_COMIC_FLOW_OPTIONS = [
  { value: 'paged', label: '分页' },
  { value: 'vertical', label: '竖向连续' }
] as const;

export const READER_PAGE_GAP_OPTIONS = [0, 8, 16, 24].map((value) => ({ value: String(value), label: value === 0 ? '无' : `${value}px` }));

export const READER_PDF_FLOW_OPTIONS = [
  { value: 'paged', label: '分页' },
  { value: 'continuous', label: '连续滚动' }
] as const;

export const READER_PDF_ROTATION_OPTIONS = [0, 90, 180, 270].map((value) => ({ value: String(value), label: `${value}°` }));

export const READER_PDF_CROP_OPTIONS = [
  { value: 'off', label: '关闭' },
  { value: 'auto', label: '自动' }
] as const;

export const READER_PAGE_TURN_ANIMATION_OPTIONS = [
  { value: 'slide', label: '平移' },
  { value: 'off', label: '关闭' }
] as const;

export const READER_COMIC_IMAGE_FIT_OPTIONS = [
  { value: 'width', label: '宽度' },
  { value: 'height', label: '高度' },
  { value: 'contain', label: '完整' },
  { value: 'original', label: '原始' }
] as const;

export const READER_COMIC_IMAGE_VARIANT_OPTIONS = [
  { value: 'original', label: '原图' },
  { value: 'data-saver', label: '省流' }
] as const;

export const READER_COMIC_DIRECTION_OPTIONS = [
  { value: 'ltr', label: '左至右' },
  { value: 'rtl', label: '右至左' }
] as const;

export const READER_PDF_FIT_OPTIONS = [
  { value: 'width', label: '宽度' },
  { value: 'page', label: '整页' }
] as const;

export const READER_TAP_ZONE_OPTIONS = [
  { value: 'standard', label: '标准' },
  { value: 'reversed', label: '反向' },
  { value: 'disabled', label: '关闭' }
] as const;

export const READER_TEXT_ALIGN_OPTIONS = [
  { value: 'publisher', label: '原书' },
  { value: 'left', label: '左对齐' },
  { value: 'justify', label: '两端对齐' }
] as const;

export const READER_PARAGRAPH_INDENT_OPTIONS = [
  { value: '0', label: '关闭' },
  { value: '1', label: '一字' },
  { value: '2', label: '两字' },
  { value: '3', label: '三字' }
] as const;

export const READER_PARAGRAPH_SPACING_OPTIONS = [
  { value: '0', label: '原书' },
  { value: '0.4', label: '小' },
  { value: '0.8', label: '中' },
  { value: '1.2', label: '大' }
] as const;

export function closestReaderOptionValue(value: number, options: ReadonlyArray<{ value: string }>) {
  return options.reduce((closest, option) => (
    Math.abs(Number(option.value) - value) < Math.abs(Number(closest.value) - value) ? option : closest
  )).value;
}

export function adjacentReaderOptionValue(
  value: number,
  options: ReadonlyArray<{ value: string }>,
  direction: -1 | 1
) {
  const closestValue = closestReaderOptionValue(value, options);
  const currentIndex = options.findIndex((option) => option.value === closestValue);
  const nextIndex = Math.max(0, Math.min(options.length - 1, currentIndex + direction));
  return options[nextIndex]?.value ?? closestValue;
}

export type ReaderFontFamily = typeof READER_FONT_FAMILY_OPTIONS[number]['value'];
