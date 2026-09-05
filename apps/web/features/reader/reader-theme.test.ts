import assert from 'node:assert/strict';
import test from 'node:test';
import { visualTokens } from '../../generated/visual-tokens';
import { readerThemeSurfaces, resolveReaderTheme } from './reader-theme';

function luminance(hex: string) {
  const channels = [1, 3, 5].map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16) / 255)
    .map((channel) => channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);
  return (channels[0] ?? 0) * 0.2126 + (channels[1] ?? 0) * 0.7152 + (channels[2] ?? 0) * 0.0722;
}

function contrast(first: string, second: string) {
  const light = Math.max(luminance(first), luminance(second));
  const dark = Math.min(luminance(first), luminance(second));
  return (light + 0.05) / (dark + 0.05);
}

test('all reader surfaces come from the generated contract with readable text and controls', () => {
  for (const theme of ['day', 'warm', 'green', 'night', 'black'] as const) {
    const surface = readerThemeSurfaces[theme];
    const token = visualTokens.reader.themes[theme];
    assert.deepEqual(
      { background: surface.background, color: surface.color, link: surface.link, accent: surface.accent },
      { background: token.canvas, color: token.textPrimary, link: token.link, accent: token.accent }
    );
    assert.equal(surface.colorScheme, token.colorScheme);
    assert.ok(contrast(surface.background, surface.color) >= 4.5);
    assert.ok(contrast(surface.background, surface.link) >= 3);
  }
});

test('system mode maps to day and night without replacing the remembered manual theme', () => {
  assert.equal(resolveReaderTheme('green', 'system', false), 'day');
  assert.equal(resolveReaderTheme('green', 'system', true), 'night');
  assert.equal(resolveReaderTheme('green', 'manual', true), 'green');
});
