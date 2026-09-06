import { expect, type Page } from '@playwright/test';

export async function visibleReaderFrame(page: Page) {
  const shell = page.locator('[data-reader-shell="v3"]');
  await expect(shell).toBeVisible();
  await expect(shell.locator('[data-reader-error-code]')).toHaveCount(0);
  await expect(page.locator('[data-reader-opening-cover="loading"]')).toHaveCount(0);
  const frame = shell.locator('iframe:visible').first();
  await expect(frame).toBeVisible();
  return frame;
}

export async function revealReaderControls(page: Page): Promise<void> {
  const frame = await visibleReaderFrame(page);
  const appearance = page.getByRole('button', { name: '外观', exact: true });
  if (await appearance.isVisible()) return;
  const bounds = await frame.boundingBox();
  if (!bounds) throw new Error('READIUM_FRAME_BOUNDS_MISSING');
  await page.mouse.click(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await expect(appearance).toBeVisible();
}
