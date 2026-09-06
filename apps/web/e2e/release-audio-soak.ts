import { appendFile } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';

import { expect, type Page } from '@playwright/test';

export function audioSoakSeconds(): number {
  const seconds = Number(process.env.RELEASE_LIVE_AUDIO_SOAK_SECONDS ?? '0');
  if (!Number.isInteger(seconds) || seconds < 0 || seconds > 7_200) {
    throw new Error('RELEASE_LIVE_AUDIO_SOAK_SECONDS must be an integer from 0 to 7200');
  }
  return seconds;
}

/** A test-owned observer with explicit disposal; never changes playback. */
export async function startAudioProbe(page: Page) {
  return page.locator('audio').evaluateHandle((audio: HTMLAudioElement) => {
    const started = performance.now();
    let lastSample = started;
    let lastAdvance = started;
    let lastPosition = audio.currentTime;
    let maxSamplingGapMillis = 0;
    let maxNoAdvanceMillis = 0;
    const events: { elapsedMillis: number; type: string; positionMillis: number }[] = [];
    const samples: {
      elapsedMillis: number; positionMillis: number; paused: boolean;
      ended: boolean; readyState: number; playbackRate: number;
    }[] = [];
    const observeEvent = (event: Event) => {
      events.push({ elapsedMillis: performance.now() - started, type: event.type, positionMillis: audio.currentTime * 1_000 });
    };
    const eventTypes = ['waiting', 'stalled', 'playing', 'pause', 'ended', 'error', 'seeking', 'seeked', 'ratechange'];
    for (const type of eventTypes) audio.addEventListener(type, observeEvent);
    const timer = setInterval(() => {
      const now = performance.now();
      maxSamplingGapMillis = Math.max(maxSamplingGapMillis, now - lastSample);
      maxNoAdvanceMillis = Math.max(maxNoAdvanceMillis, now - lastAdvance);
      if (audio.currentTime > lastPosition) lastAdvance = now;
      samples.push({
        elapsedMillis: now - started, positionMillis: audio.currentTime * 1_000,
        paused: audio.paused, ended: audio.ended, readyState: audio.readyState, playbackRate: audio.playbackRate
      });
      lastPosition = audio.currentTime;
      lastSample = now;
    }, 100);
    return {
      remainingSeconds: audio.duration - audio.currentTime,
      read() {
        return {
          elapsedMillis: performance.now() - started,
          currentPositionMillis: audio.currentTime * 1_000,
          seeking: audio.seeking, paused: audio.paused,
          seekable: Array.from({ length: audio.seekable.length }, (_, index) => [audio.seekable.start(index), audio.seekable.end(index)]),
          maxSamplingGapMillis, maxNoAdvanceMillis,
          samples: samples.splice(0), events: events.splice(0)
        };
      },
      stop() {
        clearInterval(timer);
        for (const type of eventTypes) audio.removeEventListener(type, observeEvent);
      }
    };
  });
}

/** Observe the existing engine; never seek, loop, restart or replace its source. */
export async function observeAudioSoak(
  page: Page,
  seconds: number,
  evidencePath: string,
  verifyProgress: () => Promise<void>
): Promise<void> {
  const probe = await startAudioProbe(page);
  try {
    expect(await probe.evaluate((value) => value.remainingSeconds), 'source must span the whole observation without looping').toBeGreaterThan(seconds + 10);
    const deadline = Date.now() + seconds * 1_000;
    while (Date.now() < deadline) {
      await delay(5_000);
      const observation = await probe.evaluate((value) => value.read());
      await appendFile(evidencePath, `${JSON.stringify(observation)}\n`, 'utf8');
      expect(observation.maxSamplingGapMillis, 'observer gaps cannot hide playback stalls').toBeLessThanOrEqual(2_000);
      expect(observation.maxNoAdvanceMillis, 'continuous engine playback must not stop for over two seconds').toBeLessThanOrEqual(2_000);
      expect(observation.samples.length).toBeGreaterThan(0);
      for (const sample of observation.samples) {
        expect(sample.paused).toBe(false);
        expect(sample.ended).toBe(false);
        expect(sample.playbackRate).toBe(1);
      }
      expect(observation.events.filter((event) => ['pause', 'ended', 'error', 'seeking', 'seeked'].includes(event.type))).toEqual([]);
      await verifyProgress();
    }
  } finally {
    await probe.evaluate((value) => value.stop());
    await probe.dispose();
  }
}
