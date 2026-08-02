export function directoryPathChain(path: string): string[] {
  if (!path.startsWith('/')) return [];
  const segments = path.split('/').filter(Boolean);
  let currentPath = '';
  return [
    '/',
    ...segments.map((segment) => {
      currentPath += `/${segment}`;
      return currentPath;
    })
  ];
}
