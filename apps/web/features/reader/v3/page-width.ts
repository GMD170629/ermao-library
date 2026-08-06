export const READER_PAGE_WIDTH_MINIMUM = 600;
export const READER_PAGE_WIDTH_MAXIMUM = 1350;
export const MOBILE_READER_VIEWPORT_MAXIMUM = 640;

export function normalizeReaderPageWidth(value: number) {
  const finiteValue = Number.isFinite(value) ? value : READER_PAGE_WIDTH_MAXIMUM;
  return Math.round(Math.max(READER_PAGE_WIDTH_MINIMUM, Math.min(READER_PAGE_WIDTH_MAXIMUM, finiteValue)));
}

/** Mobile reading always fills the viewport; wider layouts honor the saved cap. */
export function effectiveReaderPageWidth(preferredWidth: number, viewportWidth: number) {
  const availableWidth = Math.max(1, Math.round(viewportWidth));
  if (availableWidth <= MOBILE_READER_VIEWPORT_MAXIMUM) return availableWidth;
  return Math.min(availableWidth, normalizeReaderPageWidth(preferredWidth));
}

export function readerPageWidthSliderMaximum(viewportWidth: number) {
  return Math.max(
    READER_PAGE_WIDTH_MINIMUM,
    Math.min(READER_PAGE_WIDTH_MAXIMUM, Math.floor(viewportWidth))
  );
}
