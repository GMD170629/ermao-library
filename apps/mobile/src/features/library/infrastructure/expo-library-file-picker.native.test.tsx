import { ExpoLibraryFilePicker } from './expo-library-file-picker';

function selectedFile(
  overrides: Partial<
    Blob & Readonly<{ name: string; size: number; type: string }>
  > = {},
): Blob & Readonly<{ name: string; size: number; type: string }> {
  const blob = new Blob(['book'], { type: 'application/epub+zip' });
  return Object.assign(blob, { name: 'book.epub' }, overrides);
}

test('maps selected Expo files into the application upload boundary', async () => {
  const file = selectedFile();
  const picker = new ExpoLibraryFilePicker(async () => ({
    canceled: false,
    result: [file],
  }));

  const result = await picker.pickFiles();

  expect(result).toEqual({
    outcome: 'selected',
    files: [
      {
        name: 'book.epub',
        mimeType: 'application/epub+zip',
        sizeBytes: 4,
        content: file,
      },
    ],
  });
});

test('treats system cancellation as a normal picker outcome', async () => {
  const picker = new ExpoLibraryFilePicker(async () => ({
    canceled: true,
    result: null,
  }));

  await expect(picker.pickFiles()).resolves.toEqual({
    outcome: 'cancelled',
  });
});

test('contains native picker failures without exposing an exception message', async () => {
  const picker = new ExpoLibraryFilePicker(async () => {
    throw new TypeError('private provider path');
  });

  await expect(picker.pickFiles()).resolves.toEqual({
    outcome: 'failed',
    reason: 'TypeError',
  });
});
