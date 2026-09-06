import assert from 'node:assert/strict';
import test from 'node:test';
import { readiumTotalProgression } from './readium-navigation';

type ProgressPoint = {
  href: string;
  locations: {
    progression?: number;
    totalProgression?: number;
  };
};

function point(
  href: string,
  progression?: number,
  totalProgression?: number
): ProgressPoint {
  return { href, locations: { progression, totalProgression } };
}

test('interpolates unsorted resource points with stable duplicate boundary ties', () => {
  const positions = [
    point('chapter.xhtml', 0.5, 0.4),
    point('other.xhtml', 0.2, 0.8),
    point('chapter.xhtml', 1, 0.95),
    point('chapter.xhtml', 0.25, 0.2),
    point('chapter.xhtml', 0.5, 0.6),
    point('chapter.xhtml', 0.25, 0.3),
    point('chapter.xhtml', 0.75, 0.8)
  ];

  assert.equal(readiumTotalProgression(
    point('chapter.xhtml', 0.5, 0.01),
    positions
  ), 0.6);

  assert.equal(readiumTotalProgression(
    point('chapter.xhtml', 0.4, 0.01),
    positions
  ), 0.36);

  assert.equal(readiumTotalProgression(
    point('chapter.xhtml', 0.1, 0.01),
    positions
  ), 0.2);
});

test('uses bounded fallbacks for missing, invalid, and out-of-range values', () => {
  const positions = [
    point('chapter.xhtml', undefined, 0.4),
    point('chapter.xhtml', 1, 0.8)
  ];

  assert.equal(readiumTotalProgression(
    { href: 'chapter.xhtml', locations: {} },
    positions
  ), 0.4);
  assert.equal(readiumTotalProgression(
    { href: 'chapter.xhtml', locations: { progression: Number.NaN, totalProgression: 2 } },
    positions
  ), 0.4);
  assert.equal(readiumTotalProgression(
    { href: 'chapter.xhtml', locations: { progression: Number.POSITIVE_INFINITY, totalProgression: -1 } },
    positions
  ), 0.4);

  const clampedPositions = [
    point('chapter.xhtml', -2, 2),
    point('chapter.xhtml', Number.NaN, -1),
    point('chapter.xhtml', 2, 0.5)
  ];
  assert.equal(readiumTotalProgression(
    point('chapter.xhtml', 0.5, 0),
    clampedPositions
  ), 0.25);
});

test('returns a bounded current total when the resource has no matching position', () => {
  const positions = [point('other.xhtml', 0, 0.4)];

  assert.equal(readiumTotalProgression(
    { href: 'missing.xhtml', locations: {} },
    positions
  ), 0);
  assert.equal(readiumTotalProgression(
    { href: 'missing.xhtml', locations: { totalProgression: Number.NaN } },
    positions
  ), 0);
  assert.equal(readiumTotalProgression(
    { href: 'missing.xhtml', locations: { totalProgression: -2 } },
    positions
  ), 0);
  assert.equal(readiumTotalProgression(
    { href: 'missing.xhtml', locations: { totalProgression: 2 } },
    positions
  ), 1);
});

test('interpolates the final resource against the publication end', () => {
  const positions = [
    point('last.xhtml', 1, 0.9),
    point('last.xhtml', 0, 0.75)
  ];

  assert.equal(readiumTotalProgression(
    point('last.xhtml', 0.5, 0.75),
    positions
  ), 0.825);

  assert.equal(readiumTotalProgression(
    point('last.xhtml', 0.5, 0.75),
    [point('last.xhtml', 0, 0.75)]
  ), 0.875);

  assert.equal(readiumTotalProgression(
    point('last.xhtml', 1, 0.75),
    positions
  ), 0.9);
});

test('uses the first numeric next resource after the last match, including NaN, and skips missing totals', () => {
  const positions = [
    point('chapter.xhtml', 0, 0.2),
    point('earlier-next.xhtml', 0, 0.4),
    point('chapter.xhtml', 0.5, 0.7),
    point('next.xhtml', 0, Number.NaN),
    point('later.xhtml', 0, 0.3)
  ];

  assert.equal(readiumTotalProgression(
    point('chapter.xhtml', 0.75, 0.2),
    positions
  ), 0.85);

  const missingThenValid = [
    point('chapter.xhtml', 0, 0.2),
    point('earlier-next.xhtml', 0, 0.4),
    point('chapter.xhtml', 0.5, 0.7),
    point('next-missing.xhtml', 0),
    point('later.xhtml', 0, 0.9)
  ];
  assert.equal(readiumTotalProgression(
    point('chapter.xhtml', 0.75, 0.2),
    missingThenValid
  ), 0.8);
});

type ReadCounts = {
  position: number;
  href: number;
  locations: number;
  progression: number;
  totalProgression: number;
};

function countedPositions(size: number) {
  const reads: ReadCounts = {
    position: 0,
    href: 0,
    locations: 0,
    progression: 0,
    totalProgression: 0
  };
  const positionList = Array.from({ length: size }, (_, index): ProgressPoint => {
    const locations: ProgressPoint['locations'] = {
      progression: index === size - 1 ? 1 : 0,
      totalProgression: index === size - 1 ? 1 : 0
    };
    const countedLocations = new Proxy(locations, {
      get(target, property, receiver) {
        if (property === 'progression') reads.progression += 1;
        if (property === 'totalProgression') reads.totalProgression += 1;
        return Reflect.get(target, property, receiver);
      }
    });
    const position: ProgressPoint = { href: 'chapter.xhtml', locations: countedLocations };
    return new Proxy(position, {
      get(target, property, receiver) {
        if (property === 'href') reads.href += 1;
        if (property === 'locations') reads.locations += 1;
        return Reflect.get(target, property, receiver);
      }
    });
  });
  const positions = new Proxy(positionList, {
    get(target, property, receiver) {
      if (typeof property === 'string' && /^\d+$/u.test(property)) reads.position += 1;
      return Reflect.get(target, property, receiver);
    }
  });
  return { positions, reads };
}

test('keeps metadata reads within linear bounds for 10k and 20k positions', () => {
  const perPositionReadLimit = 12;
  const measured: number[] = [];

  for (const size of [10_000, 20_000]) {
    const input = countedPositions(size);
    const result = readiumTotalProgression(
      point('chapter.xhtml', 0.5, 0),
      input.positions
    );
    const reads = input.reads.position
      + input.reads.href
      + input.reads.locations
      + input.reads.progression
      + input.reads.totalProgression;

    assert.equal(result, 0.5);
    assert.ok(reads <= size * perPositionReadLimit, `${size} positions caused ${reads} metadata reads`);
    measured.push(reads);
  }

  assert.ok(measured[1] <= measured[0] * 2 + 64, `20k reads ${measured[1]} exceeded linear scaling from 10k reads ${measured[0]}`);
});
