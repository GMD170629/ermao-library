import assert from 'node:assert/strict';
import test from 'node:test';
import {
  comparePublicationLocations,
  parsePublicationLocation,
  quantizePageProgression,
  type PublicationLocation
} from '@shuku/reader-core';
import audioRequest from '../../../../packages/reader-contracts/fixtures/exact-audio-request.json';
import comicRequest from '../../../../packages/reader-contracts/fixtures/exact-comic-request.json';
import pdfRequest from '../../../../packages/reader-contracts/fixtures/exact-pdf-request.json';
import reflowableRequest from '../../../../packages/reader-contracts/fixtures/exact-reflowable-request.json';
import { publicationLocationFromDomain, v4LocationToDomain } from './progress-wire';

const fixtures = [reflowableRequest, pdfRequest, comicRequest, audioRequest];

test('parses every canonical publication-location morphology and rejects legacy envelopes', () => {
  assert.deepEqual(fixtures.map((fixture) => parsePublicationLocation(fixture.locator)?.kind), [
    'reflowable', 'pdf', 'comic', 'audio'
  ]);
  const audio = parsePublicationLocation(audioRequest.locator);
  assert.ok(audio?.kind === 'audio');
  assert.equal(audio.assetId, 'audio-asset-1');
  assert.equal(parsePublicationLocation({
    engine: 'readium', platform: 'web', version: 'legacy', publication: {}, payload: {}
  }), null);
});

test('enforces zero-based exact page anchors and safe comic resources', () => {
  const pdf = parsePublicationLocation(pdfRequest.locator);
  const comic = parsePublicationLocation(comicRequest.locator);
  assert.ok(pdf?.kind === 'pdf' && comic?.kind === 'comic');
  assert.equal(parsePublicationLocation({ ...pdf, pageIndex: -1 }), null);
  assert.equal(parsePublicationLocation({ ...pdf, pageProgression: 0.12345 }), null);
  assert.equal(parsePublicationLocation({
    ...pdf,
    engineLocator: { engine: 'readium', platform: 'web', version: 'pdfjs:1', payload: { destination: [7, 0.5] } }
  })?.kind, 'pdf');
  assert.equal(parsePublicationLocation({ ...comic, resourceHref: '../escape.jpg' }), null);
  assert.equal(parsePublicationLocation({ ...pdf, resourceHref: 'page.jpg' }), null);
  assert.equal(parsePublicationLocation({
    ...comic,
    unexpected: true
  }), null);
  assert.equal(quantizePageProgression(0.12345), 0.1235);
});

test('keeps PDF and comic locations zero-based across domain and wire data', () => {
  const pdf = parsePublicationLocation(pdfRequest.locator);
  const comic = parsePublicationLocation(comicRequest.locator);
  assert.ok(pdf?.kind === 'pdf' && comic?.kind === 'comic');
  const pdfDomain = v4LocationToDomain(pdf, 'resource-pdf', null);
  const comicDomain = v4LocationToDomain(comic, 'resource-comic', null);
  assert.equal(pdfDomain?.kind === 'pdf' ? pdfDomain.pageIndex : null, pdf.pageIndex);
  assert.equal(comicDomain?.kind === 'comic' ? comicDomain.pageIndex : null, comic.pageIndex);
  assert.deepEqual(pdfDomain ? publicationLocationFromDomain(pdfDomain) : null, pdf);
  assert.deepEqual(comicDomain ? publicationLocationFromDomain(comicDomain) : null, comic);
});

test('compares exact locations only within the same morphology', () => {
  const pdf = parsePublicationLocation(pdfRequest.locator) as PublicationLocation;
  const comic = parsePublicationLocation(comicRequest.locator) as PublicationLocation;
  assert.equal(comparePublicationLocations(pdf, pdf).precision, 'exact');
  assert.equal(comparePublicationLocations(comic, comic).precision, 'exact');
  assert.equal(comparePublicationLocations(pdf, comic).reason, 'kind_mismatch');
  assert.equal(comparePublicationLocations(pdf, { ...pdf, pageProgression: 0 } as PublicationLocation).precision, 'unverified');
});
