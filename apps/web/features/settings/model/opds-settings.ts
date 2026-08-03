export function initialOpdsPublicBaseUrl(
  savedPublicBaseUrl: string | undefined,
  currentOrigin: string
) {
  return savedPublicBaseUrl?.trim() || currentOrigin;
}
