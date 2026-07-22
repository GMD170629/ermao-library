import assert from 'node:assert/strict';
import test from 'node:test';
import { generateEpubLocations, generateEpubSectionLocations } from './epub-location-generation';

type FakeRange = {
  startContainer?: FakeNode;
  startOffset?: number;
  endContainer?: FakeNode;
  endOffset?: number;
  setStart: (node: FakeNode, offset: number) => void;
  setEnd: (node: FakeNode, offset: number) => void;
};

type FakeNode = {
  id: string;
  nodeType: number;
  textContent: string;
  length: number;
  childNodes: FakeNode[];
};

function sectionDocument(id: string, text: string) {
  const textNode: FakeNode = { id, nodeType: 3, textContent: text, length: text.length, childNodes: [] };
  const body: FakeNode = { id: `${id}-body`, nodeType: 1, textContent: text, length: 0, childNodes: [textNode] };
  const document = {
    querySelector: (selector: string) => selector === 'body' ? body : null,
    createRange: (): FakeRange => ({
      setStart(node, offset) { this.startContainer = node; this.startOffset = offset; },
      setEnd(node, offset) { this.endContainer = node; this.endOffset = offset; }
    })
  };
  return { ownerDocument: document } as unknown as Element;
}

function fakeSection(id: string, text = 'abcdefghijk') {
  let unloaded = 0;
  const contents = sectionDocument(id, text);
  return {
    linear: true,
    load: async () => contents,
    unload: () => { unloaded += 1; },
    cfiFromRange: (range: Range) => {
      const value = range as unknown as FakeRange;
      return `epubcfi(${id}:${value.startOffset}-${value.endOffset})`;
    },
    unloaded: () => unloaded
  };
}

test('EPUB section generation preserves character-range location boundaries', () => {
  const section = fakeSection('chapter-1');
  const generated = generateEpubSectionLocations(
    sectionDocument('chapter-1', 'abcdefghijk'),
    section as never,
    4
  );
  assert.deepEqual(generated, [
    'epubcfi(chapter-1:1-5)',
    'epubcfi(chapter-1:6-10)',
    'epubcfi(chapter-1:11-11)'
  ]);
});

test('EPUB location generation removes the per-chapter delay and reports real progress', async () => {
  const sections = Array.from({ length: 4 }, (_, index) => fakeSection(`chapter-${index + 1}`));
  const progress: Array<[number, number]> = [];
  const startedAt = Date.now();
  const generated = await generateEpubLocations({
    load: async () => ({}),
    spine: { each: (visit: (section: unknown) => void) => sections.forEach(visit) }
  } as never, {
    breakSize: 1200,
    onProgress: ({ completed, total }) => progress.push([completed, total])
  });

  assert.equal(generated.length, 4);
  assert.deepEqual(progress, [[0, 4], [1, 4], [2, 4], [3, 4], [4, 4]]);
  assert.ok(Date.now() - startedAt < 200, 'generation must not retain epub.js 100ms-per-section pauses');
  assert.deepEqual(sections.map((section) => section.unloaded()), [1, 1, 1, 1]);
});

test('EPUB location generation aborts at a chapter boundary and unloads active content', async () => {
  const sections = Array.from({ length: 3 }, (_, index) => fakeSection(`chapter-${index + 1}`));
  const controller = new AbortController();
  await assert.rejects(generateEpubLocations({
    load: async () => ({}),
    spine: { each: (visit: (section: unknown) => void) => sections.forEach(visit) }
  } as never, {
    breakSize: 1200,
    signal: controller.signal,
    concurrency: 1,
    onProgress: ({ completed }) => {
      if (completed === 1) controller.abort();
    }
  }), (reason: unknown) => reason instanceof DOMException && reason.name === 'AbortError');

  assert.deepEqual(sections.map((section) => section.unloaded()), [1, 0, 0]);
});
