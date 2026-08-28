export type PdfCropBox = Readonly<{ left: number; top: number; right: number; bottom: number }>;

export function pdfContinuousWindowPages(pageNumber: number, pageCount: number) {
  const begin = Math.max(1, pageNumber - 1);
  const end = Math.min(pageCount, pageNumber + 1);
  return Array.from({ length: Math.max(0, end - begin + 1) }, (_, index) => begin + index);
}

export function detectPdfCropBox(pixels: Uint8ClampedArray, width: number, height: number): PdfCropBox | null {
  if (width <= 0 || height <= 0 || pixels.length < width * height * 4) return null;
  let left = width;
  let top = height;
  let right = -1;
  let bottom = -1;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const offset = (y * width + x) * 4;
      if ((pixels[offset] ?? 255) > 245 && (pixels[offset + 1] ?? 255) > 245 && (pixels[offset + 2] ?? 255) > 245) continue;
      left = Math.min(left, x);
      top = Math.min(top, y);
      right = Math.max(right, x);
      bottom = Math.max(bottom, y);
    }
  }
  const contentArea = right >= left && bottom >= top ? (right - left + 1) * (bottom - top + 1) : 0;
  const marginDetected = left > width * 0.015 || top > height * 0.015 || right < width * 0.985 || bottom < height * 0.985;
  if (contentArea <= width * height * 0.02 || !marginDetected) return null;
  const padding = 2;
  return {
    left: Math.max(0, left - padding) / width,
    top: Math.max(0, top - padding) / height,
    right: Math.min(width, right + padding + 1) / width,
    bottom: Math.min(height, bottom + padding + 1) / height
  };
}
