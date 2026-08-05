import assert from 'node:assert/strict';
import test from 'node:test';
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

test('sage green uses the approved tokens with readable text, links, and controls', () => {
  const green = readerThemeSurfaces.green;
  assert.deepEqual(
    { background: green.background, color: green.color, link: green.link, accent: green.accent },
    { background: '#E8F0E3', color: '#203126', link: '#2F6B45', accent: '#3F6F4E' }
  );
  assert.ok(contrast(green.background, green.color) >= 4.5);
  assert.ok(contrast(green.background, green.link) >= 4.5);
  assert.ok(contrast(green.background, green.accent) >= 4.5);
});

test('system mode maps to day and night without replacing the remembered manual theme', () => {
  assert.equal(resolveReaderTheme('green', 'system', false), 'day');
  assert.equal(resolveReaderTheme('green', 'system', true), 'night');
  assert.equal(resolveReaderTheme('green', 'manual', true), 'green');
});
