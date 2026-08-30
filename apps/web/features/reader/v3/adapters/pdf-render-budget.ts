import { READER_SAFETY_BUDGETS } from '@shuku/reader-core';

export const PDF_MAX_CANVAS_PIXELS = READER_SAFETY_BUDGETS.pdfRenderMaxPixels;
export const PDF_MAX_CANVAS_DIMENSION = READER_SAFETY_BUDGETS.pdfCanvasMaxDimension;

export type PdfRenderBudgetInput = {
  cssWidth: number;
  cssHeight: number;
  devicePixelRatio: number;
  maxPixels?: number;
  maxDimension?: number;
};

export type PdfRenderBudget = {
  outputScale: number;
  pixelWidth: number;
  pixelHeight: number;
  cssWidth: number;
  cssHeight: number;
  constrained: boolean;
};

export function computePdfRenderBudget(input: PdfRenderBudgetInput): PdfRenderBudget {
  const cssWidth = Number.isFinite(input.cssWidth) ? Math.max(1, input.cssWidth) : 1;
  const cssHeight = Number.isFinite(input.cssHeight) ? Math.max(1, input.cssHeight) : 1;
  const requestedScale = Number.isFinite(input.devicePixelRatio) ? Math.max(1, input.devicePixelRatio) : 1;
  const maxPixels = Math.max(1, input.maxPixels ?? PDF_MAX_CANVAS_PIXELS);
  const maxDimension = Math.max(1, input.maxDimension ?? PDF_MAX_CANVAS_DIMENSION);
  const areaScale = Math.sqrt(maxPixels / (cssWidth * cssHeight));
  const dimensionScale = Math.min(maxDimension / cssWidth, maxDimension / cssHeight);
  // There is intentionally no scale floor: an extreme or malformed page must
  // become blurry rather than exceed Safari's canvas memory/dimension limits.
  const outputScale = Math.min(requestedScale, areaScale, dimensionScale);
  const pixelWidth = Math.max(1, Math.floor(cssWidth * outputScale));
  const pixelHeight = Math.max(1, Math.floor(cssHeight * outputScale));

  return {
    outputScale,
    pixelWidth,
    pixelHeight,
    cssWidth,
    cssHeight,
    constrained: outputScale + 0.001 < requestedScale
  };
}

export function pdfPageScale(options: {
  pageWidth: number;
  pageHeight: number;
  containerWidth: number;
  containerHeight: number;
  fit: 'width' | 'page';
  zoom: number;
}) {
  const widthScale = Math.max(0.01, options.containerWidth / Math.max(1, options.pageWidth));
  const heightScale = Math.max(0.01, options.containerHeight / Math.max(1, options.pageHeight));
  const fitScale = options.fit === 'page' ? Math.min(widthScale, heightScale) : widthScale;
  return fitScale * Math.max(0.6, Math.min(2.4, options.zoom));
}
