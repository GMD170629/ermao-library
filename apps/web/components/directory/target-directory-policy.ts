export type LibraryPath = {
  rootPath: string;
  enabled: boolean;
};

export function normalizeDirectoryPath(path: string): string {
  return path.replace(/\/+$/, '') || path;
}

export function isDirectoryInside(rootPath: string, targetPath: string): boolean {
  const root = normalizeDirectoryPath(rootPath);
  const target = normalizeDirectoryPath(targetPath);
  return target === root || target.startsWith(`${root}/`);
}

export function enabledLibraryRootPaths(folders: LibraryPath[]): string[] {
  return folders
    .filter((folder) => folder.enabled)
    .map((folder) => normalizeDirectoryPath(folder.rootPath));
}

export function isAllowedTargetPath(path: string, allowedRootPaths: string[]): boolean {
  return allowedRootPaths.some((rootPath) => isDirectoryInside(rootPath, path));
}
