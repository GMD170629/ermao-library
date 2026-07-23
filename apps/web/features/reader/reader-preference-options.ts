export const READER_THEME_OPTIONS = [
  { value: 'day', label: '白天' },
  { value: 'warm', label: '暖色' },
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
  { value: 'single', label: '单页' },
  { value: 'double', label: '双页' }
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

export function closestReaderOptionValue(value: number, options: ReadonlyArray<{ value: string }>) {
  return options.reduce((closest, option) => (
    Math.abs(Number(option.value) - value) < Math.abs(Number(closest.value) - value) ? option : closest
  )).value;
}

export type ReaderFontFamily = typeof READER_FONT_FAMILY_OPTIONS[number]['value'];
