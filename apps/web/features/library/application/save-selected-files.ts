import { postUploadedFiles, type SaveUploadedFilesResult } from '../api/save-uploaded-files';

export async function saveSelectedFiles({
  files,
  targetPath
}: {
  files: File[];
  targetPath: string;
}): Promise<SaveUploadedFilesResult> {
  const form = new FormData();
  form.append('targetPath', targetPath);
  files.forEach((file) => form.append('files', file));
  return postUploadedFiles(form);
}
